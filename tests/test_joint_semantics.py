import copy

from ecom_video.prompt_catalog import apply_prompts, card_record
from ecom_video.shotcraft import MotionPlan


def test_joint_plan_uses_semantics_not_one_card_for_all_and_protects_actions():
    lines = [
        "先看一眼，再看细节。",
        "藏蓝连帽设计。",
        "拉开口袋，放进小东西。",
        "回到通勤场景。",
        "仅活动期内满200元减20元。",
        "看清楚，再挑适合自己的。",
    ]
    facts = [{"id": str(i), "text": t} for i, t in enumerate(lines[1:-1], 1)]
    payload = [
        {"text": t, "fact_ids": [str(i)] if 0 < i < len(lines) - 1 else []}
        for i, t in enumerate(lines)
    ]
    job = {
        "script": "\n".join(lines),
        "provenance": {
            "facts": facts,
            "scenes": payload,
            "creative_plan": {"version": "joint-creative-v1", "payload": payload},
        },
    }
    direction = {"mix_policy": "semantic-mix-v1", "cards": [card_record("garment-punch-v1")]}
    rows = [
        {
            "shot_recipe": "none",
            "transition": "cut",
            "reason": "",
            "motion_plan": MotionPlan(repeat_limit=4).model_dump(),
        }
        for _ in lines
    ]
    assets = [{"kind": "video", "metadata": {"width": 1080, "height": 1920}} for _ in lines]
    result = apply_prompts(rows, lines, [4] * len(lines), assets, direction, job=job)
    assert result[1]["motion_plan"]["prompt_card"] == "detail-bracket-soft-v1"
    assert result[2]["shot_recipe"] == "none"
    assert result[3]["motion_plan"]["prompt_card"] == "warm-portal-v1"
    assert result[4]["motion_plan"]["prompt_card"] == "fact-row-soft-v1"
    assert "语义编导" in result[3]["reason"]
    # An old saved job without a joint plan keeps its existing policy.
    old = copy.deepcopy(job)
    old["provenance"].pop("creative_plan")
    legacy = apply_prompts(rows, lines, [4] * len(lines), assets, direction, job=old)
    assert legacy[3]["motion_plan"]["prompt_card"] == "garment-punch-v1"


def test_new_action_classification_protects_the_adjacent_exit_boundary():
    from ecom_video.shotcraft import effective_transitions

    lines = ["先看一眼，再看细节。", "拉开拉链。", "回到通勤场景。", "看清楚，再挑适合自己的。"]
    payload = [{"text": t, "fact_ids": []} for t in lines]
    job = {
        "script": "\n".join(lines),
        "provenance": {"creative_plan": {"version": "joint-creative-v1", "payload": payload}},
    }
    rows = [
        {
            "shot_recipe": "none",
            "transition": "cut",
            "reason": "",
            "motion_plan": MotionPlan(intent="context").model_dump(),
        }
        for _ in lines
    ]
    assets = [{"kind": "video", "metadata": {"width": 1080, "height": 1920}} for _ in lines]
    result = apply_prompts(
        rows,
        lines,
        [4] * 4,
        assets,
        {"mix_policy": "semantic-mix-v1", "cards": [card_record("garment-punch-v1")]},
        job=job,
    )
    assert result[1]["motion_plan"]["intent"] == "action"
    assert result[2]["transition"] == "cut"
    assert effective_transitions([{**r, "frames": 120} for r in result])[2] == "cut"


def test_joint_qualified_fact_cannot_become_a_short_unconditional_showcase_title():
    from ecom_video.semantic_mix import guard_decision

    line = "仅限短时小雨，不适用于持续淋雨。"
    payload = [
        {"text": "先看", "fact_ids": []},
        {"text": line, "fact_ids": ["f"]},
        {"text": "再选", "fact_ids": []},
    ]
    job = {
        "script": "\n".join(p["text"] for p in payload),
        "provenance": {
            "facts": [{"id": "f", "text": line}],
            "scenes": payload,
            "creative_plan": {"version": "joint-creative-v1", "payload": payload},
        },
    }
    rows = [
        {
            "shot_recipe": "none",
            "transition": "cut",
            "reason": "",
            "motion_plan": MotionPlan().model_dump(),
        }
        for _ in payload
    ]
    assets = [{"kind": "video", "metadata": {"width": 1080, "height": 1920}} for _ in payload]
    out = apply_prompts(
        rows,
        [p["text"] for p in payload],
        [4] * 3,
        assets,
        {"mix_policy": "semantic-mix-v1", "cards": [card_record("garment-punch-v1")]},
        job=job,
    )
    assert out[1].get("clear_headline")
    assert out[1]["shot_recipe"] == "product-fact-row"
    assert guard_decision(job, 1, {"recipe": "product-fact-row"})["quote"]["text"] == line
