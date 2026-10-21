import pytest

from ecom_video.local_asr import AlignmentMismatch, align


def test_high_coverage_single_missing_character_has_bounded_estimated_timing():
    script = "请先观察合成圆罐的白色外形"
    recognized = "请先观察合成罐的白色外形"
    raw = [{"text": c, "start": i * 0.2, "end": (i + 1) * 0.2} for i, c in enumerate(recognized)]
    result = align(script, raw, 3)
    words = result["sentences"][0]["words"]
    assert "".join(w["text"] for w in words) == script
    estimated = [w["text"] for w in words if not w["anchored"]]
    assert estimated == ["成", "圆", "罐"]
    assert words[0]["start"] == 0 and words[0]["end"] == 0.2
    assert words[-1]["start"] == 2.2 and words[-1]["end"] == 2.4
    assert all(a["end"] <= b["start"] for a, b in zip(words, words[1:], strict=False))
    assert all(w["end"] > w["start"] for w in words)
    assert not result["sentences"][0]["ok"]


def test_larger_unspoken_gap_is_still_rejected():
    raw = [
        {"text": c, "start": i * 0.2, "end": (i + 1) * 0.2} for i, c in enumerate("请观察白色外形")
    ]
    with pytest.raises(AlignmentMismatch):
        align("请观察这个安装演练合成圆罐的白色外形", raw, 3)


def test_gap_repair_never_borrows_across_sentence_boundary():
    recognized = "请先观察合成罐的白色外形"
    raw = [{"text": c, "start": i * 0.2, "end": (i + 1) * 0.2} for i, c in enumerate(recognized)]
    with pytest.raises(AlignmentMismatch):
        align("请先观察合成\n圆罐的白色外形", raw, 3)
