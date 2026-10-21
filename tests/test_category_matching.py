from test_clip_grounding import clip, ranking

from ecom_video.clip_grounding import assess
from ecom_video.clip_matching import allocate
from ecom_video.creative import Brief, recommend


def test_gentle_beauty_brief_prefers_quiet_alternative_over_unrelated_collage():
    j = {
        "title": "棕色滴管瓶",
        "script": "看看滴管和瓶身的细节",
        "assets": [{"kind": "video", "sha256": "a"}],
    }
    rec = recommend(
        j,
        Brief(
            format="narrated",
            category="美妆护肤包装",
            audience="重视精致包装的护肤消费者",
            tone="轻奢精致，温柔克制，留白",
        ),
    )
    assert rec["options"][0]["id"] == "editorial"
    assert "quiet" in {s["id"] for s in rec["options"]}
    quiet = next(s for s in rec["options"] if s["id"] == "quiet")
    assert "温柔" in quiet["matched_inputs"]["气质"]


def test_headphones_and_dropper_cannot_be_replaced_by_wrong_high_scoring_subject():
    cases = [
        ("黑色耳机，看看耳罩和头梁", "黑色头戴耳机，耳罩和弧形头梁清楚可见"),
        ("棕色滴管瓶，提起滴管看看瓶口", "棕色瓶子握在手里，滴管在瓶口上方"),
    ]
    for line, correct in cases:
        pool = [clip("correct", correct), clip("wrong", "白色杯子放在木桌，杯盖被双手拿起")]
        chosen = allocate([line], [3], pool, [ranking(1, correct=2, wrong=3)], "narrated")
        assert chosen[0]["id"] == "correct"


def test_absent_uncertain_or_negated_product_is_not_visible_evidence():
    for line, description in [
        ("耳机的耳罩", "没有耳机，只有杯子"),
        ("耳机的耳罩", "可能是耳机，耳罩看不清"),
        ("提起滴管", "瓶子在手上，没有滴管"),
    ]:
        assert not assess(line, clip("x", description))["eligible"]


def test_prior_v2_beauty_selection_and_derived_version_keep_prior_policy():
    from ecom_video.creative import rebase_fingerprint, validate_creative

    j = {
        "title": "棕色滴管瓶",
        "script": "看看滴管和瓶身的细节",
        "assets": [{"kind": "video", "sha256": "a"}],
    }
    brief = Brief(
        format="narrated",
        category="美妆护肤包装",
        audience="重视精致包装的护肤消费者",
        tone="轻奢精致，温柔克制，留白",
    )
    old = recommend(j, brief, policy=2)
    new = recommend(j, brief)
    assert old["fingerprint"] != new["fingerprint"]
    assert "collage" in {s["id"] for s in old["options"]}
    assert "quiet" in {s["id"] for s in new["options"]}
    creative = {"brief": old["brief"], "style_id": "collage", "fingerprint": old["fingerprint"]}
    validate_creative(j, creative)
    candidate = {**j, "assets": [*j["assets"], {"kind": "audio", "sha256": "new"}]}
    creative["fingerprint"] = rebase_fingerprint(j, candidate, creative)
    validate_creative(candidate, creative)
    assert creative["fingerprint"] == recommend(candidate, brief, policy=2)["fingerprint"]


def test_dropper_container_name_is_not_evidence_of_an_exposed_pipette():
    for description in (
        "棕色滴管瓶，黑色瓶盖紧闭",
        "a closed dropper bottle",
        "只有滴管盖，管身不可见",
    ):
        assert not assess("提起滴管", clip("x", description))["eligible"]
    assert assess("看看滴管瓶的外观", clip("x", "一只棕色滴管瓶"))["eligible"]


def test_audience_and_product_have_controlled_ranking_effects_not_only_new_hashes():
    j = {
        "title": "黑色折叠耳机",
        "script": "看看耳机的细节和外观",
        "assets": [{"sha256": "a", "kind": "video"}],
    }
    brief = {"format": "narrated", "category": "数码", "tone": "中性"}
    student = recommend(j, Brief(**brief, audience="年轻学生"))
    office = recommend(j, Brief(**brief, audience="办公咖啡爱好者"))
    assert student["options"][0]["id"] == "collage"
    assert office["options"][0]["id"] == "quiet"
    assert "学生" in student["options"][0]["matched_inputs"]["人群"]
    assert "办公" in office["options"][0]["matched_inputs"]["人群"]
    neutral = Brief(format="narrated", audience="普通用户", tone="中性")
    before = recommend(j, neutral)
    after = recommend(
        {**j, "title": "安静咖啡茶桌", "script": "自然温暖的桌面，放一只咖啡杯，日常品茶。"},
        neutral,
    )
    assert {s["id"] for s in before["options"]} != {s["id"] for s in after["options"]}
    assert after["options"][0]["id"] == "quiet"


def test_local_ranking_bounds_context_and_still_examines_late_candidates(monkeypatch):
    import json

    from ecom_video import clip_matching

    seen = []

    def generate(prompt, schema, **kwargs):
        assert kwargs["context_size"] == 3072
        assert len(prompt.encode()) <= 2400
        assert kwargs["max_tokens"] <= 512
        payload = json.loads(prompt.split("\n", 1)[1])
        ids = [c["id"] for c in payload["candidates"]]
        seen.extend(ids)
        return {
            "lines": [
                {
                    "line": 1,
                    "choices": [
                        {
                            "clip_id": ids[-1],
                            "score": 3 if ids[-1] == "c39" else 1,
                            "reason": "可见外观",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(clip_matching, "generate", generate)
    pool = [clip(f"c{i}", "黑色耳机，耳罩与弧形头梁。" * 10) for i in range(40)]
    rows = clip_matching.rank(["耳机外观"], pool, {"model": "fixture"})
    assert seen == [c["id"] for c in pool]
    assert rows[0]["choices"][0]["clip_id"] == "c39"


def test_equal_scoring_late_batch_keeps_the_only_long_enough_clip(monkeypatch):
    import json

    from ecom_video import clip_matching

    def generate(prompt, schema, **kwargs):
        payload = json.loads(prompt.split("\n", 1)[1])
        return {
            "lines": [
                {
                    "line": 1,
                    "choices": [
                        {"clip_id": c["id"], "score": 3, "reason": "相关外观"}
                        for c in payload["candidates"][:4]
                    ],
                }
            ]
        }

    monkeypatch.setattr(clip_matching, "generate", generate)
    pool = [
        clip(f"c{i}", "黑色耳机，耳罩与弧形头梁。" * 10, end=12 if i == 11 else 3)
        for i in range(12)
    ]
    rows = clip_matching.rank(["耳机外观"], pool, {"model": "fixture"})
    assert clip_matching.allocate(["耳机外观"], [10], pool, rows, "narrated")[0]["id"] == "c11"


def test_select_filters_short_windows_before_spending_model_calls(monkeypatch):
    import json

    from ecom_video import clip_matching

    pool = [clip("short", "黑色耳机", end=3), clip("long", "黑色耳机", end=12)]
    monkeypatch.setattr(clip_matching, "candidates", lambda *a, **k: pool)
    monkeypatch.setattr(clip_matching, "identity", lambda: {"model": "fixture"})

    def generate(prompt, schema, **kwargs):
        data = json.loads(prompt.split("\n", 1)[1])
        assert [c["id"] for c in data["candidates"]] == ["long"]
        return {"lines": [ranking(1, long=3)]}

    monkeypatch.setattr(clip_matching, "generate", generate)
    assert clip_matching.select({"script": "耳机外观"}, [10], "narrated")[0][0]["id"] == "long"
