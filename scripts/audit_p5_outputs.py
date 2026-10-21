"""Measure delivered files, not normalization targets; no human approval claim."""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "docs/evidence/p5/release"
out.mkdir(exist_ok=True)
measurements = []
contact = Image.new("RGB", (1080, 4 * 540 + 45), "#eeeae1")
for col, style in enumerate(["editorial", "quiet", "collage"]):
    folder = ROOT / "examples/p5" / style
    shotbook = json.loads((folder / "shotbook.json").read_text())
    for row, shot in enumerate(shotbook["shots"]):
        frame = out / f"{style}-{row + 1}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str((shot["start"] + shot["end"]) / 2),
                "-i",
                str(folder / "output.mp4"),
                "-frames:v",
                "1",
                str(frame),
            ],
            check=True,
        )
        im = Image.open(frame).convert("RGB")
        im.thumbnail((360, 540))
        contact.paste(im, (col * 360 + (360 - im.width) // 2, row * 540 + 45))
    for name in ["output.mp4", "voice-only.mp4"]:
        file = folder / name
        if not file.exists():
            continue
        r = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(file),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data, _ = json.JSONDecoder().raw_decode(r.stderr[r.stderr.rfind("{") :])
        measurements.append(
            {
                "file": str(file.relative_to(ROOT)),
                "integrated_lufs": float(data["input_i"]),
                "true_peak_dbtp": float(data["input_tp"]),
                "loudness_range_lu": float(data["input_lra"]),
            }
        )
for col, style in enumerate(["editorial", "quiet", "collage"]):
    ImageDraw.Draw(contact).text((col * 360 + 30, 12), style, fill="black")
contact.save(out / "contact-sheet.jpg", quality=90)
(out / "audio-measurements.json").write_text(json.dumps(measurements, indent=2))
print(json.dumps(measurements, indent=2))
