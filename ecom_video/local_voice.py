"""Optional VoiceStudio REST connector; no upstream application code is embedded."""

import json
import os
import re
import time

import httpx

from . import voice_takes
from .creative import signature
from .customer import uid
from .db import Conflict
from .media import digest, inspect_media, safe_path
from .resource_leases import Lease
from .voicestudio_bridge import MODEL, REVISION, VOICE
from .volc_voice import VolcVoice

ENGINES = ("mlx-audio",)
MAX_AUDIO = 12 * 1024**2


class LocalVoiceError(ValueError):
    pass


def endpoint():
    value = os.environ.get("ECOM_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", value)
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise LocalVoiceError(
            "VoiceStudio 地址须为本机 http://127.0.0.1:端口，不接受公网、路径或凭据"
        )
    return value


class LocalVoice(VolcVoice):
    def client(self, timeout):
        key = os.environ.get("ECOM_VOICESTUDIO_API_KEY", "")
        if key and (len(key) > 4096 or any(not 33 <= ord(c) <= 126 for c in key)):
            raise LocalVoiceError("本机 VoiceStudio 凭据格式无效")
        return httpx.Client(
            base_url=endpoint(),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
            headers={"Authorization": "Bearer " + key} if key else {},
        )

    @staticmethod
    def status_json(client, path):
        deadline = time.monotonic() + 3
        data = bytearray()
        with client.stream("GET", path) as response:
            if response.status_code != 200:
                raise LocalVoiceError("unavailable")
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 65536 or time.monotonic() > deadline:
                    raise LocalVoiceError("unavailable")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise LocalVoiceError("unavailable")
        return value

    def status(self):
        try:
            with self.client(3) as client:
                # The contract checks the actual backend's availability and model.
                # The general inventory imports unrelated optional engines on cold
                # startup and cannot prove which cached model generates speech.
                contract = self.status_json(client, "/ecom/voice-contract")
                ready = contract == {
                    "version": 1,
                    "engine": "mlx-audio",
                    "model": MODEL,
                    "revision": REVISION,
                    "voice": VOICE,
                }
                engines = list(ENGINES) if ready else []
                return {
                    "connected": True,
                    "ready": ready,
                    "engines": engines,
                    "provider": "voicestudio",
                    "live_audio_verified": False,
                    "message": "已连接固定模型的本机 Kokoro 服务。中文声音仍须实际试听；不代表已通过听核。"
                    if ready
                    else "本机服务已连接，但未通过具体模型绑定。请使用指南中的固定 Kokoro 启动方式；原生服务仅显示模型名称仍不足以合成，未发送文稿。",
                }
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return {
                "connected": False,
                "ready": False,
                "engines": [],
                "provider": "voicestudio",
                "live_audio_verified": False,
                "message": "未连接本机固定模型服务。请按指南启动 VoiceStudio 专用服务（默认3900端口）；首次初始化可稍后再检查，仍可上传配音或选择火山。",
            }

    def audio(self, text, model, speed):
        try:
            with (
                self.client(180) as client,
                client.stream(
                    "POST",
                    "/v1/audio/speech",
                    headers={"X-Ecom-Expected-Model": MODEL, "X-Ecom-Expected-Revision": REVISION},
                    json={
                        "model": model,
                        "voice": VOICE,
                        "input": text,
                        "response_format": "wav",
                        "speed": speed,
                        "language": "zh",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    raise LocalVoiceError(
                        "本机配音未完成，请在 VoiceStudio 检查模型安装、授权、中文支持与内存。未自动重试或改用收费配音。"
                    )
                if (
                    response.headers.get("X-Ecom-Voice-Model") != MODEL
                    or response.headers.get("X-Ecom-Voice-Revision") != REVISION
                ):
                    raise LocalVoiceError("本机返回的具体模型凭据不符，音频未采用")
                data = bytearray()
                deadline = time.monotonic() + 180
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_AUDIO or time.monotonic() > deadline:
                        raise LocalVoiceError("本机配音超过大小上限，未保存或自动重试")
            if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise LocalVoiceError("本机返回了无效音频，未采用")
            return bytes(data)
        except httpx.HTTPError:
            raise LocalVoiceError(
                "本机配音连接失败或超时；请检查 VoiceStudio 后手动重试，未转用云配音"
            ) from None

    def generate(self, pid, data):
        with self.lock(pid):
            p, text, script_hash = self.confirmed(
                pid, data.revision, data.product_revision, data.draft_id
            )
            existing = next((a for a in p["media"] if a["role"] == "voice"), None)
            if not data.preview and (existing["id"] if existing else None) != data.replace_voice_id:
                raise Conflict("当前声音已变化，请重新载入后明确替换")
            if existing and not data.preview:
                path = safe_path(self.root, existing["path"])
                if not path.is_file() or digest(path) != existing["sha256"]:
                    raise Conflict("旧声音文件已变化，未合成")
            params = {
                "provider": "voicestudio",
                "engine": data.engine,
                "speaker": VOICE,
                "model": MODEL,
                "model_revision": REVISION,
                "speed": data.speed,
                "script_hash": script_hash,
                "draft_id": data.draft_id,
                "human_listening": "pending",
                "local_engine_confirmed": True,
            }
            scope = "preview" if data.preview else "full"
            key = signature({"params": params, "scope": scope, "endpoint": endpoint()})
            with self.store.connect() as c:
                prior = c.execute(
                    "SELECT * FROM voice_takes WHERE product_id=? AND request_hash=? AND scope=?",
                    (pid, key, scope),
                ).fetchone()
                if data.preview and prior:
                    voice_takes.file(self.root, dict(prior))
                    return self.customers.get(pid)
                voice_takes.budget(c, pid, MAX_AUDIO, 2 if existing else 1)
            with Lease(self.store) as lease:
                state = self.status()
                if not state.get("ready"):
                    raise LocalVoiceError(state["message"])
                audio = self.audio(
                    text.splitlines()[0] if data.preview else text, data.engine, data.speed
                )
                lease.check()
            aid = uid()
            relative = f"customers/{pid}/media/{aid}.wav"
            path = safe_path(self.root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as out:
                    out.write(audio)
                metadata = inspect_media(path, "audio")
                if not 0 < metadata["duration"] <= 90:
                    raise LocalVoiceError("本机配音时长无效或超过90秒，未采用")
                metadata["voice_source"] = params | {"take_id": aid}
                asset = {
                    "id": aid,
                    "name": "VoiceStudio首句试听.wav"
                    if data.preview
                    else "VoiceStudio本机配音.wav",
                    "path": relative,
                    "kind": "audio",
                    "role": "voice",
                    "sha256": digest(path),
                    "size": len(audio),
                    "metadata": metadata,
                }
                take = {
                    "draft_id": data.draft_id,
                    "script_hash": script_hash,
                    "scope": scope,
                    "params": params,
                    "request_hash": key,
                }
                if data.preview:
                    with self.store.transaction() as c:
                        self.customers.row(c, pid, data.revision)
                        self.customers.products._row(c, pid, data.product_revision)
                        voice_takes.budget(c, pid, len(audio), 1)
                        voice_takes.insert(c, asset, pid, **take)
                    return self.customers.get(pid)
                return self.customers.add_media(
                    pid,
                    data.revision,
                    asset,
                    product_revision=data.product_revision,
                    replace_voice_id=data.replace_voice_id,
                    voice_take=take,
                )
            except BaseException:
                with self.store.connect() as c:
                    committed = c.execute(
                        "SELECT 1 FROM voice_takes WHERE path=? UNION SELECT 1 FROM customer_media WHERE path=?",
                        (relative, relative),
                    ).fetchone()
                if not committed:
                    path.unlink(missing_ok=True)
                raise
