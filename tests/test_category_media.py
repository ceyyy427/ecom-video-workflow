import subprocess

import pytest

from ecom_video.clip_scan import windows


def test_resumed_manual_selection_mode_is_bound_to_parent_not_cli_flags(tmp_path):
    import json

    from ecom_video.creative import signature
    from scripts.accept_categories import selection_mode

    parent = {
        "id": "parent",
        "storyboard_revision": 2,
        "storyboard": {"creative": {"review_context": "人工查看后校正"}},
    }
    with pytest.raises(ValueError, match="缺失"):
        selection_mode(tmp_path, parent)
    record = {
        "job_id": "parent",
        "board_revision": 2,
        "board_sha256": signature(parent["storyboard"]),
    }
    (tmp_path / "manual-selection.json").write_text(json.dumps(record))
    assert selection_mode(tmp_path, parent) == "manual_after_local_proposals"
    for tampered in [
        {**parent, "id": "another"},
        {**parent, "storyboard_revision": 3},
        {**parent, "storyboard": {"creative": {"review_context": "changed"}}},
    ]:
        with pytest.raises(ValueError, match="父版不符"):
            selection_mode(tmp_path, tampered)


@pytest.mark.parametrize("duration", [45, 90, 300, 600])
def test_bounded_sampling_preserves_long_and_short_candidates(duration):
    spans = windows(duration, [])
    assert len(spans) == 8
    assert any(s["end"] - s["start"] >= 14 for s in spans)
    assert any(s["end"] - s["start"] <= 8 for s in spans)
    assert max(s["end"] for s in spans) == duration


def test_continuous_takes_have_short_action_views_and_keep_long_shot_support():
    spans = windows(22, [])
    assert len(spans) <= 8
    assert any(s["end"] - s["start"] <= 8 and s["start"] <= 7.5 <= s["end"] for s in spans)
    assert any(s["end"] - s["start"] >= 14 for s in spans)
    assert any(5 <= s["start"] <= 7 for s in spans)


def test_explicit_refresh_keeps_ready_evidence_and_is_idempotent_while_running(tmp_path):
    from test_customer import client, picture, project

    c = client(tmp_path)
    p = picture(c, project(c))
    mid = p["media"][0]["id"]
    endpoint = f"/api/customer-projects/{p['id']}/assets/{mid}/analysis"
    first = c.post(endpoint, json={}).json()
    from ecom_video.db import Store

    with Store(tmp_path / "workflow.db").transaction() as db:
        db.execute(
            "update media_analyses set status='ready',result=? where id=?",
            ('{"segments":[],"context":{}}', first["id"]),
        )
    assert c.post(endpoint, json={}).json()["id"] == first["id"]
    fresh = c.post(endpoint, json={"refresh": True})
    assert fresh.status_code == 202
    assert fresh.json()["id"] != first["id"]
    assert c.post(endpoint, json={"refresh": True}).json()["id"] == fresh.json()["id"]
    with Store(tmp_path / "workflow.db").connect() as db:
        assert (
            db.execute("select status from media_analyses where id=?", (first["id"],)).fetchone()[0]
            == "ready"
        )


def test_real_wide_video_normalization_is_even_sized_and_frame_exact(tmp_path):
    from ecom_video import remotion_renderer as renderer
    from ecom_video.media import probe

    source = tmp_path / "wide.mp4"
    target = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=190x104:r=30:d=0.4",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    renderer.prepare_source_video(source, target, {"source_in": 0, "frames": 9}, lambda: None)
    stream = next(s for s in probe(target)["streams"] if s["codec_type"] == "video")
    assert int(stream["width"]) % 2 == int(stream["height"]) % 2 == 0
    assert int(stream["nb_frames"]) == 9
