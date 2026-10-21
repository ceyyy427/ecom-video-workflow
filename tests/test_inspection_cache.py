"""Only pinned v3 observations are reusable; v4 actions are always recomputed."""

import copy
import json
from pathlib import Path

import pytest
from PIL import Image
from test_customer import client, picture, project

from ecom_video import product_inspection, vision_model
from ecom_video.creative import signature
from ecom_video.db import Conflict, Store
from ecom_video.media import digest
from ecom_video.media_analysis import Analysis

OLD_INSPECTION = "20f3a82b037567a86b01360b747e78d6091cd0c0c9b65a5d4ff030ccf065a7a1"
MODEL = {"model": "fixture", "digest": "fixed", "provider": "fixture"}


@pytest.fixture
def cached(tmp_path, monkeypatch):
    monkeypatch.setattr(product_inspection, "VERSION", "reference-motion-v4")
    c = client(tmp_path)
    p = picture(c, project(c))
    base = f"/api/customer-projects/{p['id']}"
    p = c.put(
        base,
        json={
            "revision": p["revision"],
            "settings": {
                **p["settings"],
                "strict_product": True,
                "action_timing": True,
                "product_reference_id": p["media"][0]["id"],
            },
        },
    ).json()
    store = Store(tmp_path / "workflow.db")
    service = Analysis(tmp_path, store)
    with monkeypatch.context() as old:
        old.setattr(product_inspection, "VERSION", "reference-motion-v3")
        row = service.start(p["id"], p["media"][0]["id"])
    folder = tmp_path / "analyses" / row["id"]
    folder.mkdir(parents=True)
    for name in ("coarse.jpg", "before.jpg", "after.jpg"):
        Image.new("RGB", (20, 20), "gray").save(folder / name)
    package = Path(product_inspection.__file__).parent
    result = {
        "analysis_id": row["id"],
        "context": row["result"]["context"],
        "model": MODEL,
        "source_sha256": row["source_sha256"],
        "recognition": "complete",
        "engine": signature(
            {
                "model": MODEL,
                "scanner": digest(package / "clip_scan.py"),
                "adapter": digest(package / "vision_model.py"),
                "inspection": OLD_INSPECTION,
            }
        ),
        "segments": [
            {
                "id": "clip-00",
                "start": 0,
                "end": 2,
                "frames": ["coarse.jpg", "before.jpg", "after.jpg"],
                "sample_times": [0, 0, 1],
                "quality": {"blank": False},
                "observation": {"usable": True, "description": "fixture"},
                "motion_check": {
                    "version": "reference-motion-v3",
                    "reference_sha256": p["media"][0]["sha256"],
                    "identity": "same",
                    "samples": [
                        {
                            "time": t,
                            "frame": f,
                            "match": "same",
                            "target_count": "one",
                            "lid": lid,
                            "flow": "absent",
                            "handling_lid": True,
                        }
                        for t, f, lid in [
                            (0, "before.jpg", "attached"),
                            (1, "after.jpg", "detached"),
                        ]
                    ],
                    "events": [{"kind": "open_lid", "start": 0, "end": 1, "anchor": 0.5}],
                },
            }
        ],
    }
    with store.transaction() as db:
        db.execute(
            "UPDATE media_analyses SET status='ready',result=? WHERE id=?",
            (json.dumps(result), row["id"]),
        )
    asset = p["media"][0]
    context = {**result["context"], "version": "reference-motion-v4"}
    return tmp_path, service, p, asset, row, result, context


def reuse(cached, check=lambda: None):
    from ecom_video.inspection_cache import reuse_observations

    root, service, _, asset, _, _, context = cached
    return reuse_observations(
        root, service.store, asset, context, MODEL, root / "analyses" / "new", check
    )


def test_pinned_cache_copies_frames_and_discards_old_events_without_mutating_history(cached):
    root, service, _, _, old, result, _ = cached
    accepted = reuse(cached)
    assert accepted["reused_observations_from"] == old["id"]
    assert accepted["segments"][0]["motion_check"]["events"] == []
    for name in result["segments"][0]["frames"]:
        assert digest(root / "analyses" / "new" / name) == digest(
            root / "analyses" / old["id"] / name
        )
    with service.store.connect() as db:
        assert (
            json.loads(
                db.execute("SELECT result FROM media_analyses WHERE id=?", (old["id"],)).fetchone()[
                    "result"
                ]
            )
            == result
        )


@pytest.mark.parametrize(
    "change",
    [
        "v1",
        "v2",
        "engine",
        "model",
        "context",
        "source",
        "partial",
        "frame_traversal",
        "frame_symlink",
        "missing_frame",
        "actual_source",
    ],
)
def test_untrusted_or_mismatched_cache_is_not_reused(cached, change):
    root, service, _, asset, row, result, _ = cached
    result = copy.deepcopy(result)
    status = "ready"
    if change in ("v1", "v2"):
        result["context"]["version"] = "reference-motion-" + change
    elif change == "engine":
        result["engine"] = "unknown"
    elif change == "model":
        result["model"] = {**MODEL, "digest": "different"}
    elif change == "context":
        result["context"]["action_timing"] = False
    elif change == "source":
        result["source_sha256"] = "wrong"
    elif change == "partial":
        status = "partial"
    elif change == "frame_traversal":
        result["segments"][0]["frames"][0] = "../outside.jpg"
    elif change == "frame_symlink":
        frame = root / "analyses" / row["id"] / "coarse.jpg"
        frame.unlink()
        frame.symlink_to(root / asset["path"])
    elif change == "missing_frame":
        (root / "analyses" / row["id"] / "before.jpg").unlink()
    else:
        (root / asset["path"]).write_bytes(b"changed")
    with service.store.transaction() as db:
        db.execute(
            "UPDATE media_analyses SET status=?,result=? WHERE id=?",
            (status, json.dumps(result), row["id"]),
        )
    assert reuse(cached) is None


