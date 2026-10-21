"""Catch unsupported claims, silent automatic approvals and unsafe material substitutions."""

import copy

import pytest
from test_customer import approve, client, picture, project

from ecom_video.generation import validate_scenes


def facts():
    return [
        {"id": "color", "text": "黑色头戴耳机。"},
        {"id": "action", "text": "把两侧耳罩向内转动，看看收起后的样子。"},
        {"id": "detail", "text": "弧形头梁连接两侧耳罩。"},
    ]


def test_directed_script_changes_structure_without_manufacturing_claims():
    from ecom_video.generation import compose_directed

    before = copy.deepcopy(facts())
    a = compose_directed(
        before, {"format": "recommendation", "audience": "学生通勤", "tone": "亲切"}
    )
    b = compose_directed(before, {"format": "showcase", "audience": "办公人群", "tone": "克制"})
    assert a != b
    assert a[0]["intent"] == "hook" and a[-1]["intent"] == "closing"
    assert any(s["intent"] == "action" for s in a)
    assert {i for s in a for i in s["fact_ids"]} <= {"color", "action", "detail"}
    assert all(s["text"] in [f["text"] for f in before] for s in a if s["fact_ids"])
    assert before == facts()
    assert validate_scenes(a, facts()) == a
    assert a[0]["brief"]["audience"] == "学生通勤"


def test_directed_script_review_is_observation_not_fake_measurement():
    from ecom_video.generation import compose_directed

    rows = compose_directed(facts(), {"format": "review", "tone": "年轻"})
    text = "\n".join(s["text"] for s in rows)
    assert "实拍依据" in text and "测试证明" not in text and "降噪" not in text
    with pytest.raises(ValueError):
        validate_scenes([{"text": "降噪效果翻倍", "fact_ids": []}], facts())


def test_directed_api_preserves_pending_draft_and_source_context(tmp_path):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    prod = p["product"]
    original = copy.deepcopy(prod["script_drafts"])
    r = c.post(
        f"/api/products/{p['id']}/scripts/generate",
        json={
            "revision": prod["revision"],
            "mode": "directed",
            "brief": {"format": "recommendation", "audience": "办公室", "tone": "温暖"},
        },
    )
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["status"] == "script_draft"
    assert len(new["script_approvals"]) == len(prod["script_approvals"])
    assert all(d in new["script_drafts"] for d in original)
    draft = next(d for d in new["script_drafts"] if d["id"] == new["current_draft_id"])
    assert draft["payload"][0]["brief"]["tone"] == "温暖"
    assert (
        c.post(
            f"/api/products/{p['id']}/scripts/generate",
            json={
                "revision": prod["revision"],
                "mode": "directed",
            },
        ).status_code
        == 409
    )


def asset(kind="video", actions=(), description="黑色耳机", sha="a" * 64):
    return {
        "id": "v1",
        "name": "耳机.mp4",
        "kind": kind,
        "sha256": sha,
        "metadata": {
            "duration": 12,
            "source_in": 0,
            "content_analysis": {
                "source_sha256": sha,
                "analysis_id": "scan1",
                "segments": [
                    {
                        "id": "s1",
                        "start": 0,
                        "end": 10,
                        "quality": {"blank": False},
                        "observation": {
                            "usable": True,
                            "subjects": [description],
                            "description": description,
                            "actions": list(actions),
                            "framing": "whole",
                            "uncertainty": "",
                        },
                    }
                ],
            },
        },
    }


def test_preflight_does_not_substitute_static_capability_for_fold_action():
    from ecom_video.readiness import check_materials

    lines = ["把两侧耳罩向内转动，看看收起后的样子。"]
    a = asset(description="可折叠黑色耳机，耳罩圆润")
    r = check_materials(lines, [a], durations=[4])
    assert r["lines"][0]["status"] == "gap"
    assert r["lines"][0]["code"] == "action_not_observed"
    a["metadata"]["content_analysis"]["segments"][0]["observation"]["actions"] = [
        "双手向内转动耳罩"
    ]
    r = check_materials(lines, [a], durations=[4])
    assert r["lines"][0]["status"] == "suggestion"
    assert r["lines"][0]["candidates"][0]["source_in"] == 0
    assert r["human_review_required"]


