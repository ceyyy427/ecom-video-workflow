"""Explicit, bounded cloud narration. No background retries or voice cloning."""

import base64
import binascii
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx

from . import voice_takes
from .creative import signature
from .customer import Customers, uid
from .db import Conflict
from .host_os import file_lock, open_lock
from .media import digest, inspect_media, safe_path
from .voice_profiles import PROFILES
from .voice_profiles import VERSION as PROFILE_VERSION

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
RESOURCE = "seed-tts-2.0"
SPEAKERS = {
    "zh_female_vv_uranus_bigtts": "Vivi · 合成女声",
    "zh_female_gaolengyujie_uranus_bigtts": "高冷御姐 · 合成女声",
}
DEFAULT_SPEAKER = "zh_female_vv_uranus_bigtts"
MAX_RESPONSE = 12 * 1024**2
MAX_AUDIO = 6 * 1024**2
MAX_SECONDS = 90
CONFIG_ERROR = "火山配音未配置或本机配置无效；请使用本机配置命令设置 API Key。"
PROVIDER_ERROR = "火山配音未成功完成；请核对账户权限、额度与网络后手动重试。未保存不完整音频。"
RESOURCE_ERROR = "火山语音资源未授权；请在豆包语音新版控制台的同一项目内，核对开通管理中的语音合成2.0字符版服务及 API Key 启用状态。未取得完整音频，不会自动重试。"
ERROR_MESSAGES = {
    "resource_not_granted": RESOURCE_ERROR,
    "credentials_rejected": "火山拒绝此语音凭据；请核对它是否为豆包语音新版控制台同一项目内启用的 API Key，而非方舟大模型或 Agent Plan 专属 Key。",
    "access_denied": "火山拒绝访问；请核对语音 Key 所属项目、服务开通和账户访问权限。尚不能仅凭 HTTP 403 确定是哪项权限缺失。",
    "rate_limited": "火山返回请求频率或配额限制；请在同一项目控制台核对额度与并发，未自动重试。",
    "network_error": "火山语音网络请求失败或超时；未取得完整音频，不会自动重试。",
}


class VoiceError(Exception):
    """Only fixed, public-safe failure messages cross the HTTP boundary."""

    def __init__(self, message=PROVIDER_ERROR, *, code=None, provider_code=None, http_status=None):
        super().__init__(message)
        self.code = code or ("configuration_error" if message == CONFIG_ERROR else "provider_error")
        self.provider_code = provider_code if type(provider_code) is int else None
        self.http_status = http_status if type(http_status) is int else None

    def details(self):
        return {
            "error_code": self.code,
            "message": str(self),
            "provider_code": self.provider_code,
            "http_status": self.http_status,
        }


def provider_error(payload=None, http_status=None):
    """Classify recognized evidence; never echo untrusted provider messages or IDs."""
    payload = payload if isinstance(payload, dict) else {}
    message = payload.get("message")
    message = message.lower() if isinstance(message, str) else ""
    code = "provider_error"
    if "requested resource not granted" in message:
        code = "resource_not_granted"
    elif http_status == 401:
        code = "credentials_rejected"
    elif http_status == 403:
        code = "access_denied"
    elif http_status == 429:
        code = "rate_limited"
    return VoiceError(
        ERROR_MESSAGES.get(code, PROVIDER_ERROR),
        code=code,
        provider_code=payload.get("code"),
        http_status=http_status,
    )


def config_path():
    return Path(
        os.environ.get("ECOM_VOLC_VOICE_CONFIG", "~/.config/ecom-video/volc-voice.json")
    ).expanduser()


def read_config():
    try:
        if "DOUBAO_TTS_API_KEY" in os.environ:
            data = {"api_key": os.environ["DOUBAO_TTS_API_KEY"]}
        else:
            from .voice_config import load_config

            data = load_config(config_path())
        key = data.get("api_key")
        speaker = data.get("speaker", DEFAULT_SPEAKER)
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in key)
            or speaker not in SPEAKERS
        ):
            raise ValueError
        return key, speaker
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        raise VoiceError(CONFIG_ERROR) from None


