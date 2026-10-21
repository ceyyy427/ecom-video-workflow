import json

import pytest
from test_review_snapshots import command, ingest

from ecom_video.db import Store
from ecom_video.distribution import Distribution
from ecom_video.media import digest
from ecom_video.reporting import Reporting


def ready(root, store, *, snapshot=True, title="fixture 商品", style="cinema"):
    job = store.create_job(title, "当前字段不同于冻结稿", 3)
    file = root / (job["id"] + ".mp4")
    file.write_bytes(b"AUTOMATED FIXTURE not a playable video")
    frozen = {
        "title": "冻结标题",
        "script": "先看杯口细节\n再放到桌上",
        "seconds": 3,
        "storyboard_revision": 2,
        "assets": [{"id": "asset", "kind": "video", "sha256": "a" * 64}],
        "storyboard": {
            "creative": {"style_id": style, "brief": {"format": "narrated"}},
            "shots": [
                {
                    "shot_id": "one",
                    "asset_id": "asset",
                    "duration": 3,
                    "transition": "cut",
                    "headline": "杯口细节",
                },
                {"shot_id": "two", "asset_id": "asset", "duration": 3, "transition": "wipe"},
            ],
            "narration": {"mode": "uploaded"},
            "music_id": None,
        },
    }
    with store.transaction() as c:
        c.execute(
            "UPDATE jobs SET status='ready',snapshot=?,storyboard=?,storyboard_revision=99 WHERE id=?",
            (
                json.dumps(frozen, ensure_ascii=False) if snapshot else None,
                json.dumps({"creative": {"style_id": "social"}}),
                job["id"],
            ),
        )
        c.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            (job["id"], job["id"], "video", file.name, digest(file), file.stat().st_size, 1),
        )
    return job["id"], digest(file), frozen


@pytest.fixture
def linked(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    store = Store(tmp_path / "workflow.db")
    dist = Distribution(tmp_path, store)
    aid = dist.add_account("fixture", "qianchuan", "123")["id"]
    jid, video, snapshot = ready(tmp_path, store)
    reports = Reporting(tmp_path, store)
    reports.bind(aid, "123", jid, "AUTOMATED FIXTURE binding")
    ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    from ecom_video.review_snapshots import Reviews

    return Reviews(tmp_path, store), reports, aid, jid, video, snapshot


def test_features_only_use_frozen_submission_and_preserve_lineage(linked):
    reviews, _, aid, jid, video, _ = linked
    frozen = reviews.create(command(aid, end="2026-10-01"))
    feature = frozen["snapshot"]["materials"][0]["creative_feature"]
    assert feature["job_id"] == jid and feature["video_sha256"] == video
    assert feature["features"]["hook_text"] == "先看杯口细节"
    assert feature["features"]["style_id"] == "cinema"
    assert feature["features"]["shot_count"] == 2
    assert feature["features"]["storyboard_revision"] == 2
    assert feature["features"]["video_shot_count"] == 2
    assert feature["field_sources"]["style_id"].startswith("/storyboard/")
    assert feature["video_integrity"] == "recorded_binding_and_artifact_hash;not_rehashed"


def test_legacy_task_does_not_gain_invented_features(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    store = Store(tmp_path / "workflow.db")
    dist = Distribution(tmp_path, store)
    aid = dist.add_account("legacy", "qianchuan", "123")["id"]
    jid, _, _ = ready(tmp_path, store, snapshot=False)
    reports = Reporting(tmp_path, store)
    reports.bind(aid, "123", jid, "fixture")
    from ecom_video.review_snapshots import Reviews

    frozen = Reviews(tmp_path, store).create(command(aid, end="2026-10-01"))
    material = frozen["snapshot"]["materials"][0]
    assert material["reported_days"] == 0
    assert material["creative_feature"]["status"] == "unavailable"
    assert all(v is None for v in material["creative_feature"]["features"].values())
    assert "submitted_snapshot_missing" in material["creative_feature"]["missing_reasons"]


def label(feature_id, origin="human", request_id="label-001", value="细节开场"):
    return {
        "request_id": request_id,
        "label_key": "hook_type",
        "value": value,
        "origin": origin,
        "actor": "AUTOMATED FIXTURE 标签记录",
        "evidence_field": "hook_text",
        "confirmed": origin == "human",
        **({"model_name": "fixture-only", "model_version": "v1"} if origin == "model" else {}),
    }


def test_human_and_model_labels_never_overwrite_or_rewrite_old_snapshot(linked):
    from ecom_video.creative_features import Features

    reviews, _, aid, _, _, _ = linked
    old = reviews.create(command(aid, end="2026-10-01"))
    feature = old["snapshot"]["materials"][0]["creative_feature"]
    features = Features(reviews.store)
    features.label(feature["feature_id"], label(feature["feature_id"]))
    features.label(
        feature["feature_id"], label(feature["feature_id"], "model", "label-model", "场景开场")
    )
    fresh = reviews.create(command(aid, "freeze-002", end="2026-10-01"))
    newer = fresh["snapshot"]["materials"][0]["creative_feature"]
    assert newer["labels"]["human"][0]["value"] == "细节开场"
    assert newer["labels"]["model"][0]["value"] == "场景开场"
    assert newer["labels"]["model"][0]["verified"] is False
    assert old["snapshot"]["materials"][0]["creative_feature"]["labels"] == {
        "human": [],
        "model": [],
    }
    assert reviews.get(old["review_id"]) == old


def test_mismatched_artifact_binding_is_explicitly_unavailable(linked):
    reviews, _, aid, jid, _, _ = linked
    with reviews.store.transaction() as c:
        c.execute("UPDATE artifacts SET sha256=? WHERE job_id=?", ("0" * 64, jid))
    frozen = reviews.create(command(aid, end="2026-10-01"))
    material = frozen["snapshot"]["materials"][0]
    assert material["binding_status"] == "video_hash_mismatch"
    assert material["creative_feature"] is None


def test_new_child_video_has_distinct_feature_identity(linked):
    reviews, _, aid, parent, _, _ = linked
    first = reviews.create(command(aid, end="2026-10-01"))
    child, _, _ = ready(reviews.root, reviews.store, style="social")
    with reviews.store.transaction() as c:
        c.execute("UPDATE jobs SET parent_id=? WHERE id=?", (parent, child))
    Reporting(reviews.root, reviews.store).bind(aid, "456", child, "fixture")
    second = reviews.create(command(aid, "child", end="2026-10-01"))
    a, b = second["snapshot"]["materials"]
    assert a["creative_feature"]["feature_id"] != b["creative_feature"]["feature_id"]
    assert b["creative_feature"]["parent_job_id"] == parent
    assert first["snapshot"]["materials"][0]["creative_feature"]["features"]["style_id"] == "cinema"


def test_sparse_submission_keeps_missing_music_unknown(linked):
    from ecom_video.creative_features import extract

    _, _, _, jid, video, snapshot = linked
    snapshot["storyboard"].pop("music_id")
    feature = extract({"id": jid, "parent_id": None, "snapshot": json.dumps(snapshot)}, video)
    assert feature["features"]["music_present"] is None
    assert "music_present" not in feature["field_sources"]
    assert "feature_missing:music_present" in feature["missing_reasons"]
    snapshot["storyboard"]["music_id"] = None
    feature = extract({"id": jid, "parent_id": None, "snapshot": json.dumps(snapshot)}, video)
    assert feature["features"]["music_present"] is False
