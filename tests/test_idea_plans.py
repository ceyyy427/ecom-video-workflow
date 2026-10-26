import copy

import pytest


def brief(**changes):
    from ecom_video.content_plan import ContentBrief

    return ContentBrief(
        idea="让大家看清藏蓝外套的口袋和下摆",
        subject="藏蓝软壳衣",
        audience="通勤人群",
        tone="自然、有节奏",
        facts=[
            {"text": "藏蓝配色，拉链口袋", "source": "上传资料第1段"},
            {"text": "下摆有抽绳", "source": "实拍中可见，待人工核对"},
        ],
        **changes,
    )


def test_six_executable_options_share_facts_but_have_different_scene_strategies():
    from ecom_video.content_plan import build_plan

    p = build_plan(brief(), [])
    assert len(p["options"]) == len({o["id"] for o in p["options"]}) == 6
    assert p["approvals"] == [] and p["preview_seconds"] == 7
    assert len({o["native_style"] for o in p["options"]}) == 6
    assert len({tuple(s["recipe"] for s in o["scenes"]) for o in p["options"]}) == 6
    for option in p["options"]:
        assert len(option["scenes"]) == 4
        assert sum(s["seconds"] for s in option["scenes"]) == 24
        assert all(len(s["text"]) <= 100 and s["claim_ids"] for s in option["scenes"])
        assert len(option["source"]["commit"]) == 40
        assert "127" not in option["script"] and "100%" not in option["script"]
    assert p["materials"] == [] and any("图示" in m for m in p["missing"])


def test_audience_tone_source_and_topic_change_the_frozen_plan():
    from ecom_video.content_plan import build_plan

    a = brief()
    p = build_plan(a, [])
    for key, value in [
        ("audience", "小学生"),
        ("tone", "安静、克制"),
        ("idea", "解释桥梁怎样承重"),
    ]:
        b = a.model_copy(update={key: value})
        q = build_plan(b, [])
        assert p["basis"] != q["basis"]
        assert p["options"] != q["options"]
    assert build_plan(a, [])["basis"] == p["basis"]
    material = {
        "id": "a",
        "sha256": "a" * 64,
        "kind": "image",
        "path": "x.png",
        "metadata": {},
        "source_in": 0,
    }
    assert build_plan(a, [material])["basis"] != p["basis"]
    before = copy.deepcopy(material)
    build_plan(a, [material])
    assert material == before


def test_no_data_never_creates_numbers_and_unsupported_reference_is_explicit():
    from ecom_video.content_plan import ContentBrief, build_plan

    p = build_plan(ContentBrief(idea="解释一个想法"), [])
    assert p["data"] == []
    assert all(not s.get("data") for o in p["options"] for s in o["scenes"])
    with pytest.raises(ValueError, match="可执行"):
        build_plan(ContentBrief(idea="解释一个想法", preferred="pixel-rpg"), [])


def test_plan_queue_survives_restart_cancels_and_recovers_expired_runs(tmp_path):
    from ecom_video.db import Conflict, Store
    from ecom_video.idea_plans import IdeaPlans

    store = Store(tmp_path / "workflow.db")
    old = store.create_job("旧稿", "原来的文稿")
    svc = IdeaPlans(tmp_path, store)
    p = svc.create(brief(), [])
    assert svc.create(brief(), [])["id"] == p["id"]
    assert svc.enqueue(p["id"], p["basis"])["status"] == "queued"
    claimed = svc.claim()
    assert claimed["status"] == "rendering"
    with pytest.raises(Conflict):
        svc.enqueue(p["id"], "0" * 64)
    svc.cancel(p["id"])
    with pytest.raises(Conflict):
        svc.check(p["id"], claimed["lease_token"])
    assert svc.enqueue(p["id"], p["basis"])["status"] == "queued"
    svc.claim()
    with store.transaction() as c:
        c.execute("UPDATE idea_plans SET updated_at=0 WHERE id=?", (p["id"],))
    restarted = IdeaPlans(tmp_path, Store(tmp_path / "workflow.db"))
    assert restarted.claim() is None
    assert restarted.get(p["id"])["status"] == "failed"
    assert store.get(old["id"])["script"] == "原来的文稿" and store.get(old["id"])["reviews"] == []
    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 15
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
