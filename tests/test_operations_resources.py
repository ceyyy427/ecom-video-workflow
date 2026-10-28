"""Resource locks are checked as data; upstream scripts are never imported."""

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "docs/third-party/domestic-toolkit.lock.json"


def test_packaged_bundle_has_verified_sources_but_no_executable_methods():
    from ecom_video.operations.resources import load_resources

    bundle = load_resources(LOCK)
    assert bundle.upstream_commit == "cec98a9cab382d28dfe5b4ed0de444f33c455cb5"
    assert bundle.fork_repository == "ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit"
    assert bundle.license_id == "MIT" and len(bundle.entries) >= 10
    assert "不渲染视频" in bundle.read("upstream-video-readme")
    assert all(r.status == "reference" for r in bundle.entries if r.id.startswith("upstream-"))
    assert all(
        r.kind in {"license", "readme", "prompt", "template", "reference", "script", "manifest"}
        for r in bundle.entries
    )


def copied_bundle(tmp_path):
    import shutil

    shutil.copytree(ROOT / "resources/domestic-toolkit", tmp_path / "resources/domestic-toolkit")
    lock = tmp_path / "docs/third-party/domestic-toolkit.lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(LOCK.read_bytes())
    return lock, json.loads(lock.read_text())


@pytest.mark.parametrize(
    "damage",
    [
        "hash",
        "size",
        "traversal",
        "absolute",
        "symlink",
        "duplicate",
        "script_suffix",
        "license",
        "source",
        "missing",
    ],
)
def test_corrupted_or_unsafe_resource_never_loads(tmp_path, damage):
    from ecom_video.operations.resources import ResourceError, load_resources

    lock, data = copied_bundle(tmp_path)
    item = next(r for r in data["files"] if r["id"] == "upstream-video-readme")
    resource = tmp_path / data["resource_root"] / item["path"]
    if damage == "hash":
        resource.write_text("changed")
    elif damage == "size":
        item["size_bytes"] += 1
    elif damage == "traversal":
        item["path"] = "../LICENSE"
    elif damage == "absolute":
        item["path"] = str(resource)
    elif damage == "symlink":
        outside = tmp_path / "outside.md"
        outside.write_bytes(resource.read_bytes())
        resource.unlink()
        resource.symlink_to(outside)
    elif damage == "duplicate":
        data["files"].append(copy.deepcopy(item))
    elif damage == "script_suffix":
        item["path"] = "unexpected.sh"
    elif damage == "license":
        data["license"]["sha256"] = "0" * 64
    elif damage == "source":
        item["source"]["repository"] = "other/untrusted"
    elif damage == "missing":
        resource.unlink()
    lock.write_text(json.dumps(data))
    with pytest.raises(ResourceError):
        load_resources(lock, project_root=tmp_path)


def test_duplicate_json_fields_and_oversized_lock_are_rejected(tmp_path):
    from ecom_video.operations.resources import ResourceError, load_resources

    lock = tmp_path / "lock.json"
    for text in ('{"schema_version":1,"schema_version":2}', " " * (512 * 1024 + 1)):
        lock.write_text(text)
        with pytest.raises(ResourceError):
            load_resources(lock, project_root=tmp_path)


def test_source_path_cannot_be_relabelled_to_a_different_upstream_file(tmp_path):
    from ecom_video.operations.resources import ResourceError, load_resources

    lock, data = copied_bundle(tmp_path)
    item = next(r for r in data["files"] if r["id"] == "upstream-video-readme")
    item["source"]["path"] = "Agents/01_Market_Research_Agent/README.md"
    lock.write_text(json.dumps(data))
    with pytest.raises(ResourceError):
        load_resources(lock, project_root=tmp_path)


def test_verified_resource_metadata_cannot_be_mutated_after_loading():
    from pydantic import ValidationError

    from ecom_video.operations.resources import load_resources

    resource = load_resources(LOCK).entries[0]
    with pytest.raises(ValidationError):
        resource.status = "verified"
    with pytest.raises(ValidationError):
        resource.source.commit = "0" * 40


def test_deeply_nested_invalid_json_is_a_safe_resource_error(tmp_path):
    from ecom_video.operations.resources import ResourceError, load_resources

    lock = tmp_path / "lock.json"
    lock.write_text("[" * 1500 + "0" + "]" * 1500)
    with pytest.raises(ResourceError):
        load_resources(lock, project_root=tmp_path)
