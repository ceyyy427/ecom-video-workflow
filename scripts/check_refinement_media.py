"""Offline media checks only; no browser, provider or business state writes."""

import argparse
import json
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data", type=Path, required=True)
data = parser.parse_args().data.resolve()
evidence = root / "docs/evidence/huashu-category"
assert all((data / c / "refined/manifest.json").is_file() for c in ["headphones", "serum"]), (
    "Both completed films are required"
)
result = {}
for case in ["headphones", "serum"]:
    folder = data / case / "refined"
    if not (folder / "manifest.json").exists():
        continue
    manifest = json.loads((folder / "manifest.json").read_text())
    film = folder / "output.mp4"
    for s in manifest["scenes"]:
        for c in s["caption_layout"]:
            assert c["width"] <= 912 and len(c["lines"]) <= 2 and c["font_size"] >= 40
            assert c["start"] >= -1 / 30 and c["end"] <= s["frames"] / 30 + 1 / 30
            if c.get("emphasis"):
                p = c["emphasis"]
                assert (
                    p["basis"] == "anchored_words"
                    and c["start"] <= p["start"] < p["end"] <= c["end"]
                )
    info = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(film)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30/1")
    loud = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(film),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=90,
    )
    metrics = json.loads(re.findall(r"\{[^{}]+\}", loud.stderr)[-1])
    assert -17.5 <= float(metrics["input_i"]) <= -14.5 and float(metrics["input_tp"]) <= -1
    times = (
        [0.25, 0.75]
        + [(s["start"] + s["end"]) / 2 for s in manifest["scenes"]]
        + [manifest["scenes"][2]["start"] + x for x in [0.033, 0.133, 0.433]]
    )
    frames = sorted({round(t * 30) for t in times})
    select = "+".join("eq(n," + str(n) + ")" for n in frames)
    vf = "select='" + select + "',scale=270:480,tile=5x2"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(film),
            "-vf",
            vf,
            "-frames:v",
            "1",
            str(evidence / (case + "-frames.jpg")),
        ],
        check=True,
        timeout=60,
    )
    result[case] = {
        "duration": float(info["format"]["duration"]),
        "size": [v["width"], v["height"]],
        "frames": int(v["nb_frames"]),
        "loudness": metrics,
        "caption_width_and_lines_valid": True,
        "emphasis_within_original_caption": True,
        "caption_boundary_notes": [
            {
                "shot_id": s["shot_id"],
                "local_start": c["start"],
                "basis": "inherited word clock, less than one frame before cut; visible from frame0, anchors preserved",
            }
            for s in manifest["scenes"]
            for c in s["caption_layout"]
            if c["start"] < 0
        ],
        "frame_times": [n / 30 for n in frames],
        "coverage": "ten_selected_frames_plus_full_decode_and_audio_metrics; not continuous human viewing or listening",
    }
(evidence / "media-qc.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