def test_preflight_marks_unknown_stale_analysis_wrong_product_and_short_video():
    from ecom_video.readiness import check_materials

    line = ["黑色头戴耳机。"]
    a = asset()
    a["metadata"]["content_analysis"]["source_sha256"] = "b" * 64
    assert check_materials(line, [a])["lines"][0]["status"] == "unknown"
    assert check_materials(line, [asset(description="绿色植物")])["lines"][0]["status"] == "gap"
    assert check_materials(line, [asset()], durations=[14])["lines"][0]["code"] == "duration_short"
    assert check_materials(["正在倒水"], [asset(kind="image")])["lines"][0]["status"] == "gap"


def test_preflight_endpoint_is_read_only_and_does_not_need_style_or_voice(tmp_path):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    before = c.get(base).json()
    r = c.get(base + "/preflight")
    assert r.status_code == 200, r.text
    assert r.json()["human_review_required"] and r.json()["lines"]
    assert c.get(base).json() == before
    assert c.get(base + "/preflight").json()["fingerprint"] == r.json()["fingerprint"]


def test_preflight_uses_current_board_timing_and_never_an_old_script_board(tmp_path):
    from test_customer import plan, prepare

    from ecom_video.readiness import project_preflight

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    p["job"]["storyboard"]["shots"][0]["duration"] = 7
    r = project_preflight(p)
    assert r["lines"][0]["duration"] == 7
    assert r["lines"][0]["duration_basis"] == "measured"
    p["inputs_changed"] = True
    r = project_preflight(p)
    assert r["lines"][0]["duration_basis"] == "estimated"


@pytest.mark.parametrize(
    "line", ["不要倒水。", "请勿开盖。", "不必戴上耳机。", "无需把耳罩向内转动。"]
)
def test_preflight_does_not_request_actions_that_script_explicitly_negates(line):
    from ecom_video.readiness import required_action

    assert required_action(line) is None


def test_product_image_is_a_valid_editorial_outro_not_an_action_video():
    from ecom_video.readiness import check_materials

    r = check_materials(
        ["黑色耳机", "外观看清之后，再核对参数和自己的使用需要。"], [asset(kind="image")]
    )
    assert r["lines"][-1]["status"] == "suggestion"
    assert check_materials(["正在倒水"], [asset(kind="image")])["lines"][0]["status"] == "gap"


def test_all_affirmative_actions_in_a_sentence_require_evidence():
    from ecom_video.readiness import check_materials

    a = asset(actions=["双手开盖"], description="水杯与杯盖，杯中是倒水后的状态")
    r = check_materials(["先开盖，再倒水。"], [a], [3])
    assert r["lines"][0]["status"] == "gap"
    assert set(r["lines"][0]["required_actions"]) == {"open_lid", "pour"}


def test_generic_hook_cannot_recommend_wrong_product_and_unknown_category_stays_unknown():
    from ecom_video.readiness import check_materials

    r = check_materials(["看看整体外观。", "黑色头戴耳机。"], [asset(description="绿色植物放在桌面")])
    assert r["lines"][0]["status"] == "gap"
    r = check_materials(["看看这款收纳配件。"], [asset(description="绿色植物放在桌面")])
    assert r["lines"][0]["status"] == "unknown"


def test_part_closeup_need_not_repeat_product_name_and_environment_cannot_prove_unknown_product():
    from ecom_video.readiness import check_materials

    detail = asset(description="弧形头梁连接两侧耳罩")
    detail["id"] = "detail"
    r = check_materials(["黑色耳机。", "弧形头梁连接两侧耳罩。"], [asset(), detail])
    assert r["lines"][1]["status"] == "suggestion"
    assert r["lines"][1]["candidates"][0]["asset_id"] == "detail"
    r = check_materials(["这款收纳配件放在桌面。"], [asset(description="绿色植物放在桌面")])
    assert r["lines"][0]["status"] == "unknown"
