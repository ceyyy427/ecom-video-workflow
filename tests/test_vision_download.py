"""Official-model installer boundaries; no network or model execution in unit tests."""

import hashlib

import httpx
import pytest

from scripts import download_qwen_vision as installer


def test_model_download_resumes_exact_range_and_verifies_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "DEST", tmp_path)
    monkeypatch.setattr(installer, "validate_url", lambda url: None)
    name = "unit-model.gguf"
    payload = b"GGUF" + b"unit test weights"
    (tmp_path / (name + ".part")).write_bytes(payload[:4])
    seen = []

    def handler(request):
        seen.append(request.headers["range"])
        return httpx.Response(
            206,
            content=payload[4:],
            headers={"content-range": f"bytes 4-{len(payload) - 1}/{len(payload)}"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        installer.download(c, name, len(payload), hashlib.sha256(payload).hexdigest())
    assert seen == [f"bytes=4-{len(payload) - 1}"]
    assert (tmp_path / name).read_bytes() == payload
    assert not (tmp_path / (name + ".chunks")).exists()


def test_model_download_rejects_wrong_bytes_without_installing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "DEST", tmp_path)
    monkeypatch.setattr(installer, "validate_url", lambda url: None)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                206, content=b"wrong", headers={"content-range": "bytes 0-4/5"}
            )
        )
    ) as c, pytest.raises(ValueError, match="SHA256"):
        installer.download(c, "bad.gguf", 5, hashlib.sha256(b"right").hexdigest())
    assert not (tmp_path / "bad.gguf").exists()


def test_installer_rejects_untrusted_redirects_and_private_resolution(monkeypatch):
    with pytest.raises(ValueError, match="Unexpected"):
        installer.validate_url("https://evil.example/model.gguf")
    with pytest.raises(ValueError, match="HTTPS"):
        installer.validate_url("http://modelscope.cn/model.gguf")
    monkeypatch.setattr(
        installer.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("198.18.0.1", 443))]
    )
    with pytest.raises(ValueError, match="public"):
        installer.validate_url("https://cdn-lfs-cn-1.modelscope.cn/model.gguf")
