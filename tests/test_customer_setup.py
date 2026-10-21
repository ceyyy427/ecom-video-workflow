import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def test_package_has_runtime_but_no_customer_data_or_credentials(tmp_path):
    from ecom_video.customer_setup import build_package

    root = tmp_path / "source"
    for name, value in {
        "pyproject.toml": "[project]",
        "uv.lock": "locked",
        "requirements.txt": "pinned",
        "ecom_video/__init__.py": "runtime",
        "ecom_video/web/customer.html": "page",
        "ecom_video/migrations/001_initial.sql": "schema",
        "render/remotion/src/index.tsx": "video",
        "render/remotion/package-lock.json": "locked",
        "scripts/install_customer.py": "setup",
        "docs/CUSTOMER_INSTALL.md": "guide",
        ".env": "SECRET=private",
        "var/workflow.db": "private",
        "client-projects/customer.mp4": "private",
        "ecom_video/__pycache__/secret.pyc": "private",
        "render/remotion/node_modules/secret": "private",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    target = tmp_path / "customer.zip"
    result = build_package(root, target)
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        assert "ecom_video/web/customer.html" in names
        assert "render/remotion/src/index.tsx" in names
        assert "scripts/install_customer.py" in names
        assert not any("private" in z.read(n).decode() for n in names)
        manifest = json.loads(z.read("PACKAGE.json"))
        for item in manifest["files"]:
            assert hashlib.sha256(z.read(item["path"])).hexdigest() == item["sha256"]
    assert result["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        build_package(root, target)


def test_package_rejects_symlink_in_runtime(tmp_path):
    from ecom_video.customer_setup import build_package

    root = tmp_path / "source"
    (root / "ecom_video").mkdir(parents=True)
    secret = tmp_path / "private.py"
    secret.write_text("secret")
    (root / "ecom_video/private.py").symlink_to(secret)
    with pytest.raises(ValueError):
        build_package(root, tmp_path / "customer.zip")
    assert not (tmp_path / "customer.zip").exists()


def test_local_asr_import_verifies_before_creating_destination(tmp_path):
    from ecom_video.customer_setup import import_asr

    source = tmp_path / "models"
    source.mkdir()
    (source / "model.int8.onnx").write_bytes(b"model")
    (source / "tokens.txt").write_bytes(b"tokens")
    expected = {
        n: hashlib.sha256((source / n).read_bytes()).hexdigest()
        for n in ("model.int8.onnx", "tokens.txt")
    }
    target = tmp_path / "installed"
    assert import_asr(source, target, expected)["verified"]
    assert (target / "tokens.txt").read_bytes() == b"tokens"
    (source / "tokens.txt").write_bytes(b"bad")
    with pytest.raises(ValueError):
        import_asr(source, tmp_path / "rejected", expected)
    assert not (tmp_path / "rejected").exists()
    assert (target / "tokens.txt").read_bytes() == b"tokens"


def test_customer_profile_disables_platform_writes_and_auto_execution(monkeypatch):
    from ecom_video.customer_setup import customer_profile

    monkeypatch.setenv("ECOM_QIANCHUAN_WRITES", "1")
    monkeypatch.setenv("ECOM_AGENT_EXECUTION_ENABLED", "1")
    customer_profile()
    import os

    assert os.environ["ECOM_QIANCHUAN_WRITES"] == "0"
    assert os.environ["ECOM_AGENT_EXECUTION_ENABLED"] == "0"
    assert os.environ["ECOM_REVIEW_SNAPSHOTS_ENABLED"] == "1"
    assert os.environ["ECOM_EXPERIMENTS_ENABLED"] == "1"


def test_configure_model_persists_only_verified_local_identity(tmp_path, monkeypatch):
    from ecom_video import vision_model
    from ecom_video.customer_setup import configure_vision

    # External Ollama service is the only replaced boundary; no inference.
    def reply(path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "local:2b", "digest": "a" * 64}]}
        assert path == "/api/show" and payload == {"model": "local:2b"}
        return {"capabilities": ["vision"]}

    monkeypatch.setattr(vision_model, "request", reply)
    dest = tmp_path / "models/vision.json"
    configure_vision("local:2b", dest)
    assert json.loads(dest.read_text())["model"] == "local:2b"
    with pytest.raises(ValueError):
        configure_vision("remote-cloud:latest", dest)
    assert json.loads(dest.read_text())["model"] == "local:2b"


def test_customer_api_mode_enforces_safe_profile(tmp_path):
    import os
    import socket
    import time

    import httpx

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ecom_video",
            "--customer",
            "--api-only",
            "--data",
            str(tmp_path),
            "--port",
            str(port),
        ],
        env={**os.environ, "ECOM_QIANCHUAN_WRITES": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1) as c:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    r = c.get("/api/system/check")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("customer server unavailable")
            assert r.json()["platform_writes_enabled"] is False
            assert c.get("/api/reviews/capabilities").json()["enabled"]
            assert c.get("/api/experiments/capabilities").json()["enabled"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    with sqlite3.connect(tmp_path / "workflow.db") as c:
        assert c.execute("select count(*) from jobs").fetchone()[0] == 0


def test_old_node_is_not_reported_as_render_ready(tmp_path, monkeypatch):
    import os

    from ecom_video.maintenance import check

    binary = tmp_path / "node"
    binary.write_text("#!/bin/sh\nprintf 'v18.20.4\\n'\n")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert check(tmp_path / "not-created")["ready"] is False


def test_first_install_instructions_are_reachable_from_running_app(tmp_path):
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app

    with TestClient(create_app(tmp_path), base_url="http://localhost") as c:
        result = c.get("/api/system/install-guide")
        assert result.status_code == 200
        assert "attachment" in result.headers["content-disposition"]
        assert "--customer" in result.text
        assert "--simulate-confirmations" in result.text


def test_packaged_private_voice_setup_is_executable_without_key(tmp_path):
    from ecom_video.customer_setup import build_package

    target = tmp_path / "client.zip"
    build_package(Path(__file__).resolve().parents[1], target)
    extracted = tmp_path / "client"
    with zipfile.ZipFile(target) as archive:
        archive.extractall(extracted)
    result = subprocess.run(
        [sys.executable, str(extracted / "scripts/volc_voice_setup.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=extracted,
    )
    assert result.returncode == 0, result.stderr
    assert "--speaker" in result.stdout
    assert not (extracted / "var").exists()


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swift"), reason="macOS Vision runtime only"
)
def test_packaged_ocr_adapter_runs_on_local_image(tmp_path):
    from PIL import Image

    from ecom_video.customer_setup import build_package

    target = tmp_path / "client.zip"
    build_package(Path(__file__).resolve().parents[1], target)
    extracted = tmp_path / "client"
    with zipfile.ZipFile(target) as archive:
        archive.extractall(extracted)
    image = tmp_path / "frame.png"
    Image.new("RGB", (240, 320), "white").save(image)
    output = tmp_path / "ocr.json"
    result = subprocess.run(
        ["swift", str(extracted / "scripts/local_ocr.swift"), str(output), str(image)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(output.read_text())["frames"]) == 1
