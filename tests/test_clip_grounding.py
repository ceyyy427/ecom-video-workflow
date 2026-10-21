"""Adversarial context scores must not beat actual visible scene evidence."""

import pytest

from ecom_video import clip_matching


def clip(key, description, *, kind="video", start=0, end=8):
    return {
        "id": key,
        "asset_id": key,
        "asset_sha256": key,
        "kind": kind,
        "start": start,
        "end": end,
        "analysis_id": "real-shape-test",
        "segment_id": key,
        "role": "product",
        "note": "",
        "observation": {
            "description": description,
            "subjects": [],
            "actions": [],
            "uncertainty": "",
            "framing": "context",
            "usable": True,
        },
    }


def ranking(i, **scores):
    return {
        "line": i,
        "choices": [{"clip_id": k, "score": v, "reason": "test score"} for k, v in scores.items()],
    }


def test_desk_and_book_requirement_beats_wrong_high_score_and_reuse_penalty():
    pool = [
        clip("desk", "白色杯子放在木质桌面，旁边有笔记本和植物"),
        clip("close", "杯盖有椭圆形开口，背景是浅色墙壁", kind="image"),
    ]
    rows = [ranking(1, desk=3), ranking(2, desk=2, close=3)]
    chosen = clip_matching.allocate(
        ["看看外观", "放在桌边，和书本一起看看整体"], [5, 4], pool, rows, "narrated"
    )
    assert chosen[1]["id"] == "desk"
    assert chosen[1]["reused"] is True
    assert {x["label"] for x in chosen[1]["grounding"]["matched"]} == {"桌面", "书本"}


@pytest.mark.parametrize(
    "description",
    [
        "杯子在台面上，背景只有墙壁",
        "桌面上没有书本，只有杯子",
        "杯子在桌面上，旁边是笔记本电脑",
        "杯子在桌上，可能有一本书本，但看不清",
    ],
)
def test_missing_negated_uncertain_or_laptop_is_not_book_evidence(description):
    with pytest.raises(ValueError, match="画面要求"):
        clip_matching.allocate(
            ["桌边和书本"], [3], [clip("x", description)], [ranking(1, x=3)], "narrated"
        )


def test_unmentioned_scene_from_filename_or_human_role_cannot_supply_evidence():
    c = clip("desk-book", "杯子特写，只有杯盖")
    c.update(role="lifestyle", note="桌面书本", name="桌面书本.mp4")
    with pytest.raises(ValueError, match="画面要求"):
        clip_matching.allocate(["桌面书本"], [3], [c], [ranking(1, **{"desk-book": 3})], "narrated")


def test_semantic_relevance_is_not_overridden_by_novelty():
    p = [clip("relevant", "商品整体"), clip("weaker", "商品局部")]
    chosen = clip_matching.allocate(
        ["展示外观", "继续展示"],
        [5, 5],
        p,
        [ranking(1, relevant=3), ranking(2, relevant=3, weaker=2)],
        "narrated",
    )
    assert chosen[1]["id"] == "relevant"


def test_generic_intro_reserves_only_desk_book_clip_for_later_specific_line():
    p = [clip("desk", "杯子在桌上，旁边是书本", end=6), clip("hero", "杯子整体", end=6)]
    chosen = clip_matching.allocate(
        ["看看外观", "桌边和书本"],
        [4, 4],
        p,
        [ranking(1, desk=3, hero=3), ranking(2, desk=3, hero=3)],
        "narrated",
    )
    assert [c["id"] for c in chosen] == ["hero", "desk"]
    assert not any(c["reused"] for c in chosen)


def test_empty_context_preserves_general_product_matching():
    chosen = clip_matching.allocate(
        ["喜欢这种简洁外观"], [3], [clip("x", "白色杯子")], [ranking(1, x=3)], "narrated"
    )
    assert chosen[0]["id"] == "x"


def test_negated_script_does_not_require_the_rejected_scene():
    chosen = clip_matching.allocate(
        ["不要桌面场景，只看杯盖"], [3], [clip("cap", "杯盖特写")], [ranking(1, cap=3)], "narrated"
    )
    assert chosen[0]["id"] == "cap"