def test_cache_copy_obeys_cancellation(cached):
    def cancelled():
        raise Conflict("cancelled")

    with pytest.raises(Conflict, match="cancelled"):
        reuse(cached, cancelled)


@pytest.mark.parametrize("interruption", [None, "cancel", "context", "source_file", "model"])
def test_analysis_refines_copied_observations_and_never_publishes_after_invalidation(
    cached, monkeypatch, interruption
):
    from ecom_video import clip_scan

    root, service, p, asset, old, original, _ = cached
    new = service.start(p["id"], asset["id"])
    assert (root / "analyses" / old["id"] / "before.jpg").is_file()
    row = service.claim()
    current_model = [MODEL]
    monkeypatch.setattr(vision_model, "identity", lambda: current_model[0])

    def forbidden(*args, **kwargs):
        raise AssertionError("full sampling must not run for pinned cache")

    monkeypatch.setattr(clip_scan, "scan", forbidden)
    monkeypatch.setattr(vision_model, "observe", forbidden)
    calls = []

    def refine(segment, folder, model, check, context):
        calls.append(segment["id"])
        assert not segment["motion_check"]["events"]
        assert (folder / "before.jpg").is_file()
        segment["motion_check"].update(version="reference-motion-v4", events=[])
        if interruption == "cancel":
            service.cancel(p["id"], asset["id"])
        if interruption == "context":
            with service.store.transaction() as db:
                settings = {**p["settings"], "action_timing": False}
                db.execute(
                    "UPDATE customer_projects SET settings=? WHERE product_id=?",
                    (json.dumps(settings), p["id"]),
                )
        if interruption == "source_file":
            (root / asset["path"]).write_bytes(b"changed during refinement")
        if interruption == "model":
            current_model[0] = {**MODEL, "digest": "changed"}

    monkeypatch.setattr(product_inspection, "refine_segment", refine, raising=False)
    if interruption:
        with pytest.raises(Conflict):
            service.run(row, lambda: None)
        assert service.get(p["id"], asset["id"])["status"] != "ready"
    else:
        service.run(row, lambda: None)
        ready = service.get(p["id"], asset["id"])
        assert ready["status"] == "ready" and ready["id"] == new["id"]
        assert ready["result"]["reused_observations_from"] == old["id"]
        assert ready["result"]["segments"][0]["motion_check"]["version"] == "reference-motion-v4"
    assert calls == ["clip-00"]
    with service.store.connect() as db:
        assert (
            json.loads(
                db.execute("SELECT result FROM media_analyses WHERE id=?", (old["id"],)).fetchone()[
                    "result"
                ]
            )
            == original
        )


def test_invalid_cache_uses_full_scan_instead_of_partial_reuse(cached, monkeypatch):
    from ecom_video import clip_scan

    _, service, p, asset, old, _, _ = cached
    with service.store.transaction() as db:
        db.execute(
            "UPDATE media_analyses SET result=json_set(result,'$.engine','unknown') WHERE id=?",
            (old["id"],),
        )
    service.start(p["id"], asset["id"])
    row = service.claim()
    monkeypatch.setattr(vision_model, "identity", lambda: MODEL)
    calls = []

    def scan(*args):
        calls.append("scan")
        return {"segments": [{"id": "fresh", "frames": [], "quality": {"blank": True}}]}

    def forbidden(*args):
        raise AssertionError("invalid cache must not invoke refinement")

    monkeypatch.setattr(clip_scan, "scan", scan)
    monkeypatch.setattr(product_inspection, "refine_segment", forbidden)
    service.run(row, lambda: None)
    result = service.get(p["id"], asset["id"])["result"]
    assert calls == ["scan"] and "reused_observations_from" not in result
    assert result["segments"][0]["id"] == "fresh"


def test_reference_actual_hash_is_checked_separately_from_media(cached):
    root, service, _, _, old, result, context = cached
    reference = root / "separate-reference.png"
    Image.new("RGB", (20, 20), "red").save(reference)
    context["reference_path"] = "separate-reference.png"
    result["context"]["reference_path"] = "separate-reference.png"
    with service.store.transaction() as db:
        db.execute("UPDATE media_analyses SET result=? WHERE id=?", (json.dumps(result), old["id"]))
    assert reuse(cached) is None


def test_changed_frame_during_copy_cannot_be_reused(cached, monkeypatch):
    import shutil

    original = shutil.copyfile

    def corrupt(source, destination):
        original(source, destination)
        Path(destination).write_bytes(b"changed during copy")

    monkeypatch.setattr(shutil, "copyfile", corrupt)
    assert reuse(cached) is None


def test_published_v3_adapter_remains_an_exact_compatible_cache_source(cached):
    root, service, _, _, old, result, _ = cached
    package = Path(product_inspection.__file__).parent
    result["engine"] = signature(
        {
            "model": MODEL,
            "scanner": digest(package / "clip_scan.py"),
            "adapter": "4e98d0c96d9757cbb957db115f7c68b63bb5b1f13731450d4bbdd91fa16ac80c",
            "inspection": OLD_INSPECTION,
        }
    )
    with service.store.transaction() as db:
        db.execute("UPDATE media_analyses SET result=? WHERE id=?", (json.dumps(result), old["id"]))
    assert reuse(cached) is not None
