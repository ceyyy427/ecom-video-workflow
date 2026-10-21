"""Check the isolated material film/retake, without a browser or model call."""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from PIL import Image, ImageDraw

    from ecom_video.material_suitability import (
        complete_events,
        current_appearance,
        repeat_report,
        visible,
        visible_ranges,
    )
    from ecom_video.media import digest, safe_path
    from scripts.build_prompt_samples import pcm, pixels

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    data = args.data.resolve()
    evidence = args.evidence.resolve()
    assert not data.is_relative_to(ROOT)
    evidence.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    old = json.loads((data / "job.json").read_text())
    child = json.loads((data / "retake-job.json").read_text())

    def folder(job):
        return safe_path(
            runtime, next(a["path"] for a in job["artifacts"] if a["kind"] == "video")
        ).parent

    original, retake = folder(old), folder(child)
    parent = json.loads((original / "manifest.json").read_text())
    updated = json.loads((retake / "manifest.json").read_text())
    assert (
        old["status"] == child["status"] == "needs_review"
        and not old["reviews"]
        and not child["reviews"]
    )
    assert child["parent_id"] == old["id"]
    count = len(parent["scenes"])
    assert count == 5
    # An already rendered identical retake may hit all scenes. The pixel/byte
    # checks below still prove the requested first-shot change and untouched rest.
    assert updated["cache"]["total"] == count
    assert count - 1 <= updated["cache"]["hits"] <= count
    assert updated["cache"]["rendered"] == count - updated["cache"]["hits"]
    assert pixels(original / "scene-000.mp4") != pixels(retake / "scene-000.mp4")
    assert all(
        digest(original / f"scene-{i:03d}.mp4") == digest(retake / f"scene-{i:03d}.mp4")
        for i in range(1, count)
    )
    assert pcm(original / "output.mp4") == pcm(retake / "output.mp4")
    assert (original / "subtitles.srt").read_bytes() == (retake / "subtitles.srt").read_bytes()
    inherited = dict(updated["alignment"])
    assert (
        inherited.pop("inherited_from_alignment_id")
        == json.loads((data / "alignment-actual.json").read_text())["id"]
    )
    assert parent["alignment"] == inherited
    assert all(w["anchored"] for sent in parent["alignment"]["sentences"] for w in sent["words"])
    assets = {a["id"]: a for a in old["snapshot"]["assets"]}
    project = json.loads((data / "project-verified.json").read_text())
    reference = next(
        a["sha256"]
        for a in project["media"]
        if a["id"] == project["settings"]["product_reference_id"]
    )
    used = []
    selected = []
    action_delta = None
    for index, s in enumerate(parent["scenes"]):
        a = assets[s["asset_id"]]
        meta = a["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        assert a["kind"] in ("image", "video") and a["name"] not in ("other.mp4", "wide.mp4")
        candidates = [
            seg
            for seg in meta["content_analysis"]["segments"]
            if a["kind"] == "image" or seg["start"] <= s["source_in"] < seg["end"]
        ]
        motion = next(
            seg["motion_check"]
            for seg in candidates
            if (
                a["kind"] == "image"
                and current_appearance(
                    {"motion_check": seg["motion_check"], "asset_sha256": a["sha256"]}, reference
                )
                and any(visible(sample) for sample in seg["motion_check"]["samples"])
            )
            or any(
                r["start"] - 1e-6 <= s["source_in"]
                and s["source_in"] + s["frames"] / 30 <= r["end"] + 1e-6
                for r in visible_ranges(
                    {"motion_check": seg["motion_check"], "asset_sha256": a["sha256"]}, reference
                )
            )
        )
        c = {
            "asset_sha256": a["sha256"],
            "kind": a["kind"],
            "start": s["source_in"],
            "motion_check": motion,
        }
        repeat = repeat_report(c, s["frames"] / 30, used)
        assert repeat["overlap_seconds"] == 0
        used.append({**c, "duration": s["frames"] / 30})
        if index == 1:
            events = complete_events(c, "pour")
            event = next(
                e
                for e in events
                if s["source_in"] <= e["complete_start"]
                and e["complete_end"] <= s["source_in"] + s["frames"] / 30
            )
            assert any(
                w["basis"] == "analysis"
                and w["start"] <= event["complete_start"] - s["source_in"] + 1e-6
                and w["end"] >= event["complete_end"] - s["source_in"] - 1e-6
                for w in s["motion_plan"]["windows"]
            )
            spoken = next(
                w["start"]
                for w in parent["alignment"]["sentences"][index]["words"]
                if w["text"] == "倒"
            )
            action_delta = round(s["start"] + event["start"] - s["source_in"] - spoken, 4)
        for caption in s["caption_layout"]:
            assert caption["width"] <= 912 and len(caption["lines"]) <= 2
            assert caption["start"] >= -1 / 30 and caption["end"] <= s["frames"] / 30 + 1 / 30
        selected.append(
            {
                "shot": s["shot_id"],
                "file": a["name"],
                "kind": a["kind"],
                "sha256": a["sha256"],
                "source_in": s["source_in"],
                "source_end": s["source_in"] + s["frames"] / 30,
                "repeat_check": repeat,
            }
        )
    for target in (original, retake):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(target / "output.mp4"), "-f", "null", "-"],
            check=True,
        )
    frames = evidence / "frames"
    frames.mkdir(exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(original / "output.mp4"),
            "-vf",
            "fps=2,scale=216:384",
            str(frames / "%03d.jpg"),
        ],
        check=True,
    )
    files = sorted(frames.glob("*.jpg"))
    for offset in range(0, len(files), 12):
        batch = files[offset : offset + 12]
        sheet = Image.new("RGB", (4 * 226, math.ceil(len(batch) / 4) * 410), "#dddcd7")
        draw = ImageDraw.Draw(sheet)
        for i, file in enumerate(batch):
            x, y = (i % 4) * 226, (i // 4) * 410
            sheet.paste(Image.open(file), (x, y + 24))
            draw.text((x + 3, y + 4), f"{(offset + i) / 2:.1f}s", fill="black")
        sheet.save(evidence / f"film-grid-{offset // 12 + 1}.jpg")
    video_count = sum(s["kind"] == "video" for s in selected)
    assert video_count >= count - 1, "No slideshow acceptance: at most one actual image"
    result = {
        "duration": parent["duration"],
        "video_sha256": digest(original / "output.mp4"),
        "retake_sha256": digest(retake / "output.mp4"),
        "shots": selected,
        "video_shots": video_count,
        "image_shots": count - video_count,
        "same_source_overlap_seconds": 0,
        "sampled_flow_start_minus_spoken_word_seconds": action_delta,
        "retake_cache": updated["cache"],
        "other_four_byte_equal": True,
        "whole_audio_pcm_equal": True,
        "subtitles_byte_equal": True,
        "all_words_anchored": True,
        "caption_bounds_checked": True,
        "full_decode_checked": 2,
        "offline_frames": len(files),
        "human_review": "pending",
        "fixture_approvals_only": True,
        "no_automatic_distribution": True,
        "benchmark": "single stock group, not statistical accuracy",
    }
    (data / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (evidence / "render-acceptance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
