import copy

import pytest

from ecom_video.storyboard import default_board, validate_board


def setup_board():
    assets = [
        {
            "id": name,
            "kind": "video",
            "name": name + ".mp4",
            "sha256": name * 64,
            "metadata": {
                "duration": 10,
                "identity": {
                    "sku": "山甲LT",
                    "color": "藏蓝",
                    "reviewer": "AUTOMATED FIXTURE",
                    "source_sha256": name * 64,
                },
            },
        }
        for name in ("a", "b")
    ]
    job = {"script": "袖口贴手腕，下摆想收紧，拉一下就行。", "seconds": 5, "assets": assets}
    board = default_board(job)
    board["delivery"] = {
        "version": 1,
        "caption_policy": "pause-v1",
        "identity_lock": {"sku": "山甲LT", "color": "藏蓝"},
    }
    board["shots"][0].update(
        duration=5,
        source_cuts=[
            {
                "asset_id": "a",
                "source_in": 0,
                "source_duration": 3,
                "duration": 3,
                "reason": "袖口外观，不宣称袖口可调",
            },
            {
                "asset_id": "b",
                "source_in": 1,
                "source_duration": 2,
                "duration": 2,
                "reason": "下摆抽绳",
                "complete_action": {"name": "抽绳", "start": 1, "end": 3},
            },
        ],
    )
    return job, board


def test_same_colour_source_cuts_preserve_complete_action():
    job, board = setup_board()
    saved = validate_board(job, board)
    assert len(saved["shots"][0]["source_cuts"]) == 2
    assert saved["shots"][0]["motion_plan"]["protect_action"] is True
    assert any(
        w["start"] == 3 and w["end"] == 5 for w in saved["shots"][0]["motion_plan"]["windows"]
    )


def test_primary_source_in_cannot_silently_override_explicit_cut():
    job, board = setup_board()
    board["shots"][0]["source_in"] = 4
    with pytest.raises(ValueError, match="分段.*入点"):
        validate_board(job, board)


def test_single_shot_revision_checks_normalized_complete_action_boundaries(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    job = p["job"]
    # This synthetic metadata fixture exercises versioning, not media/identity accuracy.
    with c.app.state.store.transaction() as db:
        import json

        for a in job["assets"]:
            db.execute(
                "UPDATE assets SET kind='video',metadata=? WHERE id=?",
                (json.dumps({"duration": 10}), a["id"]),
            )
    job = c.get(f"/api/jobs/{job['id']}").json()
    board = copy.deepcopy(job["storyboard"])
    from ecom_video.creative import rebase_fingerprint

    board["creative"]["fingerprint"] = rebase_fingerprint(p["job"], job, board["creative"])
    board["delivery"] = {"version": 1, "caption_policy": "pause-v1"}
    for s in board["shots"]:
        s.update(
            motion="static",
            source_in=0,
            source_cuts=[
                {
                    "asset_id": s["asset_id"],
                    "source_in": 0,
                    "source_duration": s["duration"],
                    "duration": s["duration"],
                }
            ],
        )
        s["transition"] = "wipe"
        s["motion_plan"]["windows"] = []
    saved = c.put(
        f"/api/jobs/{job['id']}/storyboard",
        json={"revision": job["storyboard_revision"], "board": board},
    )
    assert saved.status_code == 200, saved.text
    p = c.get(f"/api/customer-projects/{p['id']}").json()
    # A legacy project that explicitly opts its board in must also confirm both stages.
    from test_delivery_reviews import confirm

    style = board["creative"]["style_id"]
    p = confirm(c, p, "direction", style)
    p = confirm(c, p, "storyboard", style)
    payload = lock_and_revision(c, p)
    s = p["job"]["storyboard"]["shots"][0]
    cuts = copy.deepcopy(s["source_cuts"])
    cuts[0]["complete_action"] = {"name": "完整动作", "start": 0, "end": s["duration"]}
    payload.update(shot_id=s["shot_id"], changes={"source_cuts": cuts})
    result = c.post(f"/api/customer-projects/{p['id']}/revise-shot", json=payload)
    assert result.status_code == 422 and "相邻转场" in result.text, result.text


@pytest.mark.parametrize("problem", ["other_color", "unknown", "changed_file"])
def test_colour_lock_rejects_mismatch_unknown_and_stale_declaration(problem):
    job, board = setup_board()
    identity = job["assets"][1]["metadata"]["identity"]
    if problem == "other_color":
        identity["color"] = "浅蓝"
    elif problem == "unknown":
        job["assets"][1]["metadata"].pop("identity")
    else:
        job["assets"][1]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="款式|配色|身份"):
        validate_board(job, board)


@pytest.mark.parametrize("problem", ["incomplete", "speed", "unowned", "coverage"])
def test_source_cut_safety_cannot_be_bypassed(problem):
    job, board = setup_board()
    cuts = board["shots"][0]["source_cuts"]
    if problem == "incomplete":
        cuts[1]["complete_action"]["end"] = 3.5
    elif problem == "speed":
        cuts[1]["source_duration"] = 2.4
    elif problem == "unowned":
        cuts[1]["asset_id"] = "outside"
    else:
        cuts[0]["duration"] = 2.5
    with pytest.raises(ValueError):
        validate_board(job, board)


def test_legacy_board_needs_no_identity_or_new_consent():
    job, board = setup_board()
    board.pop("delivery")
    board["shots"][0].pop("source_cuts")
    for a in job["assets"]:
        a["metadata"].pop("identity")
    original = copy.deepcopy(board)
    assert validate_board(job, board)["shots"][0]["source_in"] == original["shots"][0]["source_in"]


def test_secondary_cut_asset_cannot_be_removed_from_draft(tmp_path):
    from ecom_video.db import Conflict, Store

    store = Store(tmp_path / "workflow.db")
    source, board = setup_board()
    job = store.create_job("分段实拍", source["script"], 5)
    for asset in source["assets"]:
        store.add_asset(job["id"], {**asset, "path": asset["name"], "size": 1})
    store.save_storyboard(job["id"], board, 0)
    with pytest.raises(Conflict, match="分镜"):
        store.remove_asset(job["id"], "b")
