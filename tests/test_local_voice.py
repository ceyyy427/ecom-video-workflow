import io
import json
import wave

import httpx
import pytest
from test_customer import approve, client, project


def verified_contract():
    return {
        "version": 1,
        "engine": "mlx-audio",
        "model": "mlx-community/Kokoro-82M-bf16",
        "revision": "a71e4d38b236d968966a2002c4c895dbd12b1c3c",
        "voice": "zf_xiaobei",
    }


VOICE_HEADERS = {
    "content-type": "audio/wav",
    "X-Ecom-Voice-Model": "mlx-community/Kokoro-82M-bf16",
    "X-Ecom-Voice-Revision": "a71e4d38b236d968966a2002c4c895dbd12b1c3c",
}


def body(p, **extra):
    return {
        "revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "draft_id": p["product"]["current_draft_id"],
        "engine": "mlx-audio",
        "local_engine_confirmed": True,
        **extra,
    }


def audio():
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\0\0" * 12000)
    return out.getvalue()


def test_noncommercial_or_unknown_active_model_blocks_synthesis(tmp_path):
    c = client(tmp_path)
    p = approve(c, project(c))
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(
            200, json={"active": "omnivoice", "active_model": "k2-fsa/OmniVoice", "backends": []}
        )

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    r = c.post(f"/api/customer-projects/{p['id']}/voice/voicestudio", json=body(p))
    assert r.status_code == 503
    assert all(r.method == "GET" for r in requests)
    state = c.get("/api/voice/voicestudio/status").json()
    assert state["connected"] is True and state["ready"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost:3900",
        "http://127.0.0.1:0",
        "http://127.0.0.1:3900/path",
        "http://user@127.0.0.1:3900",
    ],
)
def test_endpoint_must_be_numeric_loopback(monkeypatch, url):
    from ecom_video.local_voice import endpoint

    monkeypatch.setenv("ECOM_VOICESTUDIO_URL", url)
    with pytest.raises(ValueError):
        endpoint()


def test_local_generation_uses_only_confirmed_text_and_reuses_preview(tmp_path):
    c = client(tmp_path)
    p = project(c)
    calls = []

    def send(request):
        if request.method == "GET":
            if request.url.path == "/ecom/voice-contract":
                return httpx.Response(200, json=verified_contract())
            return httpx.Response(
                200,
                json={
                    "active": "mlx-audio",
                    "active_model": "mlx-community/Kokoro-82M-bf16",
                    "backends": [{"id": "mlx-audio", "available": True}],
                },
            )
        calls.append(request)
        return httpx.Response(200, content=audio(), headers=VOICE_HEADERS)

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    route = f"/api/customer-projects/{p['id']}/voice/voicestudio"
    assert c.post(route, json={**body(p), "draft_id": "missing"}).status_code == 409
    assert not calls
    p = approve(c, p)
    assert c.post(route, json=body(p, local_engine_confirmed=False)).status_code == 422
    assert c.post(route, json=body(p, text="unconfirmed")).status_code == 422
    out = c.post(route, json=body(p))
    assert out.status_code == 201, out.text
    result = out.json()
    assert len(calls) == 1 and calls[0].url.host == "127.0.0.1"
    assert json.loads(calls[0].content)["response_format"] == "wav"
    assert json.loads(calls[0].content)["voice"] == "zf_xiaobei"
    assert calls[0].headers["X-Ecom-Expected-Model"] == "mlx-community/Kokoro-82M-bf16"
    take = result["voice_takes"][0]
    assert take["params"]["provider"] == "voicestudio"
    assert take["params"]["model_revision"] == verified_contract()["revision"]
    assert take["params"]["human_listening"] == "pending"
    assert not result["media"]
    assert c.post(route, json=body(p)).status_code == 201
    assert len(calls) == 1
    out = c.post(route, json=body(p, preview=False))
    assert out.status_code == 201, out.text
    assert len(calls) == 2
    result = out.json()
    assert result["media"][0]["role"] == "voice"
    assert result["media"][0]["metadata"]["voice_source"]["human_listening"] == "pending"
    assert c.post(route, json=body(result, preview=False)).status_code == 409


