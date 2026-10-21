"""Native contracts also runnable on Windows without models, secrets or cloud."""

import json
import os
import subprocess
import sys

import pytest


def test_windows_python_path_is_used_for_receipt(tmp_path, monkeypatch):
    from ecom_video import customer_launcher as launcher
    from ecom_video import host_os

    monkeypatch.setattr(host_os, "WINDOWS", True)
    (tmp_path / ".venv/Scripts").mkdir(parents=True)
    (tmp_path / ".venv/Scripts/python.exe").touch()
    (tmp_path / "render/remotion/node_modules/@remotion/renderer").mkdir(parents=True)
    (tmp_path / "uv.lock").write_text("fixture")
    (tmp_path / "render/remotion/package-lock.json").write_text("fixture")
    browser = tmp_path / "browser.exe"
    browser.touch()
    (tmp_path / ".customer-install.json").write_text(
        json.dumps(
            {"browser": str(browser), "fingerprint": launcher.dependency_fingerprint(tmp_path)}
        )
    )
    assert launcher.dependencies_ready(tmp_path)


def test_shared_lock_allows_readers_excludes_writer_and_close_releases(tmp_path):
    from ecom_video.maintenance_lock import acquire

    reader = acquire(tmp_path)
    script = """
import os, sys
from ecom_video.maintenance_lock import acquire, MaintenanceBusy
try:
    fd = acquire(sys.argv[1], exclusive=sys.argv[2] == 'write')
except MaintenanceBusy:
    sys.exit(23)
os.close(fd)
"""

    def run(kind):
        return subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), kind], timeout=15
        ).returncode

    try:
        assert run("read") == 0
        assert run("write") == 23
    finally:
        os.close(reader)
    assert run("write") == 0
    writer = acquire(tmp_path, exclusive=True)
    try:
        assert run("read") == 23
    finally:
        os.close(writer)


def test_windows_launchers_and_delivery_docs_are_packaged(tmp_path):
    import zipfile

    from ecom_video.customer_setup import PROJECT, build_package

    target = tmp_path / "release.zip"
    build_package(PROJECT, target)
    with zipfile.ZipFile(target) as archive:
        assert {
            "启动剪序.cmd",
            "验收剪序.cmd",
            "scripts/customer_windows.ps1",
            "docs/CUSTOMER_WINDOWS.md",
            "docs/CUSTOMER_HANDOFF.md",
        } <= set(archive.namelist())


def test_recovery_writes_both_relative_launchers(tmp_path):
    from ecom_video.customer_recovery import Recovery

    service = Recovery(tmp_path / "data")
    service.launch_file(tmp_path, "启动新版本.command")
    command = (tmp_path / "启动新版本.cmd").read_text(encoding="utf-8-sig")
    assert 'cd /d "%~dp0application"' in command
    assert "--data ../data --port 8770" in command
    assert "call" in command


def test_cancelled_media_process_is_reaped(tmp_path):
    from ecom_video.media import run_checked

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls > 2:
            raise ValueError("fixture cancel")

    with pytest.raises(ValueError, match="fixture cancel"):
        run_checked([sys.executable, "-c", "import time; time.sleep(60)"], cancel)


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows DPAPI")
def test_windows_voice_key_encrypted_and_roundtrips(tmp_path, monkeypatch):
    from ecom_video.voice_config import save_config
    from ecom_video.volc_voice import read_config

    path = tmp_path / "private/voice.json"
    monkeypatch.delenv("DOUBAO_TTS_API_KEY", raising=False)
    monkeypatch.setenv("ECOM_VOLC_VOICE_CONFIG", str(path))
    key = "unusable-native-windows-fixture-only"
    save_config(path, key, "zh_female_vv_uranus_bigtts")
    assert key.encode() not in path.read_bytes()
    assert read_config()[0] == key
    with pytest.raises(FileExistsError):
        save_config(path, "different-fixture", "zh_female_vv_uranus_bigtts")
    save_config(path, "replacement-fixture", "zh_female_vv_uranus_bigtts", replace=True)
    assert read_config()[0] == "replacement-fixture"
    path.write_text('{"api_key":"plaintext-rejected"}')
    from ecom_video.volc_voice import VoiceError

    with pytest.raises(VoiceError):
        read_config()


def test_windows_npm_shim_is_never_passed_to_shell(tmp_path, monkeypatch):
    from ecom_video import host_os

    monkeypatch.setattr(host_os, "WINDOWS", True)
    npm = tmp_path / "node & tools/npm.cmd"
    npm.parent.mkdir()
    npm.touch()
    cli = npm.parent / "node_modules/npm/bin/npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.touch()
    monkeypatch.setattr(
        host_os.shutil, "which", lambda name: str(npm) if name == "npm" else "node.exe"
    )
    assert host_os.npm_command()[0] == "node.exe"
    assert host_os.npm_command()[1] == str(cli)


