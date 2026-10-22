import json

from ecom_video.media import digest, probe, run_checked


def test_multicut_preparation_uses_owned_video_and_exact_output_frames(tmp_path):
    from ecom_video.remotion_renderer import prepare_cut_video

    source = tmp_path / "source.mp4"
    run_checked(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x280:r=30",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(source),
        ],
        lambda: None,
    )
    assets = {"a": {"path": "source.mp4", "sha256": digest(source)}}
    scene = {
        "source_framing": "original",
        "focus_x": 0.5,
        "focus_y": 0.5,
        "source_cuts": [
            {"asset_id": "a", "source_in": 0.1, "source_duration": 0.6, "duration": 0.8},
            {"asset_id": "a", "source_in": 1, "source_duration": 0.7, "duration": 0.7},
        ],
    }
    out = tmp_path / "cuts.mp4"
    prepare_cut_video(tmp_path, out, scene, assets, lambda: None)
    video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
    assert int(video["nb_frames"]) == 45
    assert video["width"] == 1080 and video["height"] == 1920


def test_clock_records_source_beats_and_original_anchor_status():
    from ecom_video.delivery_timeline import timeline_record

    snap = {
        "script": "看袖口",
        "assets": [{"id": "a", "sha256": "a" * 64, "name": "实拍"}],
        "provenance": {"scenes": [{"text": "看袖口", "fact_ids": ["f1"]}]},
    }
    scene = {
        "shot_id": "s1",
        "start": 0,
        "end": 2,
        "frames": 60,
        "asset_id": "a",
        "source_in": 1,
        "duration": 2,
        "caption_layout": [{"text": "看袖口", "start": 0.2, "end": 1.1}],
    }
    alignment = {
        "sentences": [{"words": [{"text": "看", "start": 0.2, "end": 0.5, "anchored": False}]}]
    }
    record = timeline_record(snap, {"narration": {"asset_id": None}}, [scene], alignment)
    assert record["total_frames"] == 60
    assert record["shots"][0]["fact_ids"] == ["f1"]
    assert record["shots"][0]["words"][0]["anchored"] is False
    assert record["shots"][0]["captions"][0]["start_sample"] == 9600
    assert json.dumps(record, ensure_ascii=False)
