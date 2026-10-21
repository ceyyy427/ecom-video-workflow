"""P8 contracts: pending analysis cannot masquerade as semantic matching."""

import pytest
from test_customer import approve, client, picture, project


def test_visual_upload_can_be_queued_cancelled_and_is_project_scoped(tmp_path):
    c = client(tmp_path)
    p = picture(c, project(c))
    mid = p["media"][0]["id"]
    base = f"/api/customer-projects/{p['id']}/assets/{mid}/analysis"
    r = c.post(base, json={})
    assert r.status_code == 202, r.text
    first = r.json()
    assert first["status"] == "queued"
    assert c.post(base, json={}).json()["id"] == first["id"]
    other = project(c, "other")
    assert c.get(f"/api/customer-projects/{other['id']}/assets/{mid}/analysis").status_code == 404
    assert c.delete(base).json()["status"] == "cancelled"
    assert c.post(base, json={}).json()["id"] != first["id"]


def test_auto_selection_cannot_prepare_without_completed_source_analysis(tmp_path):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    settings = {**p["settings"], "auto_select": True}
    base = f"/api/customer-projects/{p['id']}"
    r = c.put(base, json={"revision": p["revision"], "settings": settings})
    assert r.status_code == 200, r.text
    r = c.post(base + "/prepare", json={"revision": r.json()["revision"]})
    assert r.status_code == 409, r.text
    assert "识别" in r.json()["detail"]


@pytest.mark.parametrize("colors", [("red", "blue"), ("0x808080", "0xa0a0a0")])
def test_detected_cuts_bound_candidates_and_blank_frames_are_not_useful(tmp_path, colors):
    import subprocess

    from PIL import Image

    from ecom_video.clip_scan import scan, windows
    from ecom_video.media import inspect_media

    path = tmp_path / "cuts.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colors[0]}:s=160x240:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colors[1]}:s=160x240:r=30:d=3",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(path),
        ],
        check=True,
    )
    result = scan(path, "video", inspect_media(path, "video"), tmp_path / "frames")
    assert any(abs(t - 3) < 0.04 for t in result["cuts"])
    assert len(result["segments"]) == 2
    assert result["segments"][0]["end"] <= 2.9
    assert result["segments"][1]["start"] >= 3.1
    assert len(windows(600, [])) == 8
    for s in result["segments"]:
        assert all((tmp_path / "frames" / f).is_file() for f in s["frames"])
    blank = tmp_path / "black.png"
    Image.new("RGB", (160, 240)).save(blank)
    r = scan(blank, "image", {}, tmp_path / "black-frames")
    assert r["segments"][0]["quality"]["blank"]


def pool():
    return [
        {
            "id": k,
            "kind": kind,
            "asset_id": asset,
            "asset_sha256": asset,
            "start": a,
            "end": b,
            "analysis_id": "analysis",
            "segment_id": k,
            "role": "product",
            "note": "",
            "observation": {"description": "测试输入，非模型实测", "framing": "whole"},
        }
        for k, kind, asset, a, b in [
            ("v1", "video", "video", 0, 6),
            ("v2", "video", "video", 7, 13),
            ("img", "image", "image", 0, 0),
        ]
    ]


def test_selector_prefers_relevant_video_and_avoids_repeating_same_range():
    from ecom_video.clip_matching import allocate

    rankings = [
        {
            "line": i,
            "choices": [
                {"clip_id": k, "score": 3, "reason": "fixture"} for k in ["v1", "v2", "img"]
            ],
        }
        for i in [1, 2]
    ]
    decisions = allocate(["杯身", "杯身"], [4, 4], pool(), rankings, "narrated")
    assert [(d["kind"], d["start"]) for d in decisions] == [("video", 0), ("video", 7)]


