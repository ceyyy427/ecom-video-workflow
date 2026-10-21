from copy import deepcopy

from scripts.build_narrative_samples import corrected_provenance


def test_recut_provenance_replaces_only_target_and_preserves_previous_receipt():
    source = {
        "approvals": [],
        "source_edits": [{"shot": 1, "cuts": ["old0"]}, {"shot": 2, "cuts": ["old1"]}],
    }
    before = deepcopy(source)
    board = {"shots": [{"shot_id": "a"}, {"shot_id": "b"}]}
    edits = [
        {
            "shot_id": "b",
            "source": "original.mp4",
            "source_sha256": "abc",
            "source_in": 10.4,
            "seconds": 2,
            "crop": [900, 900, 90, 930],
        }
    ]
    fixed = corrected_provenance(source, board, edits)
    assert source == before
    assert fixed["source_edits"][0] == before["source_edits"][0]
    cut = fixed["source_edits"][1]["cuts"][0]
    assert cut == {
        "source": "original.mp4",
        "source_sha256": "abc",
        "source_in": 10.4,
        "source_out": 12.4,
        "scene_in": 0,
        "scene_out": 2,
        "crop_xywh": [90, 930, 900, 900],
    }
    assert fixed["previous_source_edits"] == before["source_edits"]
    assert fixed["approvals"] == []
