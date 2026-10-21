import copy

from ecom_video.creative import Brief, recommend
from ecom_video.production_direction import choreography_for, direction_for, footage_priority


def test_recommendations_describe_one_joint_footage_motion_voice_direction():
    job = {
        "title": "黑色耳机",
        "script": "先看耳罩和头梁。",
        "assets": [{"kind": "video", "sha256": "a"}],
    }
    rec = recommend(
        job, Brief(format="narrated", category="数码耳机", audience="年轻学生", tone="活泼节奏")
    )
    assert len(rec["options"]) == 3
    for option in rec["options"]:
        p = option["production"]
        assert p["version"] == "narrative-v1"
        assert p["voice"] == option["voice"]
        assert p["footage"] and p["rhythm"] and p["structure"]
    assert direction_for("cinema") != direction_for("social") != direction_for("lab")


def test_joint_choreography_uses_semantic_chapters_not_second_shot_as_default():
    lines = ["先看这副耳机。", "耳罩向内折叠。", "再看头梁的外观。", "最后看整体。"]
    social = choreography_for(lines, "social", [4] * 4, repeat_limit=2)
    assert social[0]["shot_recipe"] == "crash-zoom-punch"
    assert social[1]["shot_recipe"] == "none" and social[1]["motion_plan"]["intent"] == "action"
    assert social[1]["transition"] == "cut"
    assert social[2]["transition"] == "push-stack"
    assert choreography_for(lines, "lab", [4] * 4)[2]["shot_recipe"] == "scanline-annotate-focus"
    assert choreography_for(lines, "cinema", [4] * 4)[0]["motion_plan"]["strength"] == "subtle"


def test_direction_priority_is_bounded_uses_observed_framing_and_never_mutates_data():
    candidate = {"kind": "video", "observation": {"framing": "context", "actions": []}}
    before = copy.deepcopy(candidate)
    assert footage_priority(candidate, "social", "看看这副耳机。", 1, 4) > footage_priority(
        candidate, "lab", "看看这副耳机。", 1, 4
    )
    assert footage_priority(candidate, "social", "看看耳罩细节。", 1, 4) == footage_priority(
        candidate, "lab", "看看耳罩细节。", 1, 4
    )
    assert candidate == before


def test_generic_three_directions_and_frozen_board_keep_explicit_opt_in(tmp_path):
    from test_customer import approve, client, picture, plan, prepare, project

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    assert all(s["production"]["voice"] == s["voice"] for s in p["recommendations"]["options"])
    result = plan(c, p)
    assert result["job"]["storyboard"]["creative"]["production"] == "narrative-v1"
    assert any("未开启" in n for n in result["planning_notes"])


def test_allocate_direction_changes_equal_candidates_but_cannot_override_relevance_or_wrong_product():
    from test_clip_grounding import clip, ranking

    from ecom_video.clip_matching import allocate

    whole, context = clip("whole", "黑色耳机"), clip("context", "黑色耳机")
    whole["observation"]["framing"] = "whole"
    context["observation"]["framing"] = "context"
    pool = [whole, context]
    lines = ["看看耳机。"] * 3
    rows = [ranking(i + 1, whole=2, context=2) for i in range(3)]
    constraints = {"direction": {"version": "narrative-v1", "style_id": "social"}}
    picked = allocate(lines, [2] * 3, pool, rows, "narrated", constraints)
    assert picked[1]["id"] == "context"
    rows[1] = ranking(2, whole=3, context=2)
    assert allocate(lines, [2] * 3, pool, rows, "narrated", constraints)[1]["id"] == "whole"
    wrong = clip("wrong", "白色杯子放在桌上")
    wrong["observation"]["framing"] = "context"
    assert (
        allocate(
            ["耳机外观"],
            [2],
            [wrong, whole],
            [ranking(1, wrong=3, whole=2)],
            "narrated",
            constraints,
        )[0]["id"]
        == "whole"
    )


def test_style_constraint_does_not_require_a_product_reference_for_plain_auto_select(
    tmp_path, monkeypatch
):
    import pytest
    from test_customer import approve, client, picture, prepare, project

    from ecom_video.customer_planner import plan_board

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))

    def select(job, durations, mode):
        assert job["matching_constraints"]["direction"] == {
            "version": "narrative-v1",
            "style_id": "cinema",
        }
        assert not job["matching_constraints"]["strict_product"]
        raise RuntimeError("reached semantic selector without a reference")

    monkeypatch.setattr("ecom_video.clip_matching.select", select)
    with pytest.raises(RuntimeError, match="reached semantic selector"):
        plan_board(p["job"], {**p["settings"], "auto_select": True}, "cinema")


def test_product_independent_direction_names_do_not_keep_cup_demo_title():
    job = {
        "title": "黑色耳机",
        "script": "耳机的外观。",
        "assets": [{"kind": "video", "sha256": "a"}],
    }
    rec = recommend(
        job,
        Brief(
            format="narrated", category="数码耳机", audience="通勤人群", tone="亲切生活分享，温暖"
        ),
    )
    social = next(s for s in rec["options"] if s["id"] == "social")
    assert social["name"] == "生活种草"


