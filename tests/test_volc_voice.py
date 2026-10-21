"""External HTTP is simulated; approval, parsing, probing and persistence are real."""

import base64
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from test_customer import approve, client, project


@pytest.fixture(autouse=True)
def isolate_voice_environment(monkeypatch):
    monkeypatch.delenv("DOUBAO_TTS_API_KEY", raising=False)


def test_voice_environment_is_accepted_without_exposure(tmp_path, monkeypatch):
    from ecom_video.volc_voice import read_config

    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "unit-tts-environment-secret")
    assert read_config()[0] == "unit-tts-environment-secret"
    c = client(tmp_path / "data")
    r = c.get("/api/voice/volcengine/status")
    assert r.json()["configured"] is True
    assert "unit-tts-environment-secret" not in r.text
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "invalid\nheader")
    assert c.get("/api/voice/volcengine/status").json()["configured"] is False


def body(p):
    return {
        "revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "draft_id": p["product"]["current_draft_id"],
        "external_consent": True,
    }


def configured(tmp_path, monkeypatch):
    path = tmp_path / "voice-config.json"
    path.write_text(
        json.dumps({"api_key": "unit-test-private-key", "speaker": "zh_female_vv_uranus_bigtts"})
    )
    path.chmod(0o600)
    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(path))
    c = client(tmp_path / "data")
    return c, path


def sse(audio=b"audio", complete=True):
    frames = (
        "event: 352\ndata: "
        + json.dumps({"code": 0, "data": base64.b64encode(audio).decode()})
        + "\n\n"
    )
    if complete:
        frames += 'event: 152\ndata: {"code":20000000,"data":null}\n\n'
    return frames.encode()


def test_status_hides_credentials_and_rejects_unsafe_config(tmp_path, monkeypatch):
    c, path = configured(tmp_path, monkeypatch)
    r = c.get("/api/voice/volcengine/status")
    assert r.status_code == 200
    assert r.json()["configured"] is True
    assert "private-key" not in r.text and str(path) not in r.text
    path.chmod(0o644)
    assert c.get("/api/voice/volcengine/status").json()["configured"] is False


def test_requires_consent_and_confirmed_current_script_before_network(tmp_path, monkeypatch):
    c, _ = configured(tmp_path, monkeypatch)
    p = project(c)
    endpoint = f"/api/customer-projects/{p['id']}/voice/volcengine"
    assert c.post(endpoint, json={**body(p), "draft_id": "missing"}).status_code == 409
    p = approve(c, p)
    assert c.post(endpoint, json={**body(p), "external_consent": False}).status_code == 422
    assert c.post(endpoint, json={**body(p), "product_revision": 0}).status_code == 409
    assert c.post(endpoint, json={**body(p), "text": "unapproved"}).status_code == 422


@pytest.fixture
def mp3(tmp_path):
    path = tmp_path / "fixture.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-ar",
            "24000",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def test_completed_audio_added_once_and_only_approved_text_sent(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    seen = []

    def send(request):
        seen.append(request)
        return httpx.Response(200, content=sse(mp3), headers={"content-type": "text/event-stream"})

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    endpoint = f"/api/customer-projects/{p['id']}/voice/volcengine"
    r = c.post(endpoint, json=body(p))
    assert r.status_code == 201, r.text
    result = r.json()
    audio = result["media"][0]
    assert audio["role"] == "voice" and audio["metadata"]["duration"] > 0
    assert audio["metadata"]["voice_source"]["draft_id"] == p["product"]["current_draft_id"]
    assert c.get(f"/api/customer-projects/{p['id']}/assets/{audio['id']}").content == mp3
    assert len(seen) == 1
    assert str(seen[0].url) == "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
    assert seen[0].headers["X-Api-Key"] == "unit-test-private-key"
    approved = p["product"]["script_drafts"][-1]["payload"]
    assert json.loads(seen[0].content)["req_params"]["text"] == "\n".join(
        s["text"] for s in approved
    )
    assert c.post(endpoint, json=body(result)).status_code == 409
    assert len(seen) == 1


@pytest.mark.parametrize(
    "response",
    [
        sse(complete=False),
        b"data: {bad}\n\n",
        b'data: {"code":45000000,"message":"SECRET vendor raw"}\n\n',
        b'data: {"code":0,"data":"%%%"}\n\ndata: {"code":20000000}\n\n',
        b'data: {"code":20000000,"data":null}\n\n',
    ],
)
def test_bad_or_incomplete_stream_never_creates_asset_and_masks_error(
    tmp_path, monkeypatch, response
):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, content=response)

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    r = c.post(f"/api/customer-projects/{p['id']}/voice/volcengine", json=body(p))
    assert r.status_code == 502
    assert "SECRET" not in r.text and "unit-test" not in r.text
    assert len(calls) == 1
    assert c.get(f"/api/customer-projects/{p['id']}").json()["media"] == []
    assert not list((tmp_path / "data").glob("customers/*/media/*.mp3"))


