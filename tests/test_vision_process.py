"""Private inference is local, lazy, cancellation-aware and owns only its group."""

import json
from pathlib import Path

import pytest

from ecom_video import vision_process as vp

MODEL = {"model": "fixture", "digest": "pinned"}


def test_private_environment_has_no_customer_credentials(monkeypatch):
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "secret-not-inherited")
    monkeypatch.setenv("ARK_API_KEY", "secret-not-inherited")
    env = vp.environment(43210)
    assert not any("KEY" in k or "TOKEN" in k for k in env)
    assert env["OLLAMA_HOST"] == "127.0.0.1:43210"
    assert env["OLLAMA_FLASH_ATTENTION"] == "true"
    assert env["LLAMA_ARG_CACHE_RAM"] == "0"
    assert env["OLLAMA_NO_CLOUD"] == "true" and env["OLLAMA_NUM_PARALLEL"] == "1"


def test_unused_scope_never_starts_a_process(monkeypatch):
    monkeypatch.setattr(vp.subprocess, "Popen", lambda *a, **kw: pytest.fail("must stay lazy"))
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)
    assert session.endpoint("/api/tags", None) == "http://127.0.0.1:11434"
    session.close()
    assert session.record["starts"] == 0
    json.dumps(session.record)


def test_explicit_shared_or_unverified_size_never_plans_private(monkeypatch):
    session = vp.Session(None)
    monkeypatch.setenv("ECOM_VISION_PROCESS", "shared")
    session.plan(MODEL, 3072, 8 * 1024**3)
    assert session.candidate is None
    monkeypatch.delenv("ECOM_VISION_PROCESS")
    session.plan(MODEL, 8192, 0)
    assert session.candidate is None


def test_only_chat_can_start_and_endpoint_is_fixed_loopback(monkeypatch):
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)
    starts = []

    def start():
        starts.append(1)
        session.url = "http://127.0.0.1:43210"

    monkeypatch.setattr(session, "start", start)
    assert session.endpoint("/api/show", {"model": "fixture"}) == "http://127.0.0.1:11434"
    assert session.endpoint("/api/chat", {"model": "fixture"}) == "http://127.0.0.1:43210"
    assert starts == [1]
    assert session.endpoint("/api/generate", {"model": "fixture", "keep_alive": 0}) == session.url


def test_start_failure_rechecks_cancellation_before_shared_fallback(monkeypatch):
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)

    def fail():
        raise OSError("private secret path must not be recorded")

    monkeypatch.setattr(session, "start", fail)
    assert session.endpoint("/api/chat", {"model": "fixture"}) == "http://127.0.0.1:11434"
    assert session.record["fallbacks"] == 1
    assert "secret path" not in json.dumps(session.record)
    monkeypatch.setattr(session, "check", lambda: (_ for _ in ()).throw(RuntimeError("cancelled")))
    with pytest.raises(RuntimeError, match="cancelled"):
        session.endpoint("/api/chat", {"model": "fixture"})


def test_close_terminates_only_owned_group_and_is_idempotent(monkeypatch):
    class Process:
        pid = 12345

        def wait(self, timeout):
            return 0

    session = vp.Session(None)
    session.process = Process()
    session.record["starts"] = 1
    groups = []
    monkeypatch.setattr(vp.os, "killpg", lambda pid, signal: groups.append(pid), raising=False)
    session.close()
    first = list(groups)
    session.close()
    assert groups == first and groups and all(pid == 12345 for pid in groups)
    assert session.record["stops"] == 1
    assert session.record["closed"]


def test_runtime_binary_change_does_not_receive_verified_profile(tmp_path, monkeypatch):
    binary = tmp_path / "ollama"
    runner = tmp_path / "llama-server"
    binary.write_bytes(b"changed")
    runner.write_bytes(b"changed")
    monkeypatch.setattr(vp, "BINARY", binary)
    assert vp.verified_binary() is None


