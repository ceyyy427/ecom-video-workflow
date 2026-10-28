import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mac_package_contains_exact_case_locked_resources_and_customer_guides(tmp_path):
    from ecom_video.customer_setup import build_package

    target = tmp_path / "candidate.zip"
    build_package(ROOT, target)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "docs/third-party/domestic-toolkit.lock.json" in names
        lock = json.loads(archive.read("docs/third-party/domestic-toolkit.lock.json"))
        for row in lock["files"]:
            assert lock["resource_root"] + "/" + row["path"] in names
        for name in (
            "docs/MAC_WORKBENCH_GUIDE.md",
            "docs/DOMESTIC_SUITE_GUIDE.md",
            "requirements-mcp.txt",
        ):
            assert name in names
        assert not any(
            name.startswith(("var/", "vendor/MoneyPrinterTurbo/", "client-projects/"))
            or name.endswith((".mp4", ".onnx", ".safetensors"))
            for name in names
        )


def test_017_loader_bridge_contains_only_legacy_permitted_files(tmp_path):
    from ecom_video.customer_setup import build_bridge

    target = tmp_path / "bridge.zip"
    build_bridge(ROOT, target, bridge_version="0.17.1")
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("PACKAGE.json"))
        assert manifest["release"]["version"] == "0.17.1"
        assert not any(name.startswith("resources/") for name in archive.namelist())
        assert "docs/CUSTOMER_HANDOFF.md" in archive.namelist()
        assert b'version = "0.17.1"' in archive.read("pyproject.toml")
        assert b'version = "0.17.1"' in archive.read("uv.lock")


def test_shipped_customer_guides_have_their_direct_local_markdown_links(tmp_path):
    import posixpath
    import re
    from urllib.parse import urlsplit

    from ecom_video.customer_setup import build_package

    package = tmp_path / "candidate.zip"
    build_package(ROOT, package)
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        for guide in (
            "docs/MAC_WORKBENCH_GUIDE.md",
            "docs/DOMESTIC_ACCEPTANCE.md",
            "docs/VOICESTUDIO_LOCAL.md",
            "docs/TYPOGRAPHY_PROMPT_GUIDE.md",
        ):
            for href in re.findall(r"\]\(([^)]+)\)", archive.read(guide).decode()):
                link = urlsplit(href)
                if not link.scheme and link.path.endswith(".md"):
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(guide), link.path))
                    assert target in names, (guide, target)


def test_loader_bridge_changes_only_application_version_not_a_same_number_dependency(tmp_path):
    import tomllib

    from ecom_video.customer_setup import build_bridge

    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        '[project]\nname="ecom-video-workflow"\nversion = "0.17.0"\n'
    )
    (source / "uv.lock").write_text(
        '[[package]]\nname = "ecom-video-workflow"\nversion = "0.17.0"\n\n[[package]]\nname = "ruff"\nversion = "0.17.0"\n'
    )
    target = tmp_path / "bridge.zip"
    build_bridge(source, target, bridge_version="0.17.1")
    with zipfile.ZipFile(target) as z:
        versions = {
            p["name"]: p["version"] for p in tomllib.loads(z.read("uv.lock").decode())["package"]
        }
    assert versions == {"ecom-video-workflow": "0.17.1", "ruff": "0.17.0"}