def test_script_change_during_request_discards_audio(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))

    def send(request):
        with c.app.state.store.transaction() as conn:
            conn.execute("UPDATE products SET revision=revision+1 WHERE id=?", (p["id"],))
        return httpx.Response(200, content=sse(mp3))

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    r = c.post(f"/api/customer-projects/{p['id']}/voice/volcengine", json=body(p))
    assert r.status_code == 409
    assert c.get(f"/api/customer-projects/{p['id']}").json()["media"] == []
    assert not list((tmp_path / "data").glob("customers/*/media/*.mp3"))


def test_concurrent_generation_is_rejected_without_second_charge(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    entered, release = Event(), Event()

    def send(request):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, content=sse(mp3))

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    endpoint = f"/api/customer-projects/{p['id']}/voice/volcengine"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(c.post, endpoint, json=body(p))
        try:
            assert entered.wait(5)
            assert c.post(endpoint, json=body(p)).status_code == 409
        finally:
            release.set()
        assert first.result().status_code == 201


def test_oversized_and_failed_http_requests_are_single_masked_failures(tmp_path, monkeypatch):
    from ecom_video.volc_voice import MAX_RESPONSE

    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    count = []

    def send(request):
        count.append(1)
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE + 1))

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    endpoint = f"/api/customer-projects/{p['id']}/voice/volcengine"
    assert c.post(endpoint, json=body(p)).status_code == 502
    assert len(count) == 1

    def denied(request):
        count.append(1)
        return httpx.Response(401, json={"error": "SECRET raw vendor"})

    c.app.state.volc_voice.transport = httpx.MockTransport(denied)
    result = c.post(endpoint, json=body(p))
    assert result.status_code == 502 and "SECRET" not in result.text
    assert len(count) == 2


def test_setup_refuses_overwrite_and_stores_private_config(tmp_path, monkeypatch):
    from scripts.volc_voice_setup import save_config

    path = tmp_path / "config" / "voice.json"
    save_config(path, "local-fixture-secret", "zh_female_vv_uranus_bigtts")
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(path))
    c = client(tmp_path / "data")
    assert c.get("/api/voice/volcengine/status").json()["configured"] is True
    with pytest.raises(FileExistsError):
        save_config(path, "another-fixture-secret", "zh_female_vv_uranus_bigtts")
    assert json.loads(path.read_text())["api_key"] == "local-fixture-secret"


def test_missing_config_and_cross_origin_request_cannot_send(tmp_path, monkeypatch):
    c, path = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    calls = []
    c.app.state.volc_voice.transport = httpx.MockTransport(lambda r: calls.append(r))
    endpoint = f"/api/customer-projects/{p['id']}/voice/volcengine"
    assert (
        c.post(endpoint, json=body(p), headers={"origin": "https://other.invalid"}).status_code
        == 403
    )
    path.unlink()
    assert c.post(endpoint, json=body(p)).status_code == 503
    assert calls == []


