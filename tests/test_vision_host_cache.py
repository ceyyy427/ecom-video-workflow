"""Experimental native prompt cache stays bounded and opt-in until measured."""

from pathlib import Path

import pytest

from ecom_video import vision_process as vp


@pytest.mark.parametrize(
    "value,expected", [(None, 0), ("256", 256), ("8192", 0), ("-1", 0), ("url", 0)]
)
def test_host_cache_is_fixed_small_opt_in(monkeypatch, value, expected):
    monkeypatch.delenv("ECOM_VISION_HOST_CACHE", raising=False)
    if value is not None:
        monkeypatch.setenv("ECOM_VISION_HOST_CACHE", value)
    assert vp.host_cache_mib() == expected
    env = vp.environment(43210)
    assert env["LLAMA_ARG_CACHE_RAM"] == str(expected)
    assert env["OLLAMA_HOST"] == "127.0.0.1:43210"
    assert env["OLLAMA_NO_CLOUD"] == "true"


def test_host_cache_does_not_override_unverified_profile(monkeypatch):
    monkeypatch.setenv("ECOM_VISION_HOST_CACHE", "256")
    monkeypatch.setenv("ECOM_VISION_PROCESS", "shared")
    session = vp.Session(None)
    session.plan({"model": "fixture", "digest": "unknown"}, 3072, 8 * 1024**3)
    assert session.candidate is None
    assert session.record["starts"] == 0


def test_receipt_records_launched_cache_not_later_environment(monkeypatch):
    monkeypatch.setenv("ECOM_VISION_HOST_CACHE", "256")
    session = vp.Session(None)
    model = {"model": "fixture", "digest": "pinned"}
    session.plan(model, 3072, 8 * 1024**3)
    monkeypatch.setattr(vp, "verified_binary", lambda: Path("/verified/ollama"))
    sent = []

    class Process:
        pid = 12345

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    def launch(*args, **kwargs):
        sent.append(kwargs["env"])
        monkeypatch.setenv("ECOM_VISION_HOST_CACHE", "-1")
        return Process()

    def read(url, path):
        if path == "/api/ps":
            return {"models": []}
        if path == "/api/version":
            return {"version": "0.35.0"}
        return {"models": [{"name": "fixture", "digest": "pinned"}]}

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout):
            pass

    monkeypatch.setattr(vp.subprocess, "Popen", launch)
    monkeypatch.setattr(vp, "read_local", read)
    monkeypatch.setattr(vp.threading, "Thread", Thread)
    monkeypatch.setattr(vp.os, "killpg", lambda *args: None)
    session.start()
    assert sent[0]["LLAMA_ARG_CACHE_RAM"] == "256"
    assert session.record["host_cache_mib"] == 256
    session.close()
    assert session.record["closed"] and session.record["stops"] == 1
