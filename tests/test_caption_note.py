import pytest
from pydantic import ValidationError

from ecom_video.customer_api import ShotChanges
from ecom_video.storyboard import Shot


def test_optional_human_note_is_bounded_and_not_narration():
    assert Shot().model_dump()["caption_note"] == ""
    note = "防泼水演示，非防水等级测试"
    assert Shot(caption_note=note).caption_note == note
    assert ShotChanges(caption_note=note).model_dump(exclude_unset=True) == {"caption_note": note}
    with pytest.raises(ValidationError):
        Shot(caption_note="字" * 41)
    with pytest.raises(ValidationError):
        ShotChanges(caption_note="字" * 41)


def test_old_board_without_note_compares_equal_to_new_empty_note():
    from ecom_video.delivery_revision import canonical

    old = {"assets": [], "storyboard": {"shots": [{"shot_id": "s1"}]}}
    new = {"assets": [], "storyboard": {"shots": [{"shot_id": "s1", "caption_note": ""}]}}
    assert canonical(old) == canonical(new)


def test_handoff_board_binding_handles_schema_numeric_defaults_but_not_real_edits():
    import copy

    from ecom_video.customer_handoff import same_board
    from ecom_video.storyboard import Board

    raw = Board(shots=[Shot(motion_plan={"version": 2})]).model_dump()
    normalized = Board.model_validate(raw).model_dump()
    assert same_board(raw, normalized)
    altered = copy.deepcopy(raw)
    altered["shots"][0]["caption_note"] = "new visible text"
    assert not same_board(raw, altered)
    altered = copy.deepcopy(raw)
    altered["shots"][0]["motion_plan"]["cue_offset"] = 0.1
    assert not same_board(raw, altered)
    assert not same_board(raw, {"shots": []})