def test_selection_never_extends_short_segment_or_uses_weak_unrelated_video():
    import pytest

    from ecom_video.clip_matching import allocate

    ranked = [
        {
            "line": 1,
            "choices": [
                {"clip_id": "v1", "score": 3, "reason": "short"},
                {"clip_id": "img", "score": 2, "reason": "外观相关图片"},
            ],
        }
    ]
    assert allocate(["外观"], [7], pool(), ranked, "narrated")[0]["kind"] == "image"
    ranked[0]["choices"][1]["score"] = 0
    with pytest.raises(ValueError, match="时长足够"):
        allocate(["外观"], [7], pool(), ranked, "narrated")
    ranked[0]["choices"][0]["clip_id"] = "invented"
    with pytest.raises(ValueError, match="未知"):
        allocate(["外观"], [7], pool(), ranked, "narrated")


def test_model_observation_cannot_promote_footage_to_test_evidence():
    import pytest

    from ecom_video.clip_matching import allocate

    ranked = [
        {"line": 1, "choices": [{"clip_id": "v1", "score": 3, "reason": "model says testing"}]}
    ]
    with pytest.raises(ValueError, match="未找到"):
        allocate(["测试"], [3], pool(), ranked, "review")


def test_analysis_worker_finishes_binds_source_and_delete_cancels_public_access(
    tmp_path, monkeypatch
):
    from ecom_video import vision_model
    from ecom_video.analysis_worker import Worker
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = picture(c, project(c))
    mid = p["media"][0]["id"]
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    row = svc.start(p["id"], mid)
    monkeypatch.setattr(
        vision_model,
        "identity",
        lambda: {"model": "fixture", "digest": "fixture", "provider": "test_only"},
    )
    monkeypatch.setattr(
        vision_model,
        "observe",
        lambda images, model: {
            "description": "fixture plain color",
            "subjects": [],
            "actions": [],
            "framing": "unknown",
            "usable": False,
            "uncertainty": "fixture, not real recognition",
        },
    )
    assert Worker(tmp_path).once()
    ready = svc.get(p["id"], mid)
    assert ready["status"] == "ready"
    assert ready["result"]["source_sha256"] == p["media"][0]["sha256"]
    assert ready["result"]["analysis_id"] == row["id"]
    url = f"/api/customer-projects/{p['id']}/assets/{mid}/analysis/{row['id']}/frames/clip-00/0"
    assert c.get(url).status_code == 200
    assert c.get(url.replace("clip-00", "made-up")).status_code == 404
    assert (
        c.request(
            "DELETE",
            f"/api/customer-projects/{p['id']}/assets/{mid}",
            json={"revision": p["revision"]},
        ).status_code
        == 200
    )
    assert c.get(url).status_code == 404
    assert not (tmp_path / "analyses" / row["id"]).exists()
    with svc.store.connect() as db:
        assert not db.execute("select * from media_analyses").fetchall()


def test_failed_inference_and_expired_lease_never_become_ready(tmp_path, monkeypatch):
    from ecom_video import vision_model
    from ecom_video.analysis_worker import Worker
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = picture(c, project(c))
    mid = p["media"][0]["id"]
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    svc.start(p["id"], mid)

    def unavailable():
        raise ValueError("fixture unavailable")

    monkeypatch.setattr(vision_model, "identity", unavailable)
    Worker(tmp_path).once()
    assert svc.get(p["id"], mid)["status"] == "partial"
    assert svc.get(p["id"], mid)["result"]["recognition"] == "unavailable"
    svc.start(p["id"], mid)
    row = svc.claim()
    with svc.store.transaction() as db:
        db.execute("update media_analyses set lease_until=0 where id=?", (row["id"],))
    assert svc.claim() is None
    assert svc.get(p["id"], mid)["status"] == "failed"
    assert svc.get(p["id"], mid)["result"] is None


