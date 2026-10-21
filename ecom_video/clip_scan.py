"""Measured scene boundaries and bounded keyframes; no generated footage."""

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .media import input_options, run_checked

VERSION = "ffmpeg-cuts-025-v3"
MAX_SEGMENTS = 8


def windows(duration, cuts, limit=MAX_SEGMENTS):
    boundaries = sorted({0.0, duration, *[t for t in cuts if 0 < t < duration]})
    options = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        # Guard both sides of a detected cut; round inward to the renderer's frame grid.
        start = math.ceil((a + (0.1 if a else 0)) * 30) / 30
        end = math.floor((b - (0.1 if b < duration else 0)) * 30) / 30
        for x in np.arange(start, end, 12):
            y = min(float(x) + 15, end)
            if y - x >= 1:
                options.append({"start": round(float(x) * 30) / 30, "end": round(y * 30) / 30})
    # A continuous 15s take can hide a brief action between its two endpoint frames.
    # Keep the long view for 9–15s shots, alongside measured <=8s action views.
    refined = list(options)
    for span in options:
        if span["end"] - span["start"] > 8:
            for x in np.arange(span["start"], span["end"], 6):
                end = min(float(x) + 8, span["end"])
                if end - x >= 1:
                    refined.append({"start": round(float(x) * 30) / 30, "end": end})
    options = [{"start": a, "end": b} for a, b in sorted({(s["start"], s["end"]) for s in refined})]
    if len(options) > limit:
        long = [s for s in options if s["end"] - s["start"] > 8]
        short = [s for s in options if s["end"] - s["start"] <= 8]
        # Sampling a mixed list can accidentally retain only short views.
        # Reserve both lengths, then distribute spare slots to the other pool.
        nlong = min(len(long), (limit + 1) // 2)
        nshort = min(len(short), limit - nlong)
        nlong = min(len(long), limit - nshort)
        options = sorted(
            [
                pool[i]
                for pool, n in [(long, nlong), (short, nshort)]
                for i in np.linspace(0, len(pool) - 1, n, dtype=int)
            ],
            key=lambda s: (s["start"], s["end"]),
        )
    return options


def quality(images):
    values = []
    for path in images:
        with Image.open(path) as im:
            a = np.asarray(im.convert("L").resize((128, 128)), dtype=float)
        values.append(
            {
                "brightness": float(a.mean()),
                "contrast": float(a.std()),
                "edge_energy": float(
                    np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()
                ),
            }
        )
    blank = all(
        (x["brightness"] < 9 or x["brightness"] > 247) and x["contrast"] < 8 for x in values
    )
    return {
        "sampled_frames": values,
        "blank": blank,
        "method": "sampled_luma_and_edges_not_full_video_quality",
    }


def scan(path, kind, metadata, folder, check=lambda: None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cuts = []
    if kind == "video":
        result = run_checked(
            [
                "ffmpeg",
                "-v",
                "info",
                *input_options(path),
                "-i",
                str(path),
                "-an",
                "-vf",
                "scale=160:-2,select='gt(scene,0.25)',showinfo",
                "-fps_mode",
                "vfr",
                "-f",
                "null",
                "-",
            ],
            check,
            timeout=180,
            capture=True,
        )
        cuts = [float(v) for v in re.findall(r"pts_time:([0-9.]+)", result)]
        ranges = windows(metadata["duration"], cuts)
    else:
        ranges = [{"start": 0.0, "end": 0.0}]
    segments = []
    for i, r in enumerate(ranges):
        check()
        points = (
            [
                r["start"] + min(0.25, (r["end"] - r["start"]) / 4),
                r["end"] - min(0.25, (r["end"] - r["start"]) / 4),
            ]
            if kind == "video"
            else [0]
        )
        files = []
        for n, t in enumerate(points):
            file = folder / f"{i:02d}-{n}.jpg"
            if kind == "image":
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((640, 640))
                    im.save(file, quality=85)
            else:
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        *input_options(path),
                        "-ss",
                        str(t),
                        "-i",
                        str(path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=640:640:force_original_aspect_ratio=decrease",
                        str(file),
                    ],
                    check,
                    timeout=30,
                )
            if not file.is_file():
                raise ValueError("关键帧无法提取，请重新导出视频")
            files.append(file)
        segments.append(
            {
                **r,
                "id": f"clip-{i:02d}",
                "frames": [p.name for p in files],
                "sample_times": points,
                "quality": quality(files),
            }
        )
    uncovered = []
    position = 0.0
    if kind == "video":
        for r in ranges:
            if r["start"] > position:
                uncovered.append([position, r["start"]])
            position = max(position, r["end"])
        if position < metadata["duration"]:
            uncovered.append([position, metadata["duration"]])
    return {
        "uncovered_ranges": uncovered,
        "segments": segments,
        "cuts": cuts,
        "duration": metadata.get("duration"),
        "coverage": "sampled",
        "max_segments": MAX_SEGMENTS,
        "scan_version": VERSION,
    }
