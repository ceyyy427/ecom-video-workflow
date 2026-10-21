"""Execution placement may change speed, never the visual checks or input budget."""

from ecom_video import vision_model

MODEL = {
    "model": "ecom-qwen3vl:4b-q4km",
    "digest": "744629259dd19027ab5b5c35c8238e18f32c373ead897e95da0f36d93628ca46",
    "provider": "ollama_loopback",
}


def test_verified_metal_model_stays_resident_without_smaller_inputs(monkeypatch, tmp_path):
    import os
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    seen = []

    def request(path, payload=None, **kwargs):
        if path == "/api/generate":
            return {"done_reason": "unload"}
        seen.append(payload)
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"unchanged-image")
    assert vision_model.generate(
        "unchanged prompt", {"type": "object"}, [image], MODEL, context_size=3072, max_tokens=512
    ) == {"ok": True}
    options = seen[0]["options"]
    assert options["num_gpu"] == 99
    assert options["num_ctx"] == 3072 and options["num_predict"] == 512
    assert seen[0]["messages"][-1] == {
        "role": "user",
        "content": "unchanged prompt",
        "images": ["dW5jaGFuZ2VkLWltYWdl"],
    }
    assert seen[0]["format"] == {"type": "object"}


def test_unverified_hardware_or_model_and_explicit_rollback_use_original_placement(monkeypatch):
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert "num_gpu" not in vision_model.execution_options(MODEL, 3072)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert "num_gpu" not in vision_model.execution_options({**MODEL, "digest": "unknown"}, 3072)
    monkeypatch.setenv("ECOM_VISION_ACCELERATION", "off")
    assert "num_gpu" not in vision_model.execution_options(MODEL, 3072)


def test_resource_failure_retries_once_with_original_inputs_and_disables_acceleration_in_scope(
    monkeypatch,
):
    import os
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    seen = []
    operations = []

    def request(path, payload=None, **kw):
        operations.append(path)
        if path == "/api/generate":
            return {"done_reason": "unload"}
        if path == "/api/ps":
            return {"models": []}
        seen.append(payload)
        if len(seen) == 1:
            raise vision_model.LocalVisionError("本机内存不足", resource_exhausted=True)
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    with vision_model.execution_scope() as runtime:
        assert vision_model.generate("same", {}, model=MODEL, context_size=3072) == {"ok": True}
        assert vision_model.generate("next", {}, model=MODEL, context_size=3072) == {"ok": True}
    assert len(seen) == 3
    assert seen[0]["options"]["num_gpu"] == 99
    assert all("num_gpu" not in p["options"] for p in seen[1:])
    assert {k: v for k, v in seen[0].items() if k != "options"} == {
        k: v for k, v in seen[1].items() if k != "options"
    }
    assert {k: v for k, v in seen[0]["options"].items() if k != "num_gpu"} == seen[1]["options"]
    assert runtime["resource_fallbacks"] == 1
    assert operations[:4] == ["/api/chat", "/api/generate", "/api/ps", "/api/chat"]
    assert operations[-1] == "/api/generate"  # Retry state is released too.


def test_invalid_json_never_triggers_an_accelerated_retry(monkeypatch):
    import pytest

    seen = []

    def request(*a, **k):
        seen.append(1)
        return {"message": {"content": "not JSON"}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    with pytest.raises(ValueError, match="有效结构化"):
        vision_model.generate("same", {}, model=MODEL, context_size=3072)
    assert len(seen) == 1


def test_oom_with_unconfirmed_runner_removal_keeps_original_error_and_does_not_retry(monkeypatch):
    import pytest

    monkeypatch.setattr(vision_model, "metal_memory", lambda *a: 8 * 1024**3)
    ticks = iter((0, 6))
    monkeypatch.setattr(vision_model.time, "monotonic", lambda: next(ticks))
    calls = []
    original = vision_model.LocalVisionError("original OOM", resource_exhausted=True)

    def request(path, payload=None, **kw):
        calls.append(path)
        if path == "/api/generate":
            return {"done_reason": "unload"}
        if path == "/api/ps":
            return {"models": [{"name": MODEL["model"]}]}
        raise original

    monkeypatch.setattr(vision_model, "request", request)
    with (
        vision_model.execution_scope() as runtime,
        pytest.raises(vision_model.LocalVisionError) as e,
    ):
        vision_model.generate("same", {}, model=MODEL, context_size=3072)
    assert e.value is original
    assert calls.count("/api/chat") == 1 and runtime["resource_fallbacks"] == 0
    assert runtime["release_errors"] == 1


def test_backend_oom_is_classified_without_exposing_raw_backend_paths(monkeypatch):
    import httpx
    import pytest

    client = httpx.Client

    def local_client(**kwargs):
        return client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    500, json={"error": "Metal out of memory /private/customer-data"}
                )
            ),
        )

    monkeypatch.setattr(httpx, "Client", local_client)
    with pytest.raises(vision_model.LocalVisionError) as error:
        vision_model.request("/api/chat", {"model": "fixture"})
    assert error.value.resource_exhausted
    assert "/private/" not in str(error.value)


