"""Run the independently installed official VoiceStudio with a fixed model.

No upstream application implementation is copied here. Its unmodified API still
performs synthesis; this extension verifies the actual backend used by that API.
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

MODEL = "mlx-community/Kokoro-82M-bf16"
REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
VOICE = "zf_xiaobei"


def require_backend(backend):
    if backend.id != "mlx-audio" or backend.model_identity() != MODEL:
        raise ValueError("实际缓存的配音模型不符，未合成；请重启固定模型服务")
    return backend


class KokoroBackend:
    """Keep MLX's voice lookup on the same verified offline snapshot."""

    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def generate(self, text, **kwargs):
        backend = require_backend(self.backend)
        # MLX-Audio 0.5.0 otherwise defaults voice tensors to a different repo.
        # This runs inside VoiceStudio's own bounded GPU generation worker.
        backend._ensure_loaded()
        backend._model.repo_id = MODEL
        for pipeline in backend._model._pipelines.values():
            pipeline.repo_id = MODEL
        return backend.generate(text, **kwargs)


class NoWebSockets:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def install(app, compat=None):
    from fastapi.responses import JSONResponse

    if compat is None:
        from api.routers import openai_compat as compat
    original = compat._resolve_engine

    def resolve(engine):
        if engine != "mlx-audio":
            raise compat.OpenAIError(400, "只允许固定的本机 Kokoro 模型")
        try:
            return KokoroBackend(require_backend(original(engine)))
        except ValueError:
            raise compat.OpenAIError(503, "实际缓存的配音模型不符，未合成") from None

    compat._resolve_engine = resolve
    app.add_middleware(NoWebSockets)

    @app.get("/ecom/voice-contract")
    def contract():
        resolve("mlx-audio")
        return {
            "version": 1,
            "engine": "mlx-audio",
            "model": MODEL,
            "revision": REVISION,
            "voice": VOICE,
        }

    @app.middleware("http")
    async def fixed_model(request, call_next):
        if request.headers.get("origin") or request.url.hostname != "127.0.0.1":
            return JSONResponse({"detail": "仅接受本机程序连接"}, status_code=403)
        if request.method == "GET" and request.url.path in (
            "/health",
            "/engines/tts",
            "/ecom/voice-contract",
        ):
            return await call_next(request)
        if request.method != "POST" or request.url.path != "/v1/audio/speech":
            return JSONResponse({"detail": "本机配音专用服务"}, status_code=404)
        if (
            request.headers.get("X-Ecom-Expected-Model"),
            request.headers.get("X-Ecom-Expected-Revision"),
        ) != (MODEL, REVISION):
            return JSONResponse({"detail": "缺少具体模型约束，未合成"}, status_code=409)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                return JSONResponse({"detail": "文稿过长，未合成"}, status_code=413)
        import json

        try:
            data = json.loads(raw)
            valid = (
                isinstance(data, dict)
                and data.get("model") == "mlx-audio"
                and data.get("voice") == VOICE
                and data.get("language") == "zh"
            )
            valid = valid and set(data) <= {
                "model",
                "voice",
                "input",
                "response_format",
                "speed",
                "language",
            }
        except (ValueError, TypeError):
            valid = False
        if not valid:
            return JSONResponse({"detail": "只允许固定中文预置音色，未合成"}, status_code=422)
        # Restore the consumed bounded body for the official request parser.
        request._body = bytes(raw)
        response = await call_next(request)
        if response.status_code == 200:
            response.headers["X-Ecom-Voice-Model"] = MODEL
            response.headers["X-Ecom-Voice-Revision"] = REVISION
        return response


def main():
    parser = argparse.ArgumentParser(description="独立 VoiceStudio 固定模型服务；不自动下载模型")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--port", type=int, default=3900)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not (args.backend / "main.py").is_file():
        parser.error("请提供官方 VoiceStudio backend 目录和有效的本机端口")
    hub = args.cache.resolve() / "models--mlx-community--Kokoro-82M-bf16"
    if (hub / "refs/main").read_text().strip() != REVISION:
        parser.error("模型 revision 未核对，请先下载指定版本")
    weights = hub / "snapshots" / REVISION / "kokoro-v1_0.safetensors"
    if (
        hashlib.file_digest(weights.open("rb"), "sha256").hexdigest()
        != "4e9ecdf03b8b6cf906070390237feda473dc13327cb8d56a43deaa374c02acd8"
    ):
        parser.error("模型权重校验失败")
    os.environ.update(
        {
            "OMNIVOICE_TTS_BACKEND": "mlx-audio",
            "OMNIVOICE_MLX_AUDIO_MODEL": "kokoro",
            "OMNIVOICE_CACHE_DIR": str(args.cache.resolve()),
            "OMNIVOICE_DATA_DIR": str(args.data.resolve()),
            "HF_HOME": str(args.cache.resolve()),
            "HF_HUB_CACHE": str(args.cache.resolve()),
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "OMNIVOICE_PRELOAD_CAPTURE_ASR": "0",
            "OMNIVOICE_PRELOAD_WATERMARK": "0",
            "OMNIVOICE_PRELOAD_TTS_ASR": "0",
        }
    )
    sys.path.insert(0, str(args.backend.resolve()))
    import uvicorn
    from main import app

    install(app)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