def test_windows_local_speech_uses_fixed_script_and_no_command_text(tmp_path, monkeypatch):
    from ecom_video import customer_demo_speech

    text = tmp_path / "script & 文稿.txt"
    output = tmp_path / "voice.wav"
    text.write_text("示例文稿", encoding="utf-8")
    commands = []
    monkeypatch.setattr(customer_demo_speech, "WINDOWS", True)
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))

    def run(args, **kwargs):
        commands.append(args)
        output.write_bytes(b"fixture")

    monkeypatch.setattr(customer_demo_speech.subprocess, "run", run)
    customer_demo_speech.synthesize(text, output)
    assert "-Command" not in commands[0]
    assert "-ExecutionPolicy" not in commands[0]
    assert str(text) in commands[0]
    assert "示例文稿" not in commands[0]


def test_existing_demo_data_must_be_empty_and_beside_evidence(tmp_path):
    from ecom_video.customer_demo_speech import demo_data
    from ecom_video.db import Store

    workspace = tmp_path / "evidence"
    data = tmp_path / "data"
    store = Store(data / "workflow.db")
    assert demo_data(workspace, data) == data
    store.create_job("existing customer", "文稿", 1)
    with pytest.raises(ValueError, match="空白"):
        demo_data(workspace, data)
    with pytest.raises(ValueError):
        demo_data(workspace, tmp_path / "nested/data")


def test_page_guides_are_downloadable_without_exposing_paths(tmp_path):
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app

    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        for route, title in [("windows-guide", "Windows 安装"), ("handoff-guide", "客户交付清单")]:
            response = client.get("/api/system/" + route)
            assert response.status_code == 200
            assert title in response.text
            assert "attachment" in response.headers["content-disposition"]


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows Job Object")
def test_windows_forced_launcher_exit_kills_child(tmp_path):
    import ctypes as ct
    import time
    from ctypes import wintypes as wt

    pid_file = tmp_path / "child.pid"
    code = """
import subprocess, sys, time
from pathlib import Path
from ecom_video.host_os import protect_descendants
protect_descendants()
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
temporary = Path(sys.argv[1] + '.tmp')
temporary.write_text(str(p.pid))
temporary.replace(sys.argv[1])
time.sleep(60)
"""
    parent = subprocess.Popen([sys.executable, "-c", code, str(pid_file)])
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (
        [wt.DWORD, wt.BOOL, wt.DWORD],
        wt.HANDLE,
    )
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = (
        [wt.HANDLE, wt.DWORD],
        wt.DWORD,
    )
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    child_handle = None
    try:
        end = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < end:
            if parent.poll() is not None:
                raise AssertionError("launcher could not establish Windows job")
            time.sleep(0.05)
        child_handle = kernel.OpenProcess(0x100000, False, int(pid_file.read_text()))
        assert child_handle
        parent.terminate()
        parent.wait(timeout=10)
        assert kernel.WaitForSingleObject(child_handle, 10000) == 0
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)
        if child_handle:
            kernel.CloseHandle(child_handle)


def test_new_release_missing_windows_entry_is_rejected(tmp_path):
    import hashlib
    import zipfile

    from ecom_video.customer_archives import unpack_release
    from ecom_video.customer_setup import PROJECT, build_package
    from ecom_video.maintenance import MaintenanceError

    original = tmp_path / "original.zip"
    broken = tmp_path / "broken.zip"
    build_package(PROJECT, original)
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(broken, "w") as target:
        manifest = json.loads(source.read("PACKAGE.json"))
        manifest["files"] = [r for r in manifest["files"] if r["path"] != "启动剪序.cmd"]
        for name in source.namelist():
            if name not in ("启动剪序.cmd", "PACKAGE.json"):
                target.writestr(name, source.read(name))
        target.writestr("PACKAGE.json", json.dumps(manifest))
    sha = hashlib.sha256(broken.read_bytes()).hexdigest()
    with pytest.raises(MaintenanceError):
        unpack_release(broken, tmp_path / "candidate", sha, 14, "0.12.0")


def test_bridge_package_uses_legacy_envelope_but_updates_loader(tmp_path):
    import tomllib
    import zipfile

    from ecom_video.customer_setup import PROJECT, build_bridge

    target = tmp_path / "bridge.zip"
    build_bridge(PROJECT, target)
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("PACKAGE.json"))
        assert manifest["release"]["version"] == "0.12.1"
        assert manifest["release"]["maintenance_protocol"] == 1
        assert (
            tomllib.loads(archive.read("pyproject.toml").decode())["project"]["version"] == "0.12.1"
        )
        assert "启动剪序.cmd" not in archive.namelist()
        assert "docs/CUSTOMER_WINDOWS.md" not in archive.namelist()
        assert "scripts/customer_windows.ps1" not in archive.namelist()
        assert b"0.12.1" in archive.read("ecom_video/api.py")
        assert b"windows_dpapi.py" in archive.read("ecom_video/customer_archives.py")
        assert "启动剪序.cmd" in archive.read("ecom_video/customer_setup.py").decode()
        for row in manifest["files"]:
            import hashlib

            assert row["sha256"] == hashlib.sha256(archive.read(row["path"])).hexdigest()