def test_rank_filters_unsupported_candidates_before_model(monkeypatch):
    import json

    p = [clip("desk", "杯子在桌面，旁边有书籍"), clip("macro", "杯盖特写")]

    def model(prompt, schema, **kwargs):
        data = json.loads(prompt.split("\n", 1)[1])
        assert [c["id"] for c in data["candidates"]] == ["desk"]
        assert schema["$defs"]["Choice"]["properties"]["clip_id"]["enum"] == ["desk"]
        return {"lines": [ranking(1, desk=3)]}

    monkeypatch.setattr(clip_matching, "generate", model)
    assert (
        clip_matching.rank(["桌边与书本"], p, {"model": "fixture"})[0]["choices"][0]["clip_id"]
        == "desk"
    )


def test_rank_receives_dense_action_evidence_when_coarse_description_omits_it(monkeypatch):
    import json

    candidate = clip("flask", "银色瓶身被双手握住")
    candidate["motion_check"] = {"events": [{"kind": "pour", "evidence": "连续抽样帧可见液流"}]}

    def model(prompt, schema, **kwargs):
        data = json.loads(prompt.split("\n", 1)[1])
        shown = data["candidates"][0]
        assert shown["sampled_action_evidence"] == candidate["motion_check"]["events"]
        assert any("倒入" in text and "液流" in text for text in shown["actions"])
        assert candidate["observation"]["actions"] == []
        assert shown["context_evidence"][0]["key"] == "pour"
        return {"lines": [ranking(1, flask=3)]}

    monkeypatch.setattr(clip_matching, "generate", model)
    assert clip_matching.rank(["倒入杯中"], [candidate], {"model": "fixture"})


@pytest.mark.parametrize(
    "description",
    [
        "桌面上有杯子，书本未出现",
        "A mug sits on a desk. Books are not visible.",
    ],
)
def test_predicate_negation_is_not_positive_evidence(description):
    from ecom_video.clip_grounding import assess

    assert not assess("桌面书本", clip("x", description))["eligible"]


def test_negative_uncertainty_vetoes_positive_description():
    from ecom_video.clip_grounding import assess

    c = clip("x", "桌面上有杯子和书本")
    c["observation"]["uncertainty"] = "未见书本"
    assert not assess("桌面书本", c)["eligible"]


@pytest.mark.parametrize(
    "line", ["不要书本只展示杯盖", "不要书本，但展示杯盖", "No books, only a lid"]
)
def test_negative_object_does_not_exclude_affirmative_next_object(line):
    from ecom_video.clip_grounding import assess, requirements

    need = requirements(line)
    assert need["required"] == ["lid"]
    assert need["excluded"] == ["book"]
    assert assess(line, clip("x", "杯盖特写"))["eligible"]
    assert not assess(line, clip("wrong", "桌面上的杯子"))["eligible"]


def test_glass_cup_supports_generic_cup_but_laptop_does_not_support_paper_book():
    from ecom_video.clip_grounding import assess

    assert assess("杯子", clip("x", "透明玻璃杯"))["eligible"]
    assert not assess("书本", clip("x", "笔记本电脑"))["eligible"]


def test_full_frame_footage_treatment_roundtrips_in_board_and_manual_patch():
    from ecom_video.customer_api import ShotChanges
    from ecom_video.storyboard import Shot

    # A first-class treatment, available to automatic plans and manual adjustments.
    assert Shot.model_validate(Shot(treatment="footage").model_dump()).treatment == "footage"
    assert ShotChanges(treatment="footage").treatment == "footage"


@pytest.mark.parametrize("description", ["杯子没有杯盖", "透明玻璃杯没有把手"])
def test_missing_component_does_not_make_visible_product_absent(description):
    from ecom_video.clip_grounding import assess

    assert assess("杯子", clip("x", description))["eligible"]
    assert not assess("杯盖和把手", clip("x", description))["eligible"]
