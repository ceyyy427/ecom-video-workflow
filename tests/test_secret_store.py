import os
import platform

import pytest

from ecom_video.platforms.secret_store import SecretStore


@pytest.mark.skipif(
    platform.system() != "Darwin" or os.getenv("ECOM_TEST_KEYCHAIN") != "1",
    reason="explicit opt-in for disposable OS keychain integration",
)
def test_macos_keychain_roundtrip_and_cleanup(tmp_path):
    store = SecretStore(tmp_path)
    try:
        store.write("synthetic-check", {"fixture": "public-noncredential-test"})
        assert store.read("synthetic-check") == {"fixture": "public-noncredential-test"}
        store.write("synthetic-check", {"fixture": "public-noncredential-updated"})
        assert store.read("synthetic-check") == {"fixture": "public-noncredential-updated"}
        assert SecretStore(tmp_path / "other").read("synthetic-check") == {}
    finally:
        store.delete("synthetic-check")
    assert store.read("synthetic-check") == {}


def test_linux_secrets_use_stdin_and_namespace(tmp_path, monkeypatch):
    import json
    import subprocess

    from ecom_video.platforms import secret_store

    monkeypatch.setattr(secret_store.platform, "system", lambda: "Linux")
    monkeypatch.setattr(secret_store.shutil, "which", lambda name: "/usr/bin/secret-tool")
    memory = {}
    calls = []

    def run(args, input, **kwargs):
        calls.append((args, input))
        key = args[-1]
        if args[1] == "store":
            memory[key] = input.strip()
        elif args[1] == "clear":
            memory.pop(key, None)
        return subprocess.CompletedProcess(
            args, 0, memory.get(key, b"") if args[1] == "lookup" else b"", b""
        )

    monkeypatch.setattr(secret_store.subprocess, "run", run)
    store = SecretStore(tmp_path)
    value = {"secret": "fixture-not-a-real-credential"}
    store.write("app-test", value)
    assert store.read("app-test") == value
    assert SecretStore(tmp_path / "other").read("app-test") == {}
    assert all(value["secret"] not in str(args) for args, _ in calls)
    assert json.loads(calls[0][1]) == value
    store.delete("app-test")
    assert store.read("app-test") == {}