def test_ready_analysis_is_frozen_and_later_retry_invalidates_preparation(tmp_path, monkeypatch):
    from test_customer import prepare

    from ecom_video import vision_model
    from ecom_video.analysis_worker import Worker
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    mid = p["media"][0]["id"]
    base = f"/api/customer-projects/{p['id']}"
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    svc.start(p["id"], mid)
    monkeypatch.setattr(
        vision_model,
        "identity",
        lambda: {"model": "fixture", "digest": "fixture", "provider": "test_only"},
    )
    monkeypatch.setattr(
        vision_model,
        "observe",
        lambda images, model: {
            "description": "fixture",
            "subjects": [],
            "actions": [],
            "framing": "whole",
            "usable": True,
            "uncertainty": "test only",
        },
    )
    Worker(tmp_path).once()
    p = c.get(base).json()
    p = c.put(
        base, json={"revision": p["revision"], "settings": {**p["settings"], "auto_select": True}}
    ).json()
    p = prepare(c, p)
    assert (
        p["job"]["assets"][0]["metadata"]["content_analysis"]["analysis_id"]
        == p["media"][0]["analysis"]["id"]
    )
    with svc.store.transaction() as db:
        db.execute("update media_analyses set status='failed' where media_id=?", (mid,))
    assert c.get(base).json()["inputs_changed"]
    assert c.post("/api/jobs/" + p["job"]["id"] + "/submit").status_code == 409


def test_semantic_framing_preserves_explicit_human_role(tmp_path, monkeypatch):
    from test_customer import prepare

    from ecom_video import clip_matching
    from ecom_video.customer_planner import plan_board

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c), "detail")))
    asset = p["job"]["assets"][0]
    monkeypatch.setattr(
        clip_matching,
        "select",
        lambda job, durations, mode: (
            [
                {
                    "asset_id": asset["id"],
                    "start": 0,
                    "observation": {"framing": "whole"},
                    "score": 3,
                    "reason": "fixture",
                    "reused": False,
                    "grounding": {"matched": []},
                }
                for _ in durations
            ],
            {"model": "fixture", "digest": "fixture"},
        ),
    )
    board, _ = plan_board(p["job"], {**p["settings"], "auto_select": True}, "lab")
    assert all(s["role"] == "detail" for s in board["shots"])


def test_cancel_during_recognition_cannot_publish_and_cleans_frames(tmp_path, monkeypatch):
    from ecom_video import vision_model
    from ecom_video.analysis_worker import Worker
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = picture(c, project(c))
    mid = p["media"][0]["id"]
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    row = svc.start(p["id"], mid)
    monkeypatch.setattr(vision_model, "identity", lambda: {"model": "fixture", "digest": "fixture"})

    def cancelled(images, model):
        svc.cancel(p["id"], mid)
        return {
            "description": "fixture",
            "subjects": [],
            "actions": [],
            "framing": "whole",
            "usable": True,
            "uncertainty": "test only",
        }

    monkeypatch.setattr(vision_model, "observe", cancelled)
    Worker(tmp_path).once()
    assert svc.get(p["id"], mid)["status"] == "cancelled"
    assert svc.get(p["id"], mid)["result"] is None
    assert not (tmp_path / "analyses" / row["id"]).exists()


def test_rank_rejects_invented_ids_and_duplicate_lines(monkeypatch):
    import pytest

    from ecom_video import clip_matching

    candidate = pool()[0]
    candidate["observation"].update(subjects=[], actions=[], uncertainty="fixture")
    rows = [{"line": 1, "choices": [{"clip_id": "invented", "score": 3, "reason": "fixture"}]}]
    monkeypatch.setattr(clip_matching, "generate", lambda *a, **kw: {"lines": rows})
    with pytest.raises(ValueError, match="未知"):
        clip_matching.rank(["杯身"], [candidate], {"model": "fixture"})
    rows[:] = [rows[0], rows[0]]
    with pytest.raises(ValueError, match="漏句或重复"):
        clip_matching.rank(["杯身", "杯盖"], [candidate], {"model": "fixture"})


