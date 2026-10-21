"""Caches save only validated function results; pixels and model/rules are part of identity."""

import json

import pytest
from PIL import Image

from ecom_video import product_inspection

MODEL = {"model": "fixture", "digest": "fixed", "provider": "fixture"}


def test_exact_image_result_survives_rename_and_process_scope_without_new_inference(
    tmp_path, monkeypatch
):
    from ecom_video.inference_reuse import scope

    a, b = tmp_path / "a.jpg", tmp_path / "renamed.jpg"
    Image.new("RGB", (24, 24), "red").save(a)
    b.write_bytes(a.read_bytes())
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        return {"category": "cup", "target_count": "one"}

    monkeypatch.setattr(product_inspection, "generate", generate)
    with scope(tmp_path, lambda: None) as first:
        assert product_inspection.reference_subject(a, MODEL) == "cup"
    with scope(tmp_path, lambda: None) as second:
        assert product_inspection.reference_subject(b, MODEL) == "cup"
    assert len(calls) == 1 and first.misses == 1 and second.hits == 1


@pytest.mark.parametrize("change", ["pixels", "model", "force", "corrupt"])
def test_changed_or_invalid_inference_cache_recomputes(tmp_path, monkeypatch, change):
    from ecom_video.inference_reuse import scope

    a = tmp_path / "a.jpg"
    Image.new("RGB", (24, 24), "red").save(a)
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        return {"category": "cup", "target_count": "one"}

    monkeypatch.setattr(product_inspection, "generate", generate)
    with scope(tmp_path, lambda: None):
        product_inspection.reference_subject(a, MODEL)
    model = MODEL
    if change == "pixels":
        Image.new("RGB", (24, 24), "blue").save(a)
    if change == "model":
        model = {**MODEL, "digest": "new"}
    if change == "corrupt":
        p = next((tmp_path / "inference-cache").glob("*.json"))
        data = json.loads(p.read_text())
        data["value"] = "bottle"
        p.write_text(json.dumps(data))
    with scope(tmp_path, lambda: None, bypass=change == "force"):
        assert product_inspection.reference_subject(a, model) == "cup"
    assert len(calls) == 2


def test_invalid_provider_result_and_cancellation_are_never_published_as_cache_hits(
    tmp_path, monkeypatch
):
    from ecom_video.inference_reuse import scope

    a = tmp_path / "a.jpg"
    Image.new("RGB", (24, 24), "red").save(a)
    monkeypatch.setattr(product_inspection, "generate", lambda *a, **k: {"category": "invented"})
    with scope(tmp_path, lambda: None), pytest.raises(ValueError):
        product_inspection.reference_subject(a, MODEL)
    assert not list((tmp_path / "inference-cache").glob("*.json"))
    monkeypatch.setattr(
        product_inspection, "generate", lambda *a, **k: {"category": "cup", "target_count": "one"}
    )
    with scope(tmp_path, lambda: None):
        product_inspection.reference_subject(a, MODEL)

    def cancelled():
        raise RuntimeError("cancelled")

    with scope(tmp_path, cancelled), pytest.raises(RuntimeError, match="cancelled"):
        product_inspection.reference_subject(a, MODEL)


def test_provider_cannot_publish_under_pixels_it_did_not_read(tmp_path, monkeypatch):
    from ecom_video.inference_reuse import scope

    a = tmp_path / "a.jpg"
    Image.new("RGB", (24, 24), "red").save(a)
    original = a.read_bytes()
    seen = []

    def generate(prompt, schema, images, *args, **kwargs):
        Image.new("RGB", (24, 24), "blue").save(a)
        seen.append(Image.open(images[0]).getpixel((0, 0)))
        return {"category": "cup", "target_count": "one"}

    monkeypatch.setattr(product_inspection, "generate", generate)
    with scope(tmp_path, lambda: None), pytest.raises(ValueError, match="图片.*变化"):
        product_inspection.reference_subject(a, MODEL)
    assert seen[0][0] > 200 and seen[0][2] < 30, "provider must read the frozen red snapshot"
    a.write_bytes(original)
    with scope(tmp_path, lambda: None) as cache, pytest.raises(ValueError, match="图片.*变化"):
        product_inspection.reference_subject(a, MODEL)
    assert cache.misses == 1 and len(seen) == 2, (
        "changing an input during inference must not write a cache entry"
    )


def test_cached_cap_comparison_still_rechecks_raw_transition_requirements(tmp_path, monkeypatch):
    from ecom_video.inference_reuse import scope

    for name, color in [("before.jpg", "red"), ("after.jpg", "blue")]:
        Image.new("RGB", (24, 24), color).save(tmp_path / name)
    samples = [
        {
            "time": t,
            "frame": f,
            "match": "same",
            "target_count": "one",
            "lid": lid,
            "handling_lid": True,
        }
        for t, f, lid in [(0, "before.jpg", "attached"), (1, "after.jpg", "detached")]
    ]
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        return {
            "same_single_product": True,
            "cap_moves_away_from_mouth": True,
            "cap_moves_onto_mouth": False,
            "hand_manipulates_cap": True,
            "visible_before_and_after": True,
            "uncertainty": "none",
        }

    monkeypatch.setattr(product_inspection, "generate", generate)
    with scope(tmp_path, lambda: None):
        assert (
            product_inspection.temporal_lid_events(samples, tmp_path, MODEL, lambda: None)[0][
                "kind"
            ]
            == "open_lid"
        )
    with scope(tmp_path, lambda: None) as cache:
        assert (
            product_inspection.temporal_lid_events(samples, tmp_path, MODEL, lambda: None)[0][
                "kind"
            ]
            == "open_lid"
        )
    assert calls == [1] and cache.hits == 1
    samples[1]["target_count"] = "multiple"
    with scope(tmp_path, lambda: None):
        assert product_inspection.temporal_lid_events(samples, tmp_path, MODEL, lambda: None) == []