@pytest.mark.parametrize(
    "status,payload",
    [(302, b"redirect"), (200, b'{"error":"not audio"}'), (500, b"secret upstream trace")],
)
def test_errors_do_not_save_partial_audio_or_expose_provider_body(tmp_path, status, payload):
    c = client(tmp_path)
    p = approve(c, project(c))
    calls = []

    def send(request):
        if request.method == "GET":
            if request.url.path == "/ecom/voice-contract":
                return httpx.Response(200, json=verified_contract())
            return httpx.Response(
                200,
                json={
                    "active": "mlx-audio",
                    "active_model": "mlx-community/Kokoro-82M-bf16",
                    "backends": [{"id": "mlx-audio", "available": True}],
                },
            )
        calls.append(request)
        return httpx.Response(status, content=payload, headers={"location": "https://example.com"})

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    r = c.post(f"/api/customer-projects/{p['id']}/voice/voicestudio", json=body(p))
    assert r.status_code == 503 and "secret" not in r.text
    assert len(calls) == 1
    assert c.get(f"/api/customer-projects/{p['id']}").json()["voice_takes"] == []


def test_native_status_without_generation_time_model_binding_does_not_synthesize(tmp_path):
    c = client(tmp_path)
    p = approve(c, project(c))
    calls = []

    def send(request):
        calls.append(request)
        if request.url.path == "/engines/tts":
            return httpx.Response(
                200,
                json={
                    "active": "mlx-audio",
                    "active_model": verified_contract()["model"],
                    "backends": [{"id": "mlx-audio", "available": True}],
                },
            )
        return httpx.Response(404)

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    assert (
        c.post(f"/api/customer-projects/{p['id']}/voice/voicestudio", json=body(p)).status_code
        == 503
    )
    assert all(r.method == "GET" for r in calls)
    assert "模型" in c.get("/api/voice/voicestudio/status").json()["message"]


def test_status_stream_stops_at_limit_instead_of_consuming_all_bytes(tmp_path):
    class Oversized(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * 65537
            raise AssertionError("response must not be consumed beyond the limit")

    c = client(tmp_path)
    c.app.state.local_voice.transport = httpx.MockTransport(
        lambda req: httpx.Response(200, stream=Oversized())
    )
    assert c.get("/api/voice/voicestudio/status").json()["ready"] is False


def test_verified_status_does_not_import_the_entire_optional_engine_inventory(tmp_path):
    c = client(tmp_path)

    def send(request):
        assert request.url.path == "/ecom/voice-contract", (
            "unrelated engines must not delay Kokoro readiness"
        )
        return httpx.Response(200, json=verified_contract())

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    assert c.get("/api/voice/voicestudio/status").json()["ready"] is True


def test_mismatched_generation_receipt_is_not_saved(tmp_path):
    c = client(tmp_path)
    p = approve(c, project(c))

    def send(request):
        if request.method == "GET":
            if request.url.path == "/ecom/voice-contract":
                return httpx.Response(200, json=verified_contract())
            return httpx.Response(
                200,
                json={
                    "active": "mlx-audio",
                    "active_model": verified_contract()["model"],
                    "backends": [{"id": "mlx-audio", "available": True}],
                },
            )
        return httpx.Response(
            200, content=audio(), headers={**VOICE_HEADERS, "X-Ecom-Voice-Model": "other"}
        )

    c.app.state.local_voice.transport = httpx.MockTransport(send)
    assert (
        c.post(f"/api/customer-projects/{p['id']}/voice/voicestudio", json=body(p)).status_code
        == 503
    )
    assert c.get(f"/api/customer-projects/{p['id']}").json()["voice_takes"] == []
