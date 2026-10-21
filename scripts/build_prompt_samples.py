"""Render three keyword-matched directions from an existing licensed, frozen job.

No provider, approval or database calls; only a NEW external rehearsal directory.
Original footage/narration/ranges remain intact. Never run browser UI automation.
"""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def pcm(path):
    return hashlib.sha256(
        subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-f",
                "s16le",
                "-",
            ]
        )
    ).hexdigest()


def variant_for(card_id):
    from ecom_video.prompt_catalog import CARDS

    original = CARDS[card_id]
    return next(
        key
        for key, card in CARDS.items()
        if card["recipe"] == original["recipe"] and card["presentation"] != original["presentation"]
    )


def pixels(path):
    return (
        subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-an",
                "-pix_fmt",
                "rgb24",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ]
        )
        .decode()
        .strip()
    )


def main():
    from ecom_video.creative import recommend
    from ecom_video.media import digest, inspect_media, safe_path
    from ecom_video.production_direction import choreography_for
    from ecom_video.prompt_catalog import apply_prompts
    from ecom_video.remotion_renderer import render_remotion

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Frozen job.json")
    parser.add_argument(
        "--runtime", type=Path, required=True, help="Original asset root, read only"
    )
    parser.add_argument("--data", type=Path, required=True, help="New external output directory")
    args = parser.parse_args()
    data = args.data.resolve()
    if data.exists() or data.is_relative_to(ROOT):
        parser.error("Use a new external rehearsal directory; never overwrite existing results")
    source = json.loads(args.source.read_text())["snapshot"]
    rec = recommend(source, source["storyboard"]["creative"]["brief"])
    data.mkdir(parents=True)
    results = {}
    for option in rec["options"]:
        style = option["id"]
        folder = data / style
        folder.mkdir()
        runtime = folder / "runtime"
        snap = copy.deepcopy(source)
        for a in snap["assets"]:
            original = safe_path(args.runtime.resolve(), a["path"])
            assert digest(original) == a["sha256"]
            target = safe_path(runtime, a["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            meta = json.loads(a["metadata"]) if isinstance(a["metadata"], str) else a["metadata"]
            a["metadata"] = {**meta, **inspect_media(target, a["kind"])}
        snap["preview_only"] = True
        board = snap["storyboard"]
        board["style"] = option["family"]
        c = board["creative"]
        c.update(style_id=style, fingerprint=rec["fingerprint"], production="narrative-v1")
        c["brand"].update(
            paper=option["colors"][0], ink=option["colors"][1], accent=option["colors"][2]
        )
        lines = snap["script"].splitlines()
        durations = [s["duration"] for s in board["shots"]]
        rows = choreography_for(lines, style, durations)
        # Existing action windows belong to the frozen narration/footage and remain guards.
        for row, old in zip(rows, board["shots"], strict=True):
            row["motion_plan"]["windows"] = copy.deepcopy(
                (old.get("motion_plan") or {}).get("windows", [])
            )
        rows = apply_prompts(
            rows,
            lines,
            durations,
            [next(a for a in snap["assets"] if a["id"] == s["asset_id"]) for s in board["shots"]],
            option["prompt_direction"],
            job=snap,
        )
        for s, row in zip(board["shots"], rows, strict=True):
            if row.get("clear_headline"):
                s["headline"] = ""
            s.update(
                shot_recipe=row["shot_recipe"],
                transition=row["transition"],
                motion_plan=row["motion_plan"],
            )
        job = {"id": "prompt-" + style, "snapshot": snap}
        save(folder / "job.json", job)
        save(folder / "recommendations.json", rec)
        out = folder / "refined"
        out.mkdir()
        render_remotion(job, runtime, out, lambda: None)
        current = json.loads((out / "manifest.json").read_text())
        assert current["alignment"] == source["alignment"]
        for a, b in zip(current["scenes"], source["storyboard"]["shots"], strict=True):
            assert a["source_in"] == b["source_in"] and a["frames"] == round(b["duration"] * 30)
        first = current["scenes"][0]
        assert (
            first["motion_decision"]["recipe"] == option["prompt_direction"]["cards"][0]["recipe"]
        ), first["motion_decision"]
        child = copy.deepcopy(job)
        child["id"] += "-single"
        old_id = child["snapshot"]["storyboard"]["shots"][0]["motion_plan"]["prompt_card"]
        variant = variant_for(old_id)
        child["snapshot"]["storyboard"]["shots"][0]["motion_plan"]["prompt_card"] = variant
        retry = folder / "single"
        retry.mkdir()
        render_remotion(child, runtime, retry, lambda: None)
        after = json.loads((retry / "manifest.json").read_text())
        total = len(board["shots"])
        assert after["cache"] == {"hits": total - 1, "rendered": 1, "total": total}
        assert pixels(out / "scene-000.mp4") != pixels(retry / "scene-000.mp4")
        assert all(
            digest(out / f"scene-{i:03d}.mp4") == digest(retry / f"scene-{i:03d}.mp4")
            for i in range(1, total)
        )
        assert pcm(out / "output.mp4") == pcm(retry / "output.mp4")
        for movie in (out / "output.mp4", retry / "output.mp4"):
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(movie), "-f", "null", "-"], check=True
            )
        result = {
            "style": style,
            "duration": current["duration"],
            "prompt_card": old_id,
            "primary_recipe": first["motion_decision"]["recipe"],
            "changed_to": variant,
            "cache": after["cache"],
            "unchanged_other_scenes": total - 1,
            "whole_audio_same": True,
            "executable_presentation_changed": True,
            "first_scene_decoded_pixels_different": True,
            "source_assets_ranges_words_preserved": all(
                a["word_anchors"] == b["word_anchors"]
                for a, b in zip(current["scenes"], after["scenes"], strict=True)
            ),
            "video_sha256": digest(out / "output.mp4"),
            "retake_sha256": digest(retry / "output.mp4"),
            "narration_sha256": digest(out / "narration.wav"),
            "human_review": "pending",
            "cloud_calls": 0,
            "platform_writes": 0,
        }
        save(folder / "acceptance.json", result)
        results[style] = result
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert len({r["primary_recipe"] for r in results.values()}) == 3
    assert len({r["narration_sha256"] for r in results.values()}) == 1
    save(data / "acceptance.json", results)


if __name__ == "__main__":
    main()
