import json
from pathlib import Path

import pytest

from ecom_video.local_asr import align


def test_mismatch_keeps_evidence_instead_of_losing_asr():
    raw = [{"text": "倒入杯中慢慢来握住瓶身让水流细一些", "start": 0.1, "end": 5}]
    with pytest.raises(ValueError) as caught:
        align("先看产品信息。\n此处是另一份长篇商品说明和素材路径。", raw, 5.26)
    diagnostic = caught.value.diagnostic
    assert diagnostic["code"] == "script_mismatch"
    assert diagnostic["transcript"] == raw[0]["text"]
    assert diagnostic["script_coverage"] < 0.35
    assert diagnostic["duration"] == 5.26


def test_history_matching_preserves_original_and_rejects_partial_or_unrelated():
    from ecom_video.speech_match import matching_drafts

    drafts = [
        {
            "id": "correct",
            "payload": [
                {"text": "倒入杯中，慢慢来。", "fact_ids": ["fact"]},
                {"text": "握住瓶身，让水流细一些。", "fact_ids": ["fact"]},
            ],
        },
        {"id": "partial", "payload": [{"text": "倒入杯中", "fact_ids": ["fact"]}]},
        {"id": "wrong", "payload": [{"text": "这是完全无关的说明", "fact_ids": ["fact"]}]},
    ]
    before = json.dumps(drafts, ensure_ascii=False)
    found = matching_drafts(drafts, "导入杯中慢慢来握住瓶身让水流细一些", {"fact"})
    assert [x["draft_id"] for x in found] == ["correct"]
    assert json.dumps(drafts, ensure_ascii=False) == before
    assert matching_drafts(drafts, "倒入杯中慢慢来握住瓶身让水流细一些", set()) == []


def test_canonical_cues_match_without_rewriting_source():
    from ecom_video.speech_match import match_score

    assert match_score("**Ｃafé** 容量 1,000 ml", "Cafe\u0301容量1000ml") == 1
    assert match_score("杯子", "杯子杯子杯子杯子") < 0.8


@pytest.mark.skipif(not Path("docs/evidence/p12/project-before.json").exists(), reason="Private customer evidence is not distributed with public source")
def test_real_failed_audio_has_matching_history():
    from ecom_video.speech_match import matching_drafts

    evidence = Path("docs/evidence/p12")
    data = json.loads((evidence / "mismatch-raw.json").read_text())
    project = json.loads((evidence / "project-before.json").read_text())
    transcript = "".join(x["text"] for x in data["raw_words"])
    found = matching_drafts(
        project["product"]["script_drafts"],
        transcript,
        {f["id"] for f in project["product"]["facts"]},
    )
    assert found[0]["draft_id"] == "95c9c61461cf422e9ed653bfb0e0fc8d"