def test_config_symlink_is_not_accepted(tmp_path, monkeypatch):
    c, path = configured(tmp_path, monkeypatch)
    actual = path.with_name("private.json")
    path.rename(actual)
    path.symlink_to(actual)
    assert c.get("/api/voice/volcengine/status").json()["configured"] is False


def test_audio_probe_failure_is_masked_and_file_removed(tmp_path, monkeypatch):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=sse(b"not an MP3"))
    )
    result = c.post(f"/api/customer-projects/{p['id']}/voice/volcengine", json=body(p))
    assert result.status_code == 502
    assert c.get(f"/api/customer-projects/{p['id']}").json()["media"] == []
    assert not list((tmp_path / "data").glob("customers/*/media/*.mp3"))


def test_ark_key_is_reported_as_text_only_not_a_voice_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("ARK_API_KEY", "private-ark-test-key")
    c = client(tmp_path / "data")
    r = c.get("/api/voice/volcengine/status")
    assert r.json()["configured"] is False
    assert r.json()["ark_key_detected"] is True
    assert "方舟" in r.json()["message"] and "语音" in r.json()["message"]
    assert "private-ark-test-key" not in r.text


@pytest.mark.parametrize("http_status,sse_event", [(200, True), (403, False)])
def test_resource_denial_has_actionable_safe_error_without_audio_or_retry(
    tmp_path, monkeypatch, http_status, sse_event
):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, project(c))
    raw = {
        "code": 45000030,
        "message": "[resource_id=volc.seedtts.default] requested resource not granted SECRET raw vendor",
    }
    seen = []

    def send(request):
        seen.append(request)
        if sse_event:
            return httpx.Response(
                http_status, content=("event: 153\ndata: " + json.dumps(raw) + "\n\n").encode()
            )
        return httpx.Response(http_status, json=raw)

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    r = c.post(f"/api/customer-projects/{p['id']}/voice/volcengine", json=body(p))
    assert r.status_code == 502
    assert r.headers.get("X-Voice-Error-Code") == "resource_not_granted"
    assert "语音合成2.0字符版" in r.json()["detail"]
    assert "同一项目" in r.json()["detail"]
    assert "SECRET" not in r.text and "unit-test" not in r.text
    assert len(seen) == 1
    assert seen[0].headers["X-Api-Resource-Id"] == "seed-tts-2.0"
    assert c.get(f"/api/customer-projects/{p['id']}").json()["media"] == []


def test_generic_provider_error_is_not_misreported_as_resource_denial():
    from ecom_video.volc_voice import VoiceError, parse_sse

    raw = b'event: 153\ndata: {"code":45000030,"message":"SECRET unknown authentication issue"}\n\n'
    with pytest.raises(VoiceError) as exc:
        parse_sse(raw)
    assert exc.value.code == "provider_error"
    assert "SECRET" not in str(exc.value)


def test_check_is_local_by_default_and_explicit_probe_does_not_write_business_data(
    tmp_path, monkeypatch, mp3, capsys
):
    from scripts.volc_voice_check import check, main

    configured(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, content=sse(mp3))

    transport = httpx.MockTransport(send)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    local = check(transport=transport)
    assert local["live_verified"] is False and calls == []
    result = check(probe=True, transport=transport)
    assert result["live_verified"] is True and result["duration"] > 0
    assert result["review_state"] == "needs_listening"
    assert (
        len(calls) == 1
        and json.loads(calls[0].content)["req_params"]["text"] == "你好，这是一条配音授权测试。"
    )
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before
    assert main([]) == 0
    assert "unit-test-private-key" not in capsys.readouterr().out


def test_failed_check_reports_safe_reason_and_never_succeeds_on_bad_audio(tmp_path, monkeypatch):
    from scripts.volc_voice_check import check

    configured(tmp_path, monkeypatch)
    denied = httpx.MockTransport(lambda r: httpx.Response(401, json={"secret": "RAW"}))
    result = check(probe=True, transport=denied)
    assert result["live_verified"] is False and result["error_code"] == "credentials_rejected"
    assert "RAW" not in json.dumps(result)
    corrupt = httpx.MockTransport(lambda r: httpx.Response(200, content=sse(b"bad audio")))
    result = check(probe=True, transport=corrupt)
    assert result["live_verified"] is False and result["error_code"] == "invalid_audio"


