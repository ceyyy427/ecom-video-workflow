"""A numbered instruction must not hide a later ranking claim on the same line."""

import pytest

from ecom_video.audit import audit_script


@pytest.mark.parametrize(
    "line", ["第一，看连帽和领口的轮廓。", "  第一、观察外观。", "第一：检查细节。"]
)
def test_explicit_numbered_observation_is_not_a_ranking(line):
    result = audit_script(line)
    assert not [f for f in result["findings"] if f["rule_id"] == "superlative"]
    assert result["status"] == "needs_review"


@pytest.mark.parametrize(
    "line", ["销量第一", "全网第一", "第一名", "第一，销量领先。", "第一看连帽"]
)
def test_ambiguous_or_ranking_first_still_requires_review(line):
    assert any(f["term"] == "第一" for f in audit_script(line)["findings"])


def test_instruction_does_not_hide_later_claim_or_its_location():
    result = audit_script("普通外观。\n第一，看连帽，这是全网第一。")
    hit = next(f for f in result["findings"] if f["term"] == "第一")
    assert hit["line"] == 2
    assert hit["normalized_column"] == 12


def test_numbering_never_hides_other_blocking_claims():
    result = audit_script("第一，看连帽，绝对安全。")
    assert result["status"] == "blocked"
    assert any(f["term"] == "绝对安全" for f in result["findings"])