def status():
    try:
        _, speaker = read_config()
        configured = True
    except VoiceError:
        speaker, configured = DEFAULT_SPEAKER, False
    ark_key_detected = bool(os.environ.get("ARK_API_KEY"))
    return {
        "configured": configured,
        "ark_key_detected": ark_key_detected,
        "provider": "volcengine",
        "resource": RESOURCE,
        "speaker": speaker,
        "speakers": SPEAKERS,
        "profiles": PROFILES,
        "profile_version": PROFILE_VERSION,
        "mode": "synthetic_narration",
        "live_verified": False,
        "max_characters": 3000,
        "message": "已配置，尚未验证账户调用权限。"
        if configured
        else (
            "检测到火山方舟大模型环境变量；它不是本工作流的语音合成配置。请单独配置火山语音 API Key，或上传成品配音。"
            if ark_key_detected
            else CONFIG_ERROR
        ),
    }


def parse_sse(raw):
    """Require an explicit terminal success and reject any partial/error stream."""
    audio, finished = bytearray(), False
    try:
        if len(raw) > MAX_RESPONSE:
            raise ValueError
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        for block in text.split("\n\n"):
            lines = block.splitlines()
            parts = [line[5:].lstrip(" ") for line in lines if line.startswith("data:")]
            if not parts:
                continue
            if finished:
                raise ValueError
            event = next((line[6:].strip() for line in lines if line.startswith("event:")), "")
            data = json.loads("\n".join(parts))
            if not isinstance(data, dict):
                raise ValueError
            if event in ("151", "153"):
                raise provider_error(data)
            code = data.get("code")
            if type(code) is not int or code not in (0, 20000000):
                raise provider_error(data)
            if data.get("data") is not None:
                if not isinstance(data["data"], str):
                    raise ValueError
                audio.extend(base64.b64decode(data["data"], validate=True))
                if len(audio) > MAX_AUDIO:
                    raise ValueError
            if code == 20000000:
                if event not in ("", "152"):
                    raise ValueError
                finished = True
        if not finished or not audio:
            raise ValueError
        return bytes(audio)
    except (UnicodeError, ValueError, TypeError, binascii.Error):
        raise VoiceError(PROVIDER_ERROR) from None


def synthesize(text, speaker, key, transport=None, *, direction=None, speech_rate=0):
    if type(speech_rate) is not int or not -20 <= speech_rate <= 20:
        raise ValueError("配音语速须为 -20 至 20 的整数。")
    if direction is not None and (
        not isinstance(direction, str) or not 1 <= len(direction) <= 300 or not direction.strip()
    ):
        raise ValueError("配音语气说明须为 1 至 300 字。")
    params = {
        "text": text,
        "speaker": speaker,
        "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": speech_rate},
    }
    if direction is not None:
        params["additions"] = json.dumps({"context_texts": [direction]}, ensure_ascii=False)
    started = time.monotonic()
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(10, connect=10),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                "POST",
                ENDPOINT,
                headers={
                    "X-Api-Key": key,
                    "X-Api-Resource-Id": RESOURCE,
                    "X-Api-Request-Id": str(uuid.uuid4()),
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                },
                json={"req_params": params},
            ) as response,
        ):
            if response.status_code != 200:
                error_body = bytearray()
                for chunk in response.iter_bytes():
                    if (
                        len(error_body) + len(chunk) > 8192
                        or time.monotonic() - started > MAX_SECONDS
                    ):
                        break
                    error_body.extend(chunk)
                try:
                    payload = json.loads(error_body)
                except (ValueError, UnicodeError):
                    payload = None
                raise provider_error(payload, response.status_code)
            raw = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() - started > MAX_SECONDS or len(raw) + len(chunk) > MAX_RESPONSE:
                    raise VoiceError(PROVIDER_ERROR)
                raw.extend(chunk)
            return parse_sse(raw)
    except httpx.HTTPError:
        raise VoiceError(ERROR_MESSAGES["network_error"], code="network_error") from None