def test_oom_retry_cannot_bypass_agent_budget(tmp_path, monkeypatch):
    import os
    import platform

    import pytest
    from test_agent_runtime import policy, setup_run, start

    from ecom_video.agent_contracts import Problem
    from ecom_video.agent_guard import scope

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch, limits=policy(max_model_calls=1))
    start(proposal, runtime)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    requests = []

    def oom(*a, **k):
        if a[0] == "/api/generate":
            return {"done_reason": "unload"}
        if a[0] == "/api/ps":
            return {"models": []}
        requests.append(1)
        raise vision_model.LocalVisionError("fixture OOM", resource_exhausted=True)

    monkeypatch.setattr(vision_model, "request", oom)
    with (
        scope(runtime.store, proposal["run_id"]),
        vision_model.execution_scope(),
        pytest.raises(Problem, match="BUDGET_EXCEEDED"),
    ):
        vision_model.generate("same", {}, model=MODEL, context_size=3072)
    assert requests == [1]
    assert runtime.get(proposal["run_id"])["usage"]["model_calls"] == 1


def test_small_metal_session_releases_native_host_cache_every_eight_requests(monkeypatch):
    import os
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    seen = []

    def request(path, payload=None, **kw):
        if path == "/api/generate":
            return {"done_reason": "unload"}
        seen.append(payload)
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    with vision_model.execution_scope() as runtime:
        for _ in range(17):
            assert vision_model.generate(
                "unchanged", {}, model=MODEL, context_size=3072, max_tokens=512
            ) == {"ok": True}
    assert [p["keep_alive"] for p in seen] == ["2m"] * 7 + [0] + ["2m"] * 7 + [0, "2m"]
    assert all(p["options"]["num_ctx"] == 3072 and p["options"]["num_predict"] == 512 for p in seen)
    assert runtime["model_releases"] == 2


def test_short_sessions_release_their_native_cache_without_new_inference(monkeypatch):
    import os
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    operations = []

    def request(path, payload=None, **kw):
        operations.append((path, payload))
        if path == "/api/generate":
            assert payload == {"model": MODEL["model"], "keep_alive": 0}
            return {"done": True, "done_reason": "unload"}
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    for _ in range(3):
        with vision_model.execution_scope() as runtime:
            vision_model.generate("short", {}, model=MODEL, context_size=3072)
        assert runtime["scope_releases"] == 1
    assert [path for path, _ in operations] == ["/api/chat", "/api/generate"] * 3


def test_cleanup_failure_preserves_original_error_and_agent_context(monkeypatch):
    import os
    import platform

    import pytest

    from ecom_video.agent_guard import SCOPE

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)

    def request(path, payload=None, **kw):
        if path == "/api/generate":
            assert SCOPE.get() is None
            raise ValueError("cleanup timed out")
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    marker = ("already cancelled fixture scope", None, None)
    token = None
    try:
        with (
            pytest.raises(ValueError, match="original frame error"),
            vision_model.execution_scope() as runtime,
        ):
            vision_model.generate("short", {}, model=MODEL, context_size=3072)
            token = SCOPE.set(marker)
            raise ValueError("original frame error")
        assert SCOPE.get() == marker
        assert runtime["release_errors"] == 1
        assert vision_model.EXECUTION.get() is None
    finally:
        if token is not None:
            SCOPE.reset(token)


def test_complete_eight_request_epoch_does_not_add_a_second_release_on_exit(monkeypatch):
    import os
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        os, "sysconf", lambda k: {"SC_PHYS_PAGES": 2097152, "SC_PAGE_SIZE": 4096}[k]
    )
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    operations = []

    def request(path, payload=None, **kw):
        operations.append(path)
        return {"message": {"content": '{"ok":true}'}, "done_reason": "stop"}

    monkeypatch.setattr(vision_model, "request", request)
    with vision_model.execution_scope() as runtime:
        for _ in range(8):
            vision_model.generate("unchanged", {}, model=MODEL, context_size=3072)
    assert runtime["scope_releases"] == runtime["release_errors"] == 0
    assert runtime["model_releases"] == 1
    assert operations == ["/api/chat"] * 8
