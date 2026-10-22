import pytest


def test_actual_cached_model_is_checked_instead_of_preferences():
    from ecom_video.voicestudio_bridge import require_backend

    class Backend:
        id = "mlx-audio"

        def model_identity(self):
            return "mlx-community/csm-1b-8bit"

    with pytest.raises(ValueError, match="模型"):
        require_backend(Backend())
    Backend.model_identity = lambda self: "mlx-community/Kokoro-82M-bf16"
    assert require_backend(Backend()).id == "mlx-audio"


def test_voice_tensors_use_the_verified_offline_model_snapshot():
    from types import SimpleNamespace

    from ecom_video.voicestudio_bridge import MODEL, KokoroBackend

    pipeline = SimpleNamespace(repo_id="prince-canuma/Kokoro-82M")
    model = SimpleNamespace(repo_id=None, _pipelines={"z": pipeline})
    backend = SimpleNamespace(
        id="mlx-audio",
        model_identity=lambda: MODEL,
        _ensure_loaded=lambda: None,
        _model=model,
        generate=lambda text, **kw: (text, kw),
    )
    out = KokoroBackend(backend).generate("你好", voice="zf_xiaobei")
    assert model.repo_id == pipeline.repo_id == MODEL
    assert out == ("你好", {"voice": "zf_xiaobei"})


def test_generation_rechecks_actual_model_and_does_not_accept_clone_arguments():
    from types import SimpleNamespace

    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.testclient import TestClient

    from ecom_video.voicestudio_bridge import MODEL, REVISION, VOICE, install

    backend = SimpleNamespace(id="mlx-audio", model_identity=lambda: MODEL)
    compat = SimpleNamespace(_resolve_engine=lambda _: backend, OpenAIError=HTTPException)
    app, calls = FastAPI(), []

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        body = await request.json()
        compat._resolve_engine(body["model"])
        calls.append(body)
        return Response(b"fixture", media_type="audio/wav")

    install(app, compat)
    c = TestClient(app, base_url="http://127.0.0.1:3900")
    assert c.get("/ecom/voice-contract").json()["model"] == MODEL
    payload = {
        "model": "mlx-audio",
        "voice": VOICE,
        "language": "zh",
        "input": "你好",
        "response_format": "wav",
        "speed": 1,
    }
    headers = {"X-Ecom-Expected-Model": MODEL, "X-Ecom-Expected-Revision": REVISION}
    assert c.post("/v1/audio/speech", json=payload).status_code == 409
    backend.model_identity = lambda: "other cached model"
    assert c.post("/v1/audio/speech", json=payload, headers=headers).status_code == 503
    assert not calls
    backend.model_identity = lambda: MODEL
    assert (
        c.post("/v1/audio/speech", json={**payload, "ref_audio": "x"}, headers=headers).status_code
        == 422
    )
    response = c.post("/v1/audio/speech", json=payload, headers=headers)
    assert response.status_code == 200 and response.headers["X-Ecom-Voice-Model"] == MODEL
    assert len(calls) == 1 and calls[0]["input"] == "你好"
    assert c.post("/engines/select", json={}).status_code == 404


def test_dedicated_service_rejects_websocket_and_browser_origin_bypasses():
    from types import SimpleNamespace

    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from ecom_video.voicestudio_bridge import install

    app = FastAPI()

    @app.websocket("/ws/tts")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("must never reach an alternative synthesis path")

    @app.get("/health")
    def health():
        return {"ok": True}

    install(app, SimpleNamespace(_resolve_engine=lambda _: None))
    c = TestClient(app, base_url="http://127.0.0.1:3900")
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws/tts"):
        pass
    assert c.get("/health", headers={"Origin": "https://example.com"}).status_code == 403
    assert c.get("/health", headers={"Host": "example.com"}).status_code == 403