def test_slow_error_stream_cannot_hide_behind_chunk_aggregation(monkeypatch):
    from ecom_video import volc_voice

    elapsed = [0.0]
    received = []

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(1024):
                elapsed[0] += 9
                received.append(1)
                yield b"x"

    monkeypatch.setattr(volc_voice.time, "monotonic", lambda: elapsed[0])
    transport = httpx.MockTransport(lambda r: httpx.Response(403, stream=Trickle()))
    with pytest.raises(volc_voice.VoiceError) as exc:
        volc_voice.synthesize("test", volc_voice.DEFAULT_SPEAKER, "unit-key", transport)
    assert elapsed[0] <= volc_voice.MAX_SECONDS + 10
    assert len(received) <= 12
    assert exc.value.code == "access_denied"


@pytest.mark.parametrize("status,code", [(403, "access_denied"), (429, "rate_limited")])
def test_http_failure_classification_keeps_unknown_cause_and_request_private(status, code):
    from ecom_video.volc_voice import DEFAULT_SPEAKER, VoiceError, synthesize

    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(status, json={"message": "SECRET unknown raw vendor"})

    with pytest.raises(VoiceError) as exc:
        synthesize("test", DEFAULT_SPEAKER, "SECRET unit-key", httpx.MockTransport(send))
    assert exc.value.code == code and exc.value.http_status == status
    assert "SECRET" not in json.dumps(exc.value.details())
    assert len(requests) == 1


@pytest.mark.parametrize("size,code", [(8192, "resource_not_granted"), (8193, "access_denied")])
def test_bounded_error_body_limit(size, code):
    from ecom_video.volc_voice import DEFAULT_SPEAKER, VoiceError, synthesize

    raw = json.dumps({"message": "requested resource not granted SECRET raw"}).encode()
    content = raw + b" " * (size - len(raw))
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(403, content=content)

    with pytest.raises(VoiceError) as exc:
        synthesize("test", DEFAULT_SPEAKER, "unit-key", httpx.MockTransport(send))
    assert exc.value.code == code
    assert "SECRET" not in str(exc.value) and len(calls) == 1


def test_network_timeout_is_safe_and_never_retried():
    from ecom_video.volc_voice import DEFAULT_SPEAKER, VoiceError, synthesize

    calls = []

    def send(request):
        calls.append(request)
        raise httpx.ReadTimeout("SECRET raw request", request=request)

    with pytest.raises(VoiceError) as exc:
        synthesize("test", DEFAULT_SPEAKER, "unit-key", httpx.MockTransport(send))
    assert exc.value.code == "network_error"
    assert "SECRET" not in str(exc.value) and len(calls) == 1


def test_voice_direction_is_separate_from_spoken_copy_and_invalid_controls_do_not_send():
    from ecom_video.volc_voice import DEFAULT_SPEAKER, synthesize

    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, content=sse())

    transport = httpx.MockTransport(send)
    assert (
        synthesize(
            "确认文稿",
            DEFAULT_SPEAKER,
            "unit-key",
            transport,
            direction="自然轻声聊天，不要播音腔",
            speech_rate=-5,
        )
        == b"audio"
    )
    payload = json.loads(calls[0].content)["req_params"]
    assert payload["text"] == "确认文稿"
    assert json.loads(payload["additions"])["context_texts"] == ["自然轻声聊天，不要播音腔"]
    assert payload["audio_params"]["speech_rate"] == -5
    for params in [
        {"speech_rate": True},
        {"speech_rate": 21},
        {"direction": "x" * 301},
        {"direction": " " * 301 + "x"},
    ]:
        with pytest.raises(ValueError):
            synthesize("确认文稿", DEFAULT_SPEAKER, "unit-key", transport, **params)
    assert len(calls) == 1
