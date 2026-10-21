"""Identity and motion evidence must constrain automatic selection, not manual edits."""

import pytest

from ecom_video.product_motion import VERSION


def state(t, *, match="same", flow="absent", lid="unclear", handling=False):
    return {
        "time": t,
        "match": match,
        "target_count": "one",
        "flow": flow,
        "lid": lid,
        "handling_lid": handling,
        "evidence": "test frame",
    }


def test_opening_needs_attached_to_detached_transition_and_handling():
    from ecom_video.product_motion import build_events

    assert not build_events([state(0, lid="detached"), state(1, lid="detached")])
    assert not build_events([state(0, lid="attached"), state(1, lid="detached")])
    events = build_events([state(0, lid="attached", handling=True), state(1, lid="detached")])
    assert events[0]["kind"] == "open_lid"
    assert events[0]["start"] == 0 and events[0]["end"] == 1


def test_pour_requires_multiple_same_product_visible_stream_frames():
    from ecom_video.product_motion import build_events

    assert not build_events([state(0, flow="visible")])
    assert not build_events([state(0, flow="visible"), state(1, flow="visible", match="different")])
    assert not build_events([state(0, flow="visible"), state(4, flow="visible")])
    e = build_events([state(0), state(1, flow="visible"), state(2, flow="visible"), state(3)])[0]
    assert (e["kind"], e["start"], e["end"]) == ("pour", 1, 2)


def test_action_range_uses_voice_offset_and_never_extends_source():
    from ecom_video.product_motion import action_ranges

    c = {
        "start": 0,
        "end": 10,
        "kind": "video",
        "motion_check": {"events": [{"kind": "pour", "start": 4, "end": 6, "anchor": 4}]},
    }
    windows = action_ranges(c, 3, [{"kind": "pour", "start": 0.8, "end": 1.4}])
    assert windows and all(4 <= w["start"] + 0.8 <= w["start"] + 1.4 <= 6 for w in windows)
    c["end"] = 4.5
    assert not action_ranges(c, 3, [{"kind": "pour", "start": 0.8, "end": 1.4}])
    c["kind"] = "image"
    assert not action_ranges(c, 3, [{"kind": "pour", "start": 0.8, "end": 1.4}])


def test_opening_window_keeps_before_and_after_with_bounded_timing_error():
    from ecom_video.product_motion import action_ranges

    c = {
        "start": 0,
        "end": 8,
        "kind": "video",
        "motion_check": {"events": [{"kind": "open_lid", "start": 3, "end": 4, "anchor": 3.5}]},
    }
    windows = action_ranges(c, 3, [{"kind": "open_lid", "start": 0.2, "end": 0.6}])
    assert windows
    for w in windows:
        assert w["start"] <= 3 and w["start"] + 3 >= 4
        assert abs((3.5 - w["start"]) - 0.4) <= 0.6 + 0.001


def test_word_anchor_rejects_interpolated_action_tokens():
    from ecom_video.product_motion import voice_anchors

    result = {
        "result": {
            "sentences": [
                {
                    "words": [
                        {"text": c, "start": i * 0.2, "end": i * 0.2 + 0.18, "anchored": True}
                        for i, c in enumerate("先开盖")
                    ]
                }
            ]
        }
    }
    a = voice_anchors(["先开盖。"], [3], result)[0]
    assert a[0]["kind"] == "open_lid" and a[0]["start"] == 0.2
    result["result"]["sentences"][0]["words"][1]["anchored"] = False
    with pytest.raises(ValueError, match="动作词"):
        voice_anchors(["先开盖。"], [3], result)


def test_different_and_uncertain_products_are_excluded_before_ranking():
    from ecom_video.product_motion import eligible_identity

    c = {"motion_check": {"version": VERSION, "reference_sha256": "ref", "identity": "different"}}
    assert not eligible_identity(
        c, {"strict_product": True, "version": VERSION, "reference_sha256": "ref"}
    )
    c["motion_check"]["identity"] = "uncertain"
    assert not eligible_identity(
        c, {"strict_product": True, "version": VERSION, "reference_sha256": "ref"}
    )
    c["motion_check"]["identity"] = "same"
    assert eligible_identity(
        c, {"strict_product": True, "version": VERSION, "reference_sha256": "ref"}
    )
    assert not eligible_identity(c, {"strict_product": True, "reference_sha256": "changed"})


def test_allocator_does_not_move_voice_anchored_window_to_avoid_reuse():
    from ecom_video.clip_matching import allocate

    c = {
        "id": "v",
        "asset_id": "video",
        "asset_sha256": "sha",
        "kind": "video",
        "start": 0,
        "end": 10,
        "observation": {"description": "瓶子倒水", "subjects": [], "actions": []},
        "role": "product",
        "note": "",
        "segment_id": "clip",
        "motion_check": {
            "identity": "same",
            "version": VERSION,
            "reference_sha256": "ref",
            "samples": [state(t) for t in range(11)],
            "events": [{"kind": "pour", "start": 2, "end": 4, "anchor": 2}],
        },
    }
    rankings = [
        {"line": i, "choices": [{"clip_id": "v", "score": 3, "reason": "test"}]} for i in (1, 2)
    ]
    constraints = {
        "strict_product": True,
        "version": VERSION,
        "reference_sha256": "ref",
        "anchors": [[{"kind": "pour", "start": 0.4, "end": 0.8}]] * 2,
    }
    decisions = allocate(["倒水", "倒水"], [3, 3], [c], rankings, "narrated", constraints)
    assert decisions[1]["reused"]
    assert all(2 <= d["start"] + 0.4 < d["start"] + 0.8 <= 4 for d in decisions)
    c["motion_check"]["identity"] = "different"
    c["motion_check"]["samples"] = [state(t, match="different") for t in range(11)]
    with pytest.raises(ValueError, match="未找到"):
        allocate(["倒水", "倒水"], [3, 3], [c], rankings, "narrated", constraints)


