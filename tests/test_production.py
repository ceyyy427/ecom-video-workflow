import pytest

from ecom_video.creative import Brief, fingerprint, recommend
from ecom_video.production import validate_production


@pytest.mark.parametrize(
    "mode,first",
    [("showcase", "cinema"), ("recommendation", "social"), ("review", "lab"), ("narrated", "lab")],
)
def test_three_distinct_directions_by_format(mode, first):
    job = {"title": "杯", "script": "看外观", "assets": []}
    rec = recommend(job, Brief(format=mode))
    assert len(rec["options"]) == 3 and rec["options"][0]["id"] == first
    assert {s["id"] for s in rec["options"]} == {"cinema", "social", "lab"}
    if mode == "review":
        assert all("测试" in " ".join(s["missing"]) for s in rec["options"])


def test_legacy_brief_keeps_original_fingerprint():
    job = {"title": "杯", "script": "看外观", "assets": []}
    brief = {"category": "家居", "audience": "", "tone": ""}
    assert fingerprint(job, brief) == fingerprint(job, {**brief, "format": "auto"})


def test_review_requires_source_context_and_video_evidence():
    board = {
        "creative": {"brief": {"format": "review"}, "review_context": ""},
        "narration": {"mode": "local"},
        "shots": [{"asset_id": "a", "role": "evidence", "evidence_note": ""}],
    }
    assets = [{"id": "a", "kind": "image"}]
    with pytest.raises(ValueError, match="测试条件"):
        validate_production(board, assets)
    board["creative"]["review_context"] = "测试方法与条件已提供"
    with pytest.raises(ValueError, match="真实测试视频"):
        validate_production(board, assets)
    board["shots"][0]["evidence_note"] = "客户测试视频 00:01–00:04"
    with pytest.raises(ValueError, match="真实测试视频"):
        validate_production(board, assets)
    assets[0]["kind"] = "video"
    validate_production(board, assets)
    board["narration"]["mode"] = "silent"
    with pytest.raises(ValueError, match="需要配音"):
        validate_production(board, assets)


def test_showcase_and_voice_are_not_silently_confused():
    b = {"creative": {"brief": {"format": "showcase"}}, "narration": {"mode": "local"}}
    with pytest.raises(ValueError, match="不含口播"):
        validate_production(b, [])
    b["narration"]["mode"] = "silent"
    validate_production(b, [])


def test_shot_treatment_and_transition_survive_rebase(tmp_path):
    from test_storyboard import draft

    from ecom_video.storyboard import default_board

    store, j = draft(tmp_path)
    b = default_board(j)
    r = recommend(j, Brief(format="showcase"))
    b["creative"] = {"brief": r["brief"], "fingerprint": r["fingerprint"], "style_id": "cinema"}
    for i, s in enumerate(b["shots"]):
        s.update(shot_id=f"shot-{i}", treatment="macro", transition="wipe")
    store.save_storyboard(j["id"], b, 0)
    changed = store.update_draft(j["id"], j["title"], "新开场\n查看细节", 2)
    assert changed["storyboard"]["shots"][1]["treatment"] == "macro"
    assert changed["storyboard"]["shots"][1]["transition"] == "wipe"
    assert changed["storyboard"]["creative"] is None


def test_spoken_captions_use_phrase_boundaries_without_orphan_tail():
    from ecom_video.captions import phrases

    result = phrases("先看杯盖，深色轮廓和开口都在这里。", [], 0, 5)
    assert [r["text"] for r in result] == ["先看杯盖", "深色轮廓和开口都在这里"]
