"""Decode delivered frames and audio; distinguish measured technical checks from human review."""

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "docs/evidence/p6/final"
out.mkdir(parents=True, exist_ok=True)
results = []
for style in ["cinema", "social", "lab"]:
    folder = ROOT / "examples/p6" / style
    manifest = json.loads((folder / "manifest.json").read_text())
    shots = manifest["scenes"]
    contact = Image.new("RGB", (1080, 5 * 640 + 40), "#deddd7")
    draw = ImageDraw.Draw(contact)
    draw.text((30, 12), style, fill="black")
    for row, s in enumerate(shots):
        # Entry, dominant motion / spoken headline, then final hold.
        samples = [
            min(s["frames"] - 1, 15),
            min(
                s["frames"] - 1,
                115 if style == "cinema" and row == 0 else round(s["frames"] * 0.55),
            ),
            max(0, s["frames"] - 20),
        ]
        for col, frame in enumerate(samples):
            at = s["start"] + frame / 30
            p = out / f"{style}-shot{row + 1}-f{round(at * 30):04d}.png"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(at),
                    "-i",
                    str(folder / "output.mp4"),
                    "-frames:v",
                    "1",
                    str(p),
                ],
                check=True,
            )
            im = Image.open(p).convert("RGB")
            im.thumbnail((360, 640))
            contact.paste(im, (col * 360, row * 640 + 40))
    contact.save(out / f"{style}-contact.jpg", quality=90)
    measurements = []
    for name in ["output.mp4", "voice-only.mp4"]:
        r = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(folder / name),
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
                "file": name,
                "integrated_lufs": float(data["input_i"]),
                "true_peak_dbtp": float(data["input_tp"]),
            }
        )
    # BGM and no-BGM versions must carry identical encoded video packets.
    hashes = []
    for name in ["output.mp4", "voice-only.mp4"]:
        r = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(folder / name),
                "-map",
                "0:v:0",
                "-c",
                "copy",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        hashes.append(r.stdout.strip())
    assert hashes[0] == hashes[1]
    # Match final AAC audio to the actual pre-encode clean track. Tests pipeline offset, not ASR accuracy.
    job_id = manifest["job_id"]
    attempts = list((ROOT / "var/p6-acceptance/jobs" / job_id).glob("attempt-*"))
    lag = None
    if attempts:
        source = next(p / "clean.wav" for p in attempts if (p / "clean.wav").exists())
        arrays = []
        for source_audio in [source, folder / "voice-only.mp4"]:
            r = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(source_audio),
                    "-ac",
                    "1",
                    "-ar",
                    "12000",
                    "-f",
                    "f32le",
                    "-",
                ],
                capture_output=True,
                check=True,
            )
            arrays.append(np.frombuffer(r.stdout, dtype="<f4"))
        a, b = arrays
        n = 1 << (len(a) + len(b) - 1).bit_length()
        corr = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
        window = np.r_[corr[-2400:], corr[:2401]]
        lag = (int(np.argmax(window)) - 2400) / 12000
        assert abs(lag) <= 0.1, lag
    # Both edges of each wipe are a matching solid plate. Record pixel difference.
    seams = []
    for s in shots[1:]:
        if s["transition"] != "wipe":
            continue
        pictures = []
        for frame in [round(s["start"] * 30) - 1, round(s["start"] * 30)]:
            file = out / f"{style}-seam-f{frame:04d}.png"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(frame / 30),
                    "-i",
                    str(folder / "output.mp4"),
                    "-frames:v",
                    "1",
                    str(file),
                ],
                check=True,
            )
            pictures.append(np.asarray(Image.open(file).convert("RGB"), dtype=float))
        seams.append(
            {
                "frame": round(s["start"] * 30),
                "mean_abs_rgb_difference": float(np.abs(pictures[0] - pictures[1]).mean()),
            }
        )
    results.append(
        {
            "style": style,
            "job_id": job_id,
            "duration": manifest["duration"],
            "audio": measurements,
            "music_versions_identical_video": True,
            "aac_offset_seconds": lag,
            "wipe_seams": seams,
            "human_listening_approval": False,
        }
    )
(out / "measurements.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