def test_distinct_action_phrases_each_get_their_actual_voice_occurrence():
    from ecom_video.product_motion import voice_anchors

    line = "先倒水再倒入"
    result = {
        "result": {
            "sentences": [
                {
                    "words": [
                        {"text": c, "start": i * 0.2, "end": i * 0.2 + 0.18, "anchored": True}
                        for i, c in enumerate(line)
                    ]
                }
            ]
        }
    }
    anchors = voice_anchors([line], [3], result)[0]
    assert len(anchors) == 2 and anchors[1]["start"] == 0.8


@pytest.mark.parametrize(
    "line", ["不锈钢杯，倒入热水。", "无需等待，倒入热水。", "不用手动开盖，直接倒水。"]
)
def test_unrelated_negation_does_not_disable_action_timing(line):
    from ecom_video.product_motion import voice_anchors

    result = {
        "result": {
            "sentences": [
                {
                    "words": [
                        {"text": c, "start": i * 0.2, "end": i * 0.2 + 0.18, "anchored": True}
                        for i, c in enumerate(line)
                    ]
                }
            ]
        }
    }
    assert any(a["kind"] == "pour" for a in voice_anchors([line], [8], result)[0])


def test_different_products_cannot_consume_matching_context_budget(monkeypatch):
    from ecom_video import clip_matching

    assets = []
    for i in range(30):
        segments = [
            {
                "id": str(k),
                "start": k * 5,
                "end": k * 5 + 5,
                "quality": {"blank": False},
                "observation": {"usable": True, "description": "瓶身", "framing": "whole"},
                "motion_check": {
                    "identity": "same" if (i, k) == (29, 1) else "different",
                    "version": VERSION,
                    "reference_sha256": "ref",
                    "samples": [
                        state(k * 5 + t, match="same" if (i, k) == (29, 1) else "different")
                        for t in range(6)
                    ],
                },
            }
            for k in range(2)
        ]
        assets.append(
            {
                "id": str(i),
                "sha256": str(i),
                "kind": "video",
                "metadata": {
                    "content_analysis": {
                        "source_sha256": str(i),
                        "analysis_id": "test",
                        "segments": segments,
                    }
                },
            }
        )
    job = {
        "assets": assets,
        "script": "瓶身",
        "matching_constraints": {
            "strict_product": True,
            "version": VERSION,
            "reference_sha256": "ref",
        },
    }
    monkeypatch.setattr(clip_matching, "identity", lambda: {"model": "fixture"})

    def rank(lines, pool, model):
        assert len(pool) == 1 and pool[0]["asset_id"] == "29"
        return [
            {"line": 1, "choices": [{"clip_id": pool[0]["id"], "score": 3, "reason": "fixture"}]}
        ]

    monkeypatch.setattr(clip_matching, "rank", rank)
    assert clip_matching.select(job, [3], "narrated")[0][0]["asset_id"] == "29"


def test_action_events_cannot_reverse_voice_order_or_reuse_one_opening():
    from ecom_video.product_motion import action_ranges, voice_anchors

    c = {
        "start": 0,
        "end": 6,
        "kind": "video",
        "motion_check": {
            "events": [
                {"kind": "close_lid", "start": 2.5, "end": 3, "anchor": 2.75},
                {"kind": "open_lid", "start": 3, "end": 3.5, "anchor": 3.25},
            ]
        },
    }
    needs = [
        {"kind": "open_lid", "start": 1, "end": 1.2},
        {"kind": "close_lid", "start": 1.3, "end": 1.5},
    ]
    assert not action_ranges(c, 4, needs)
    needs[1]["kind"] = "open_lid"
    assert not action_ranges(c, 4, needs)
    line = "不用手动开盖，直接倒水。"
    result = {
        "result": {
            "sentences": [
                {
                    "words": [
                        {"text": c, "start": i * 0.2, "end": i * 0.2 + 0.18, "anchored": True}
                        for i, c in enumerate(line)
                    ]
                }
            ]
        }
    }
    assert [a["kind"] for a in voice_anchors([line], [8], result)[0]] == ["pour"]


def test_opening_prefers_closest_voice_sync_within_valid_range():
    from ecom_video.clip_matching import allocate

    c = {
        "id": "v",
        "asset_id": "v",
        "asset_sha256": "sha",
        "kind": "video",
        "start": 0,
        "end": 8,
        "role": "product",
        "note": "",
        "segment_id": "clip",
        "observation": {"description": "手打开瓶盖", "subjects": ["瓶子"], "actions": ["开盖"]},
        "motion_check": {
            "identity": "same",
            "version": VERSION,
            "reference_sha256": "ref",
            "samples": [state(t) for t in range(9)],
            "events": [{"kind": "open_lid", "start": 3.2, "end": 4, "anchor": 3.6}],
        },
    }
    constraints = {
        "strict_product": True,
        "reference_sha256": "ref",
        "anchors": [[{"kind": "open_lid", "start": 1.8, "end": 2.8}]],
    }
    d = allocate(
        ["拧开瓶盖"],
        [3.2],
        [c],
        [{"line": 1, "choices": [{"clip_id": "v", "score": 3, "reason": "test"}]}],
        "narrated",
        constraints,
    )[0]
    assert abs(3.6 - d["start"] - 2.3) <= 1 / 30
