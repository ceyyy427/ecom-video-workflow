"""Offline checks for prompt films; no UI automation, provider or database access."""

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "examples/framing-demo/headphones/manifest.json"
    )
    parser.add_argument("--evidence", type=Path, default=ROOT / "docs/evidence/prompt-direction")
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    receipts = json.loads((args.data / "acceptance.json").read_text())
    old = json.loads(args.baseline.read_text())
    frames = sum(s["frames"] for s in old["scenes"])
    results = {}
    for style in receipts:
        folder = args.data / style / "refined"
        manifest = json.loads((folder / "manifest.json").read_text())
        for scene, before in zip(manifest["scenes"], old["scenes"], strict=True):
            for key in ("asset_sha256", "source_in", "frames", "word_anchors", "text"):
                assert scene[key] == before[key], (style, scene["shot_id"], key)
            for c in scene["caption_layout"]:
                assert c["width"] <= 912 and len(c["lines"]) <= 2
                assert c["start"] >= -1 / 30 and c["end"] <= scene["frames"] / 30 + 1 / 30
        film = folder / "output.mp4"
        assert hashlib.sha256(film.read_bytes()).hexdigest() == receipts[style]["video_sha256"]
        info = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(film),
                ]
            )
        )
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"], v["r_frame_rate"], int(v["nb_frames"])) == (
            1080,
            1920,
            "30/1",
            frames,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(film),
                "-vf",
                f"fps=2,scale=180:320,tile=8x{math.ceil(manifest['duration'] * 2 / 8)}",
                "-frames:v",
                "1",
                str(evidence / (style + "-frames.jpg")),
            ],
            check=True,
        )
        results[style] = {
            "duration": float(info["format"]["duration"]),
            "frames": frames,
            "size": [1080, 1920],
            "original_assets_ranges_words_text_preserved": True,
            "caption_bounds_checked": True,
            "grid_sampling": "2fps from0; final black padding cells are not film frames",
            "human_listening": "pending",
            "human_review": "pending",
            "computer_use": False,
        }
    (evidence / "media-qc.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