def test_fold_capability_or_image_cannot_replace_folding_action_in_new_production():
    import pytest
    from test_clip_grounding import clip, ranking

    from ecom_video.clip_matching import allocate

    c = clip("capability", "黑色耳机，耳罩可折叠，被双手托举。")
    line = "把两侧耳罩向内转动，看看收起后的样子。"
    direction = {"direction": {"version": "narrative-v1", "style_id": "social"}}
    with pytest.raises(ValueError, match="动作"):
        allocate([line], [3], [c], [ranking(1, capability=3)], "narrated", direction)
    c["observation"]["actions"] = ["双手向内转动耳罩并折叠"]
    assert (
        allocate([line], [3], [c], [ranking(1, capability=3)], "narrated", direction)[0]["id"]
        == "capability"
    )
    c["kind"] = "image"
    with pytest.raises(ValueError, match="动作"):
        allocate([line], [3], [c], [ranking(1, capability=3)], "narrated", direction)
    c["kind"] = "video"
    c["observation"]["actions"] = ["没有折叠动作"]
    with pytest.raises(ValueError, match="动作"):
        allocate([line], [3], [c], [ranking(1, capability=3)], "narrated", direction)


def test_final_reminder_is_explained_to_model_without_changing_facts_or_scores(monkeypatch):
    import json

    from test_clip_grounding import clip

    from ecom_video import clip_matching

    def generate(prompt, schema, **kwargs):
        payload = json.loads(prompt.split("\n", 1)[1])
        assert payload["script"][0]["presentation"] == "收尾提醒，非事实证明或核对动作"
        assert "不自动加分" in prompt
        return {
            "lines": [{"line": 1, "choices": [{"clip_id": "a", "score": 0, "reason": "仍不相关"}]}]
        }

    monkeypatch.setattr(clip_matching, "generate", generate)
    rows = clip_matching.rank(
        ["外观看清之后，再核对参数和自己的使用需要。"],
        [clip("a", "黑色耳机")],
        {"model": "fixture"},
    )
    assert rows[0]["choices"][0]["score"] == 0


def test_closing_reminder_cannot_hide_a_specification_or_performance_claim():
    from ecom_video.production_direction import closing_reminder

    assert not closing_reminder("再核对参数，这款耳机支持降噪40分贝。", 0, 1)
    assert not closing_reminder("再核对说明，保证长续航。", 0, 1)


def test_outro_can_use_explicit_local_product_hold_without_rewriting_model_score():
    from copy import deepcopy

    import pytest
    from test_clip_grounding import clip, ranking

    from ecom_video.clip_matching import allocate

    lines = ["看看耳机外观。", "外观看清之后，再核对参数和自己的使用需要。"]
    pool = [clip("a", "黑色耳机"), clip("wrong", "白色杯子")]
    pool[0]["observation"]["framing"] = "whole"
    rows = [ranking(1, a=3), ranking(2, a=0, wrong=0)]
    before = deepcopy(rows)
    chosen = allocate(
        lines,
        [2, 2],
        pool,
        rows,
        "narrated",
        {"direction": {"version": "narrative-v1", "style_id": "social"}},
    )
    assert chosen[-1]["id"] == "a" and chosen[-1]["model_score"] == 0
    assert chosen[-1]["ranking_method"] == "local_product_outro"
    assert rows == before
    with pytest.raises(ValueError):
        allocate(
            [lines[0], "再核对参数，保证降噪。"],
            [2, 2],
            pool,
            rows,
            "narrated",
            {"direction": {"version": "narrative-v1", "style_id": "social"}},
        )


def test_outro_reminder_rejects_arbitrary_suffix_even_without_performance_keywords():
    from ecom_video.production_direction import closing_reminder

    assert not closing_reminder("再核对参数，通话更清楚。", 0, 1)
    assert not closing_reminder("再核对说明，它的声音令人惊艳。", 0, 1)


def test_reordered_folding_instruction_still_requires_observed_action():
    import pytest
    from test_clip_grounding import clip, ranking

    from ecom_video.clip_matching import allocate

    c = clip("x", "黑色耳机，耳罩可折叠")
    c["observation"]["actions"] = ["耳罩可折叠"]
    for line in ("向内转动两侧耳罩。", "向内折叠耳罩。", "把耳罩收拢。"):
        with pytest.raises(ValueError, match="动作"):
            allocate(
                [line],
                [3],
                [c],
                [ranking(1, x=3)],
                "narrated",
                {"direction": {"version": "narrative-v1", "style_id": "social"}},
            )


def test_static_fold_result_tags_do_not_prove_the_action():
    from test_clip_grounding import clip

    from ecom_video.production_direction import supports_action

    c = clip("x", "黑色耳机")
    for tag in ("耳罩已折叠", "展示折叠后的耳机", "双手托着收起后的耳机"):
        c["observation"]["actions"] = [tag]
        assert not supports_action(c, "把两侧耳罩向内转动，看看收起后的样子。")


def test_local_outro_rejects_multi_product_script_including_computer():
    from test_clip_grounding import clip

    from ecom_video.production_direction import outro_candidate

    c = clip("x", "黑色耳机")
    c["observation"]["framing"] = "whole"
    assert not outro_candidate(
        c, ["先看这副耳机。", "再看电脑外观。", "再核对参数和自己的使用需求。"], 2
    )