def test_foreign_running_model_does_not_get_unloaded_or_spawn_private(monkeypatch):
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)
    monkeypatch.setattr(vp, "verified_binary", lambda: Path("/verified/ollama"))
    requests = []

    def read(url, path):
        requests.append((url, path))
        return {"models": [{"name": "another-user-model"}]}

    monkeypatch.setattr(vp, "read_local", read)
    monkeypatch.setattr(
        vp.subprocess, "Popen", lambda *a, **kw: pytest.fail("foreign model active")
    )
    assert session.endpoint("/api/chat", {"model": "fixture"}) == "http://127.0.0.1:11434"
    assert requests == [("http://127.0.0.1:11434", "/api/ps")]


def test_watchdog_terminates_owned_process_on_cancellation(monkeypatch):
    session = vp.Session(lambda: (_ for _ in ()).throw(RuntimeError("cancelled fixture")))

    class Process:
        pid = 12345

    session.process = Process()
    monkeypatch.setattr(session.stop, "wait", lambda timeout: False)
    groups = []
    monkeypatch.setattr(vp.os, "killpg", lambda pid, sig: groups.append(pid), raising=False)
    session.watch()
    assert isinstance(session.error, RuntimeError) and groups == [12345]
    with pytest.raises(RuntimeError, match="cancelled fixture"):
        session.check()


def test_different_model_cannot_reuse_verified_private_profile():
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)
    with pytest.raises(ValueError, match="模型发生变化"):
        session.endpoint("/api/chat", {"model": "other"})


def test_private_startup_after_spawn_failure_cleans_owned_group(monkeypatch):
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)

    class Process:
        pid = 12345

        def poll(self):
            return 1

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(vp, "verified_binary", lambda: Path("/verified/ollama"))
    monkeypatch.setattr(vp, "read_local", lambda *a: {"models": []})
    monkeypatch.setattr(vp.subprocess, "Popen", lambda *a, **kw: Process())
    groups = []
    monkeypatch.setattr(vp.os, "killpg", lambda pid, sig: groups.append(pid), raising=False)
    assert session.endpoint("/api/chat", {"model": "fixture"}) == vp.SHARED
    assert session.record["starts"] == session.record["stops"] == 1
    assert session.record["fallbacks"] == 1 and session.process is None
    assert groups and all(pid == 12345 for pid in groups)


def test_failed_start_stays_shared_for_remaining_generate_plans(monkeypatch):
    session = vp.Session(None)
    attempts = []

    def fail():
        attempts.append(1)
        raise OSError("unavailable")

    monkeypatch.setattr(session, "start", fail)
    for _ in range(3):
        session.plan(MODEL, 3072, 8 * 1024**3)
        assert session.endpoint("/api/chat", {"model": "fixture"}) == vp.SHARED
    assert attempts == [1] and session.record["fallbacks"] == 1


def test_cancelled_shared_scope_can_only_send_prompt_free_cleanup(monkeypatch):
    import httpx

    from ecom_video import vision_model

    session = vp.Session(lambda: (_ for _ in ()).throw(ValueError("cancelled fixture")))
    token = vp.CURRENT.set(session)
    client = httpx.Client
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"done_reason": "unload"})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(**kw, transport=httpx.MockTransport(transport))
    )
    try:
        vision_model.release_model("fixture")
        with pytest.raises(ValueError, match="cancelled fixture"):
            vision_model.request(
                "/api/generate", {"model": "fixture", "keep_alive": 0, "prompt": "not cleanup"}
            )
    finally:
        vp.CURRENT.reset(token)
    assert sent == [{"model": "fixture", "keep_alive": 0}]


def test_ineligible_context_clears_pending_profile():
    session = vp.Session(None)
    session.plan(MODEL, 3072, 8 * 1024**3)
    session.plan(MODEL, 8192, 0)
    assert session.candidate is None


def test_startup_cancel_is_preserved_even_if_its_cleanup_also_fails(monkeypatch):
    original = RuntimeError("cancelled fixture")
    checks = []

    def check():
        checks.append(1)
        if len(checks) > 1:
            raise original

    session = vp.Session(check)
    session.plan(MODEL, 3072, 8 * 1024**3)
    monkeypatch.setattr(session, "start", lambda: (_ for _ in ()).throw(original))
    monkeypatch.setattr(session, "close", lambda: (_ for _ in ()).throw(OSError("cleanup failed")))
    with pytest.raises(RuntimeError) as error:
        session.endpoint("/api/chat", {"model": "fixture"})
    assert error.value is original
    assert session.record["fallbacks"] == 0