class VolcVoice:
    def __init__(self, root, store, transport=None):
        self.root, self.store, self.transport = Path(root), store, transport
        self.customers = Customers(root, store)

    @contextmanager
    def lock(self, pid):
        directory = self.root / "voice-locks"
        directory.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(pid.encode()).hexdigest() + ".lock"
        # Keep lock files: unlinking would let another process lock a different inode.
        fd = open_lock(directory / name)
        try:
            try:
                file_lock(fd)
            except BlockingIOError:
                raise Conflict("此项目正在合成配音，请等待当前请求完成。") from None
            yield
        finally:
            os.close(fd)

    def confirmed(self, pid, revision, product_revision, draft_id):
        p = self.customers.get(pid)
        product = p["product"]
        if p["revision"] != revision or product["revision"] != product_revision:
            raise Conflict("项目或文稿已更新，请重新载入后合成。")
        if p["job"] and p["job"]["status"] in ("queued", "validating", "rendering", "auditing"):
            raise Conflict("项目正在制作，请等待结束后再添加配音。")
        approval = next((a for a in product["script_approvals"] if a["draft_id"] == draft_id), None)
        if (
            product["status"] != "script_confirmed"
            or product["current_draft_id"] != draft_id
            or not approval
        ):
            raise Conflict("请先人工确认当前文稿，再合成配音。")
        text = self.store.get(approval["job_id"])["script"]
        script_hash = hashlib.sha256(text.encode()).hexdigest()
        if script_hash != approval["script_hash"] or not 1 <= len(text) <= 3000:
            raise Conflict("已确认文稿校验失败，请重新核对。")
        return p, text, script_hash

    def generate(
        self,
        pid,
        revision,
        product_revision,
        draft_id,
        speaker=None,
        *,
        style_id=None,
        direction_basis=None,
        replace_voice_id=None,
        preview=False,
    ):
        with self.lock(pid):
            p, text, script_hash = self.confirmed(pid, revision, product_revision, draft_id)
            existing = next((a for a in p["media"] if a["role"] == "voice"), None)
            if not preview and existing and replace_voice_id != existing["id"]:
                raise Conflict("已有配音，请先明确移除旧配音再合成。")
            if replace_voice_id and (preview or not existing or existing["id"] != replace_voice_id):
                raise Conflict("待替换的配音已变化，请重新载入")
            profile = None
            if style_id is not None:
                if (
                    direction_basis != p["direction_basis"]
                    or not p["recommendations"]
                    or style_id not in {s["id"] for s in p["recommendations"]["options"]}
                ):
                    raise Conflict("风格依据已变化，请重新选定风格后试听")
                profile = PROFILES[style_id]
            elif direction_basis is not None or preview:
                raise ValueError("请先选择视频风格")
            if existing and replace_voice_id:
                path = safe_path(self.root, existing["path"])
                if not path.is_file() or digest(path) != existing["sha256"]:
                    raise Conflict("旧配音文件已变化，未发起新的云请求")
            if speaker is None:
                speaker = profile["speaker"] if profile else read_config()[1]
            if speaker not in SPEAKERS:
                raise ValueError("请选择支持的普通合成音色。")
            params = {
                "provider": "volcengine",
                "kind": "synthetic_narration",
                "speaker": speaker,
                "resource": RESOURCE,
                "draft_id": draft_id,
                "script_hash": script_hash,
                "product_revision": product_revision,
                "style_id": style_id,
                "profile_version": PROFILE_VERSION if profile else None,
                "direction": profile["direction"] if profile else None,
                "speech_rate": profile["speech_rate"] if profile else 0,
                "human_listening": "pending",
            }
            request_hash = signature({"params": params, "scope": "preview" if preview else "full"})
            if preview:
                with self.store.connect() as c:
                    prior = c.execute(
                        "SELECT * FROM voice_takes WHERE product_id=? AND scope='preview' AND request_hash=?",
                        (pid, request_hash),
                    ).fetchone()
                if prior:
                    voice_takes.file(self.root, dict(prior))
                    return self.customers.get(pid)
            with self.store.connect() as c:
                self.customers.row(c, pid, revision)
                self.customers.products._row(c, pid, product_revision)
                old_count = int(
                    bool(
                        existing
                        and replace_voice_id
                        and not voice_takes.saved_file(c, pid, existing)
                    )
                )
                voice_takes.budget(c, pid, MAX_AUDIO, 1 + old_count)
            key, _ = read_config()
            spoken = text.splitlines()[0] if preview else text
            audio = synthesize(
                spoken,
                speaker,
                key,
                self.transport,
                direction=params["direction"],
                speech_rate=params["speech_rate"],
            )
            aid = uid()
            relative = f"customers/{pid}/media/{aid}.mp3"
            path = safe_path(self.root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as out:
                    out.write(audio)
                try:
                    metadata = inspect_media(path, "audio")
                except ValueError:
                    raise VoiceError(PROVIDER_ERROR) from None
                metadata["voice_source"] = params | {"take_id": aid}
                a = {
                    "id": aid,
                    "name": "火山首句试听.mp3" if preview else "火山合成配音.mp3",
                    "path": relative,
                    "kind": "audio",
                    "role": "voice",
                    "sha256": digest(path),
                    "size": len(audio),
                    "metadata": metadata,
                }
                take = {
                    "draft_id": draft_id,
                    "script_hash": script_hash,
                    "scope": "preview" if preview else "full",
                    "params": params | ({"preview_text": spoken} if preview else {}),
                    "request_hash": request_hash,
                }
                if preview:
                    with self.store.transaction() as c:
                        self.customers.row(c, pid, revision)
                        self.customers.products._row(c, pid, product_revision)
                        voice_takes.budget(c, pid, len(audio), 1)
                        voice_takes.insert(c, a, pid, **take)
                    return self.customers.get(pid)
                return self.customers.add_media(
                    pid,
                    revision,
                    a,
                    product_revision=product_revision,
                    replace_voice_id=replace_voice_id,
                    voice_take=take,
                )
            except BaseException:
                # A response read can fail after add_media/preview has committed.
                # Preserve referenced files; only discard an uncommitted result.
                with self.store.connect() as c:
                    committed = c.execute(
                        "SELECT 1 FROM voice_takes WHERE path=? UNION SELECT 1 FROM customer_media WHERE path=?",
                        (relative, relative),
                    ).fetchone()
                if not committed:
                    path.unlink(missing_ok=True)
                raise

    def take_file(self, pid, aid):
        self.customers.get(pid)
        with self.store.connect() as c:
            take = voice_takes.get(c, pid, aid)
        return voice_takes.file(self.root, take)

    def use_take(self, pid, aid, revision, product_revision, draft_id):
        with self.lock(pid):
            p, _, script_hash = self.confirmed(pid, revision, product_revision, draft_id)
            with self.store.connect() as c:
                take = voice_takes.get(c, pid, aid)
            if take["scope"] != "full" or (
                take["script_hash"] and take["script_hash"] != script_hash
            ):
                raise Conflict("只能采用与当前确认文稿一致的完整配音；首句试听不能用于成片")
            path = voice_takes.file(self.root, take)
            existing = next((a for a in p["media"] if a["role"] == "voice"), None)
            if (
                existing
                and (existing["metadata"].get("voice_source", {}).get("take_id") or existing["id"])
                == aid
            ):
                return p
            metadata = inspect_media(path, "audio")
            metadata["voice_source"] = json.loads(take["params"]) | {
                "take_id": aid,
                "human_listening": "pending",
            }
            return self.customers.add_media(
                pid,
                revision,
                {
                    "id": uid(),
                    "name": "恢复的历史配音" + path.suffix,
                    "path": take["path"],
                    "kind": "audio",
                    "role": "voice",
                    "sha256": take["sha256"],
                    "size": take["size"],
                    "metadata": metadata,
                },
                product_revision=product_revision,
                replace_voice_id=existing["id"] if existing else None,
            )
