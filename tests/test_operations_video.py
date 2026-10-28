import json

import pytest


def test_benchmark_cut_comparison_uses_bytes_not_per_version_asset_ids():
    from scripts.benchmark_domestic_execution import source_choices

    a = {
        "assets": [{"id": "old", "sha256": "a" * 64}],
        "storyboard": {
            "shots": [{"source_cuts": [{"asset_id": "old", "source_in": 1, "duration": 2}]}]
        },
    }
    b = {
        "assets": [{"id": "new", "sha256": "a" * 64}],
        "storyboard": {
            "shots": [{"source_cuts": [{"asset_id": "new", "source_in": 1, "duration": 2}]}]
        },
    }
    assert source_choices(a) == source_choices(b)
    b["storyboard"]["shots"][0]["source_cuts"][0]["source_in"] = 2
    assert source_choices(a) != source_choices(b)


def test_benchmark_edits_use_supported_fields_and_confirmed_copy():
    from ecom_video.customer_api import ShotChanges
    from scripts.benchmark_domestic_execution import changes_for

    assert ShotChanges.model_validate(changes_for("cold_render_cache")).headline == "穿得利落"
    assert ShotChanges.model_validate(changes_for("warm_single_shot")).typography.mode == "contrast"


def test_native_workbench_keyword_comes_from_confirmed_script_not_a_nonexistent_shot_field():
    from scripts.accept_domestic_workbench import native_headline

    assert (
        native_headline(
            {
                "script": "切开以后，细节才看得清。\n看看切面",
                "storyboard": {"shots": [{"shot_id": "s1"}]},
            }
        )
        == "切开以后"
    )


def test_video_acceptance_rejects_missing_rights_bad_hash_and_same_category(tmp_path):
    from ecom_video.media import digest
    from ecom_video.operations.video_acceptance import validate_video_cases

    source = tmp_path / "job.json"
    source.write_text(json.dumps({"snapshot": {"assets": []}}))
    item = {
        "id": "navy",
        "category": "clothes",
        "source_root": str(tmp_path),
        "source_job": str(source),
        "source_job_sha256": digest(source),
        "usage_scope": "仅工程演示",
        "style_id": "cinema",
    }
    with pytest.raises(ValueError):
        validate_video_cases([item, item])
    second = {**item, "id": "orange", "category": "food", "style_id": "kinetic"}
    validate_video_cases([item, second])
    with pytest.raises(ValueError):
        validate_video_cases([item, {**second, "source_job_sha256": "0" * 64}])
    with pytest.raises(ValueError):
        validate_video_cases([item, {**second, "usage_scope": ""}])


def test_audio_comparison_uses_decoded_pcm_output(tmp_path):
    import wave

    from ecom_video.operations.video_acceptance import measured_audio

    p = tmp_path / "engineering.wav"
    with wave.open(str(p), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 1600)
    assert measured_audio(p).startswith("SHA256=")