def test_reuses_unused_time_inside_long_take_before_falling_back_to_still():
    from ecom_video.clip_matching import allocate

    clips = pool()
    clips[0]["end"] = 12
    rows = [
        {
            "line": i,
            "choices": [
                {"clip_id": "v1", "score": 3, "reason": "same suitable long take"},
                {"clip_id": "img", "score": 2, "reason": "still fallback"},
            ],
        }
        for i in [1, 2, 3]
    ]
    decisions = allocate(["杯身"] * 3, [3] * 3, clips, rows, "narrated")
    assert [d["start"] for d in decisions] == [0, 3, 6]
    assert all(d["kind"] == "video" and not d["reused"] for d in decisions)


def test_planner_quantizes_duration_before_semantic_allocation(tmp_path, monkeypatch):
    from test_customer import prepare

    from ecom_video import clip_matching
    from ecom_video.customer_planner import plan_board

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    job = p["job"]
    job["script"] = "一二三四五六七八九十一二三\n一二三四五六七八九十一二三"
    seen = []

    def choose(job, durations, mode):
        seen.extend(durations)
        return (
            [
                {
                    "asset_id": job["assets"][0]["id"],
                    "start": 0,
                    "observation": {"framing": "whole"},
                    "score": 3,
                    "reason": "fixture",
                    "reused": False,
                    "grounding": {"matched": []},
                }
                for _ in durations
            ],
            {"model": "fixture", "digest": "fixture"},
        )

    monkeypatch.setattr(clip_matching, "select", choose)
    board, _ = plan_board(job, {**p["settings"], "auto_select": True}, "lab")
    assert seen == [98 / 30, 98 / 30]
    assert seen == [s["duration"] for s in board["shots"]]


def test_partial_retry_racing_manual_prepare_cannot_save_deleted_evidence(tmp_path, monkeypatch):
    from ecom_video import vision_model
    from ecom_video.analysis_worker import Worker
    from ecom_video.customer import Customers
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    mid = p["media"][0]["id"]
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    old = svc.start(p["id"], mid)

    def unavailable():
        raise ValueError("fixture unavailable")

    monkeypatch.setattr(vision_model, "identity", unavailable)
    Worker(tmp_path).once()
    assert svc.get(p["id"], mid)["status"] == "partial"
    copy = Customers.copy_assets

    def concurrent_copy(self, jid, assets, library=False):
        result = copy(self, jid, assets, library)
        if library:
            svc.start(p["id"], mid)
        return result

    monkeypatch.setattr(Customers, "copy_assets", concurrent_copy)
    r = c.post(f"/api/customer-projects/{p['id']}/prepare", json={"revision": p["revision"]})
    assert r.status_code == 409, r.text
    assert not (tmp_path / "analyses" / old["id"]).exists()
    with svc.store.connect() as db:
        assert not db.execute("select * from customer_jobs").fetchall()


def test_rank_bounds_response_and_preserves_global_line_numbers(monkeypatch):
    import json

    from ecom_video import clip_matching

    candidate = pool()[0]
    candidate["observation"].update(subjects=[], actions=[], uncertainty="fixture")
    calls = []

    def bounded_model(prompt, schema, **kwargs):
        script = json.loads(prompt.split("\n", 1)[1])["script"]
        # A constrained small local model cannot fit a long multi-line response.
        if len(script) > 1:
            raise ValueError("模型输出被截断")
        assert schema["properties"]["lines"]["minItems"] == len(script)
        assert schema["properties"]["lines"]["maxItems"] == len(script)
        calls.append([s["line"] for s in script])
        return {
            "lines": [
                {
                    "line": s["line"],
                    "choices": [{"clip_id": candidate["id"], "score": 2, "reason": "fixture"}],
                }
                for s in script
            ]
        }

    monkeypatch.setattr(clip_matching, "generate", bounded_model)
    rows = clip_matching.rank(["a", "b", "c", "d", "e"], [candidate], {"model": "fixture"})
    assert [r["line"] for r in rows] == [1, 2, 3, 4, 5]
    assert calls == [[1], [2], [3], [4], [5]]
