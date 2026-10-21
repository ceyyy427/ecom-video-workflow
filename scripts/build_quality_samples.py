"""Opt-in presentation comparison. Reuse licensed local clips/voice, never approve or call cloud."""

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.media import digest
    from ecom_video.remotion_renderer import render_remotion

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT):
        parser.error("Only a dedicated external rehearsal directory is allowed")
    results = []
    for style in ("cinema", "social", "lab"):
        folder = data / style
        original = json.loads((folder / "preview-job.json").read_text())
        job = copy.deepcopy(original)
        job["id"] = "quality-" + style
        job["snapshot"]["preview_only"] = True
        for shot in job["snapshot"]["storyboard"]["shots"]:
            shot["motion_plan"]["visual_finish"] = "polished-v1"
        before = copy.deepcopy(job["snapshot"]["alignment"])
        output = folder / "quality"
        output.mkdir()
        render_remotion(job, folder / "runtime", output, lambda: None)
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["alignment"] == before
        child = copy.deepcopy(job)
        child["id"] += "-single"
        target = 2
        child["snapshot"]["storyboard"]["shots"][target]["motion_plan"]["visual_finish"] = "legacy"
        retry = folder / "quality-single"
        retry.mkdir()
        render_remotion(child, folder / "runtime", retry, lambda: None)
        after = json.loads((retry / "manifest.json").read_text())
        count = len(manifest["scenes"])
        assert after["cache"] == {"hits": count - 1, "rendered": 1, "total": count}
        for i in range(count):
            if i != target:
                assert digest(output / f"scene-{i:03d}.mp4") == digest(retry / f"scene-{i:03d}.mp4")

        def pcm(path):
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-vn",
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            return hashlib.sha256(result.stdout).hexdigest()

        assert pcm(output / "output.mp4") == pcm(retry / "output.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(output / "output.mp4"), "-f", "null", "-"],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "1.5",
                "-i",
                str(output / "output.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(output / "poster.jpg"),
            ],
            check=True,
            timeout=30,
        )
        (folder / "quality-job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2))
        row = {
            "style": style,
            "seconds": sum(s["frames"] for s in manifest["scenes"]) / 30,
            "shots": count,
            "polished_titles": sum("visual_finish" in s for s in manifest["scenes"]),
            "emphasis_phrases": sum(
                bool(c.get("emphasis")) for s in manifest["scenes"] for c in s["caption_layout"]
            ),
            "retake_cache": after["cache"],
            "other_scene_bytes_equal": True,
            "decoded_pcm_equal": True,
            "alignment_unchanged": True,
            "video_sha256": digest(output / "output.mp4"),
            "status": "needs_review",
            "final_reviews": 0,
            "cloud_calls": 0,
            "platform_writes": 0,
        }
        (folder / "quality-acceptance.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2)
        )
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (data / "quality-acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
