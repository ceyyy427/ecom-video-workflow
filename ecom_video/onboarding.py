"""Fixed-purpose, local setup. Never infer media, synthesize speech, or approve work."""

import os
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import SecretStr

from . import vision_model
from .creative import Strict
from .customer_launcher import installation_id
from .customer_setup import PROJECT, configure_vision
from .voice_config import save_config
from .volc_voice import DEFAULT_SPEAKER, config_path, status


class VoiceSetup(Strict):
    api_key: SecretStr
    speaker: Literal["zh_female_vv_uranus_bigtts", "zh_female_gaolengyujie_uranus_bigtts"] = (
        DEFAULT_SPEAKER
    )
    replace: bool = False


class VisionSetup(Strict):
    model: str


class InstallASR(Strict):
    confirmed: Literal[True]


def router(root, store):
    from .model_install import ModelInstall

    api = APIRouter()
    install = ModelInstall(PROJECT)
    config_lock = threading.Lock()

    def idle():
        from .maintenance import PENDING

        with store.connect() as c:
            for table, states in PENDING.items():
                if c.execute(
                    f"SELECT 1 FROM {table} WHERE status IN ({','.join('?' for _ in states)}) LIMIT 1",
                    states,
                ).fetchone():
                    raise HTTPException(
                        409, "仍有待执行或运行任务；请先在制作页暂停/取消并等待停止，再修改模型。"
                    )

    @api.get("/api/setup/instance")
    def instance():
        return {
            "installation": installation_id(PROJECT, root),
            "customer": os.getenv("ECOM_CUSTOMER_MODE") == "1",
        }

    @api.get("/api/setup/status")
    def get_status():
        models, issue = [], ""
        try:
            rows = vision_model.request("/api/tags").get("models", [])
            models = [
                r["name"]
                for r in rows[:100]
                if isinstance(r.get("name"), str)
                and len(r["name"]) <= 160
                and not (
                    r.get("remote_host") or r.get("remote_model") or "cloud" in r["name"].lower()
                )
            ]
        except (ValueError, KeyError, TypeError):
            issue = "尚未连接本机 Ollama。打开 Ollama 应用后重新检查；也可先用手动选段。"
        try:
            current = vision_model.model_name()
        except (ValueError, OSError, KeyError):
            current = ""
            issue = "本机视觉配置无效，请重新选择模型。"
        voice = status()
        return {
            "vision": {
                "models": models,
                "selected": current,
                "message": issue,
                "environment_override": "ECOM_VISION_MODEL" in os.environ,
            },
            "asr": {
                "present": all(
                    (PROJECT / "var/models/firered" / n).is_file()
                    for n in ("model.int8.onnx", "tokens.txt")
                ),
                "verification": "点击安装/校验按钮后执行 SHA256 校验",
            },
            "voice": {
                "configured": voice["configured"],
                "speaker": voice["speaker"],
                "speakers": voice["speakers"],
                "message": voice["message"]
                if voice["configured"]
                else "配音尚未配置；可在本页保存语音 Key，或直接上传成品配音。",
                "environment_override": "DOUBAO_TTS_API_KEY" in os.environ,
                "live_verified": False,
            },
            "manual_gates": ["事实", "文稿", "风格", "听核", "成片审核"],
            "platform_writes": os.getenv("ECOM_QIANCHUAN_WRITES", "0") == "1",
        }

    @api.post("/api/setup/voice")
    def configure_voice(data: VoiceSetup):
        with config_lock:
            if "DOUBAO_TTS_API_KEY" in os.environ:
                raise HTTPException(
                    409,
                    "当前语音 Key 来自启动环境；网页保存不会覆盖它。请先移除该环境变量并重启，或继续使用现有配置。",
                )
            try:
                save_config(
                    config_path(),
                    data.api_key.get_secret_value().strip(),
                    data.speaker,
                    data.replace,
                )
            except FileExistsError:
                raise HTTPException(409, "已有本机配音配置；确认替换后再保存。") from None
            except (OSError, ValueError):
                raise HTTPException(
                    422, "未保存：请检查语音 Key 格式和本机私有配置目录权限。"
                ) from None
        return {
            "saved": True,
            "live_verified": False,
            "message": "已保存本机私有文件；没有调用配音服务。请在文稿确认后按页面授权试听。",
        }

    @api.post("/api/setup/vision")
    def configure_local_vision(data: VisionSetup):
        with config_lock:
            idle()
            if "ECOM_VISION_MODEL" in os.environ:
                raise HTTPException(
                    409, "视觉模型由启动环境固定；请先移除 ECOM_VISION_MODEL 并重启后再从页面选择。"
                )
            return configure_vision(data.model, vision_model.CONFIG)

    @api.get("/api/setup/asr")
    def model_progress():
        return install.status()

    @api.post("/api/setup/asr")
    def install_model(data: InstallASR):
        idle()
        return install.start()

    @api.post("/api/setup/asr/cancel")
    def cancel_model():
        return install.cancel()

    return api
