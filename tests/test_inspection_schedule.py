"""Prefix-friendly scheduling keeps every original per-frame check and crop budget."""

from PIL import Image

from ecom_video import product_inspection as p
from ecom_video.media import digest


def test_dense_frames_share_reference_prefix_before_independent_motion_checks(
    tmp_path, monkeypatch
):
    ref = tmp_path / "ref.jpg"
    Image.new("RGB", (64, 64), "green").save(ref)
    folder = tmp_path / "frames"
    folder.mkdir()
    calls = []

    def generate(prompt, schema, images, model, **kwargs):
        if "single main product" in prompt:
            return {"category": "cup", "target_count": "one"}
        name = images[-1].name
        if prompt.startswith("图1是参照商品"):
            calls.append(("appearance", name))
            return {
                "match": "same",
                "permanent_features": ["rim_shape", "body_shape"],
                "uncertainty": "none",
            }
        if "Inspect this single photograph" in prompt:
            calls.append(("motion", name))
            return {
                "target_count": "one",
                "liquid_stream_outside_container": False,
                "cap_separated_from_mouth": False,
                "cap_covers_mouth": False,
                "hand_holds_cap": False,
                "visibility": "full",
                "bbox": [200, 100, 800, 900],
            }
        raise AssertionError(prompt)

    def extract(args, *a, **k):
        Image.new("RGB", (64, 64), "green").save(args[-1])

    monkeypatch.setattr(p, "generate", generate)
    monkeypatch.setattr(p, "run_checked", extract)
    monkeypatch.delenv("ECOM_VISION_ACCELERATION", raising=False)
    segment = {"id": "clip-00", "start": 0, "end": 3.1, "frames": [], "sample_times": []}
    context = {
        "reference_path": "ref.jpg",
        "reference_sha256": digest(ref),
        "action_timing": True,
        "material_checks": "material-checks-v1",
    }
    p.inspect_segment(tmp_path, "unused.mp4", "video", segment, folder, context, {}, lambda: None)
    assert [kind for kind, _ in calls] == ["appearance"] * 4 + ["motion"] * 4 + [
        "appearance",
        "motion",
    ]
    samples = segment["motion_check"]["samples"]
    assert [s["time"] for s in samples] == [0.05, 0.8, 1.55, 2.3, 3.05]
    assert len(samples) == segment["motion_check"]["planned_samples"] == 5
    assert all(
        s["match"] == "same" and s["target_count"] == "one" and s["bbox"] == [200, 100, 800, 900]
        for s in samples
    )


def test_prefetch_does_not_read_more_frames_after_a_definite_other_product(tmp_path, monkeypatch):
    calls = []
    Image.new("RGB", (32, 32), "green").save(tmp_path / "ref.jpg")
    for n in range(8):
        Image.new("RGB", (32, 32), "green").save(tmp_path / f"f{n}.jpg")

    def compare(reference, frame, *a, **k):
        calls.append(frame)
        return {
            "match": "different",
            "permanent_features": ["body_shape", "handle_presence"],
            "uncertainty": "different_design",
        }

    monkeypatch.setattr(p, "appearance", compare)
    frames = [(n, float(n), tmp_path / f"f{n}.jpg", None) for n in range(8)]
    rows = list(p.primary_batches(iter(frames), tmp_path / "ref.jpg", {}, "cup", lambda: None))
    assert len(rows) == 1 and calls == [tmp_path / "f0.jpg"]


def test_changed_prefetched_pixels_cannot_be_bound_to_a_new_motion_check(tmp_path, monkeypatch):
    import pytest

    ref = tmp_path / "ref.jpg"
    frame = tmp_path / "frame.jpg"
    for file in (ref, frame):
        Image.new("RGB", (32, 32), "green").save(file)
    monkeypatch.setattr(
        p,
        "appearance",
        lambda *a, **k: {
            "match": "same",
            "permanent_features": ["rim_shape", "body_shape"],
            "uncertainty": "none",
        },
    )
    monkeypatch.setattr(p, "motion_state", lambda *a, **k: {"target_count": "one"})
    row = next(p.primary_batches(iter([(0, 0, frame, None)]), ref, {}, "cup", lambda: None))
    Image.new("RGB", (32, 32), "blue").save(frame)
    with pytest.raises(ValueError, match="图片.*变化"):
        p.inspect_material_state(ref, frame, {}, "cup", [2], primary=row[3])


def test_ambiguous_primaries_keep_the_original_two_crop_budget(tmp_path, monkeypatch):
    ref = tmp_path / "ref.jpg"
    Image.new("RGB", (64, 64), "green").save(ref)
    frames = []
    crops = []
    for n in range(6):
        frame = tmp_path / f"f{n}.jpg"
        Image.new("RGB", (64, 64), "green").save(frame)
        frames.append((n, float(n), frame, None))

    def appearance(reference, frame, *a, **k):
        if frame.stem.endswith("-target"):
            crops.append(frame)
            return {
                "match": "same",
                "permanent_features": ["rim_shape", "base_facets"],
                "uncertainty": "none",
            }
        return {"match": "different", "permanent_features": [], "uncertainty": "ambiguous"}

    monkeypatch.setattr(p, "appearance", appearance)
    monkeypatch.setattr(
        p,
        "motion_state",
        lambda *a, **k: {
            "target_count": "one",
            "visibility": "full",
            "bbox": [100, 100, 900, 900],
            "flow": "absent",
            "lid": "unclear",
            "handling_lid": False,
        },
    )
    budget = [2]
    states = []
    for _, _, frame, primary in p.primary_batches(iter(frames), ref, {}, "cup", lambda: None):
        states.append(p.inspect_material_state(ref, frame, {}, "cup", budget, primary=primary))
        if states[-1]["match"] == "different":
            break
    assert [s["match"] for s in states] == ["same", "same", "different"]
    assert len(crops) == 2 and budget == [0]
    assert all(s["appearance_evidence"]["primary"]["match"] == "different" for s in states[:2])
