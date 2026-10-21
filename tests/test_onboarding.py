import json
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecom_video.api import create_app


@pytest.fixture
def setup_client(tmp_path, monkeypatch):
    monkeypatch.delenv("DOUBAO_TTS_API_KEY", raising=False)
    monkeypatch.delenv("ECOM_VISION_MODEL", raising=False)
    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(tmp_path / "private/voice.json"))
    from ecom_video import vision_model

    monkeypatch.setattr(vision_model, "CONFIG", tmp_path / "models/vision.json")
    with TestClient(create_app(tmp_path / "data"), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        yield c


def test_setup_page_and_voice_save_dont_echo_secret(setup_client, tmp_path):
    c = setup_client
    assert c.get("/setup").status_code == 200
    result = c.post("/api/setup/voice", json={"api_key": "fixture-only-secret"})
    assert result.status_code == 200, result.text
    assert "fixture-only-secret" not in result.text
    path = tmp_path / "private/voice.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["api_key"] == "fixture-only-secret"
    r = c.post("/api/setup/voice", json={"api_key": "another-fixture"})
    assert r.status_code == 409
    assert "fixture-only-secret" in path.read_text()
    assert (
        c.post("/api/setup/voice", json={"api_key": "new-fixture", "replace": True}).status_code
        == 200
    )
    assert "new-fixture" in path.read_text()
    assert "new-fixture" not in c.get("/api/setup/status").text


def test_secret_validation_and_origin_never_echo_input(setup_client, tmp_path):
    c = setup_client
    for body in ({"api_key": "sensitive secret"}, {"api_key": "sensitive-secret", "typo": 1}):
        r = c.post("/api/setup/voice", json=body)
        assert r.status_code == 422
        assert "sensitive" not in r.text
    c.headers.pop("X-Workflow-Token")
    assert c.post("/api/setup/voice", json={"api_key": "fixture"}).status_code == 403
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    assert (
        c.post(
            "/api/setup/voice", json={"api_key": "fixture"}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert not (tmp_path / "private/voice.json").exists()


def test_environment_key_cannot_be_silently_overridden(setup_client, tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "environment-fixture")
    result = setup_client.post(
        "/api/setup/voice", json={"api_key": "file-fixture", "replace": True}
    )
    assert result.status_code == 409
    assert "environment-fixture" not in result.text
    assert not (tmp_path / "private/voice.json").exists()


def test_vision_selection_does_not_mutate_environment(setup_client, tmp_path, monkeypatch):
    from ecom_video import vision_model

    def reply(path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "fixture:2b", "digest": "f" * 64}]}
        assert payload == {"model": "fixture:2b"}
        assert "ECOM_VISION_MODEL" not in os.environ
        return {"capabilities": ["vision"]}

    monkeypatch.setattr(vision_model, "request", reply)
    r = setup_client.post("/api/setup/vision", json={"model": "fixture:2b"})
    assert r.status_code == 200, r.text
    assert json.loads((tmp_path / "models/vision.json").read_text())["model"] == "fixture:2b"
    assert setup_client.post("/api/setup/vision", json={"model": "remote-cloud"}).status_code == 422


def test_model_install_requires_explicit_confirmation(setup_client):
    assert setup_client.post("/api/setup/asr", json={}).status_code == 422
    r = setup_client.get("/api/setup/asr")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


def test_launcher_is_in_customer_package(tmp_path):
    import zipfile

    from ecom_video.customer_setup import build_package

    package = tmp_path / "client.zip"
    build_package(Path(__file__).resolve().parents[1], package)
    with zipfile.ZipFile(package) as z:
        assert "启动剪序.command" in z.namelist()
        assert "scripts/launch_customer.py" in z.namelist()
        assert "ecom_video/web/setup.html" in z.namelist()


def test_launcher_recognizes_only_its_own_customer_instance(tmp_path):
    from ecom_video.customer_launcher import matches_instance

    own = {"installation": "a", "customer": True}
    assert matches_instance(own, "a")
    assert not matches_instance({**own, "customer": False}, "a")
    assert not matches_instance(own, "b")
    assert not matches_instance({"status": "ok"}, "a")


def test_model_change_rejected_while_job_queued(setup_client):
    c = setup_client
    job = c.post("/api/jobs", json={"title": "fixture", "script": "外观", "seconds": 1}).json()
    with c.app.state.store.connect() as db:
        db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
    assert c.post("/api/setup/vision", json={"model": "fixture:2b"}).status_code == 409
    assert c.post("/api/setup/asr", json={"confirmed": True}).status_code == 409


def test_asr_install_validates_existing_files_without_network(tmp_path):
    import hashlib
    import time

    from ecom_video.model_install import ModelInstall

    files = {"model.int8.onnx": b"fixture-model", "tokens.txt": b"fixture-tokens"}
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/P5_MODEL.json").write_text(
        json.dumps({"files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}})
    )
    model = tmp_path / "var/models/firered"
    model.mkdir(parents=True)
    for n, v in files.items():
        (model / n).write_bytes(v)
    install = ModelInstall(tmp_path)
    install.start()
    end = time.monotonic() + 5
    while install.status()["state"] == "running" and time.monotonic() < end:
        time.sleep(0.01)
    assert install.status()["state"] == "complete"
    (model / "tokens.txt").write_bytes(b"corrupt")
    install.start()
    while install.status()["state"] == "running" and time.monotonic() < end:
        time.sleep(0.01)
    assert install.status()["state"] == "failed"
    assert (model / "tokens.txt").read_bytes() == b"corrupt"


def test_asr_download_hash_failure_keeps_install_disabled(tmp_path, monkeypatch):
    import hashlib

    import httpx

    from ecom_video import model_install

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/P5_MODEL.json").write_text(
        json.dumps(
            {
                "repo": "official/repo",
                "revision": "main",
                "files": {"tokens.txt": hashlib.sha256(b"expected").hexdigest()},
            }
        )
    )
    original = httpx.Client
    monkeypatch.setattr(
        model_install.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"wrong")),
            **kwargs,
        ),
    )
    install = model_install.ModelInstall(tmp_path)
    install.run()
    assert install.status()["state"] == "failed"
    assert not (tmp_path / "var/models/firered").exists()
    assert not list((tmp_path / "var/models").glob(".asr-install-*"))


