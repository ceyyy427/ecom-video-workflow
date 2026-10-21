"""Evidence must include added crops and must not hide missing original frames."""

import copy
import hashlib

import pytest
from PIL import Image

from scripts.check_material_cold import verify_frame_evidence


def fixture(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    for folder in (before, after):
        Image.new("RGB", (100, 100), "#616161").save(folder / "frame.jpg")
    segment = {
        "frames": ["frame.jpg"],
        "motion_check": {"samples": [{"time": 1, "frame": "frame.jpg"}]},
    }
    return before, after, segment, copy.deepcopy(segment)


def test_missing_original_frame_cannot_hide_outside_intersection(tmp_path):
    before, after, a, b = fixture(tmp_path)
    b["frames"] = []
    with pytest.raises(AssertionError, match="原抽帧集合"):
        verify_frame_evidence(before, after, a, b)


def add_crop(after, b):
    sample = b["motion_check"]["samples"][0]
    with Image.open(after / "frame.jpg") as im:
        im.crop((12, 12, 88, 88)).save(after / "frame-target.jpg")
    b["frames"].append("frame-target.jpg")
    sample.update(
        bbox=[200, 200, 800, 800],
        comparison_frame="frame-target.jpg",
        appearance_evidence={
            "comparison_sha256": hashlib.sha256(
                (after / "frame-target.jpg").read_bytes()
            ).hexdigest()
        },
    )


def test_new_crop_is_independently_verified_and_recorded(tmp_path):
    before, after, a, b = fixture(tmp_path)
    add_crop(after, b)
    count, changes = verify_frame_evidence(before, after, a, b)
    assert count == 1 and len(changes) == 1
    assert changes[0]["status"] == "added"
    assert changes[0]["independently_reproduced"]


def test_new_crop_with_wrong_geometry_does_not_pass_its_own_sha(tmp_path):
    before, after, a, b = fixture(tmp_path)
    add_crop(after, b)
    b["motion_check"]["samples"][0]["bbox"] = [100, 100, 800, 800]
    with pytest.raises(AssertionError):
        verify_frame_evidence(before, after, a, b)