def test_asr_cancel_preserves_old_files_and_rejects_duplicate(tmp_path, monkeypatch):
    import hashlib
    import threading
    import time

    import httpx

    from ecom_video import model_install
    from ecom_video.db import Conflict

    entered, release = threading.Event(), threading.Event()

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert release.wait(timeout=5)
            yield b"fixture"

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/P5_MODEL.json").write_text(
        json.dumps(
            {
                "repo": "official/repo",
                "revision": "main",
                "files": {"tokens.txt": hashlib.sha256(b"fixture").hexdigest()},
            }
        )
    )
    original = httpx.Client
    monkeypatch.setattr(
        model_install.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Slow())), **kwargs
        ),
    )
    install = model_install.ModelInstall(tmp_path)
    install.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(Conflict):
            install.start()
        assert install.cancel()["state"] == "cancelling"
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while install.status()["state"] in ("running", "cancelling") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert install.status()["state"] == "cancelled"
    assert not (tmp_path / "var/models/firered").exists()


def test_small_network_chunks_observe_cancellation_before_reading_more(tmp_path, monkeypatch):
    import hashlib

    import httpx

    from ecom_video import model_install

    requested_more = []

    class SmallChunks(httpx.SyncByteStream):
        def __iter__(self):
            install.stop.set()
            yield b"x"
            requested_more.append(True)
            yield b"y"

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/P5_MODEL.json").write_text(
        json.dumps(
            {
                "repo": "official/repo",
                "revision": "main",
                "files": {"tokens.txt": hashlib.sha256(b"xy").hexdigest()},
            }
        )
    )
    original = httpx.Client
    monkeypatch.setattr(
        model_install.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=SmallChunks())),
            **kwargs,
        ),
    )
    install = model_install.ModelInstall(tmp_path)
    install.run()
    assert install.status()["state"] == "cancelled"
    assert not requested_more, "Cancellation must stop at the first available network chunk"


def test_launcher_requires_complete_receipt_and_browser(tmp_path):
    from ecom_video.customer_launcher import dependencies_ready, dependency_fingerprint

    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").touch()
    (tmp_path / "render/remotion/node_modules/@remotion/renderer").mkdir(parents=True)
    (tmp_path / "uv.lock").write_text("lock")
    (tmp_path / "render/remotion/package-lock.json").write_text("lock")
    assert not dependencies_ready(tmp_path)
    browser = tmp_path / "chrome"
    browser.touch()
    receipt = tmp_path / ".customer-install.json"
    receipt.write_text(
        json.dumps({"fingerprint": dependency_fingerprint(tmp_path), "browser": str(browser)})
    )
    assert dependencies_ready(tmp_path)
    browser.unlink()
    assert not dependencies_ready(tmp_path)
    browser.touch()
    (tmp_path / "uv.lock").write_text("changed")
    assert not dependencies_ready(tmp_path)


def test_installer_timeout_stops_its_subprocess_tree(tmp_path):
    import subprocess
    import sys
    import time

    from ecom_video.customer_launcher import run_installer

    marker = tmp_path / "must-not-exist"
    child = (
        "import pathlib,time; time.sleep(1); pathlib.Path("
        + repr(str(marker))
        + ").write_text('orphan')"
    )
    parent = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "]); time.sleep(10)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_installer([sys.executable, "-c", parent], tmp_path, timeout=0.25)
    time.sleep(1.1)
    assert not marker.exists(), "Timed-out install must not leave background writers running"
