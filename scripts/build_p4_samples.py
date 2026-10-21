"""Reproducible fictional samples using the same Store/Worker pipeline as the UI.
Run: uv run python scripts/build_p4_samples.py --data var
No platform calls or approvals. Native macOS Tingting is needed for demo narration.
"""

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.db import Store  # noqa: E402
from ecom_video.media import digest, inspect_media  # noqa: E402
from ecom_video.storyboard import default_board  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

SAMPLES = [
    (
        "premium",
        "01 · 质感展示",
        [
            "一只杯子，留一点日常的从容。",
            "奶白杯身，深色杯盖。",
            "靠近一点，看清外观细节。",
            "把简洁，放进你的日常。",
        ],
        ["hero", "detail", "hero", "lifestyle"],
        ["push", "pan_left", "pull", "push"],
    ),
    (
        "demo",
        "02 · 功能与细节演示",
        [
            "选杯子，先把细节看清。",
            "杯口与杯盖，近距离展示。",
            "从整体，再看到局部。",
            "选购前，请核对实际规格。",
        ],
        ["hero", "take", "detail", "hero"],
        ["static", "static", "push", "pull"],
    ),
    (
        "lifestyle",
        "03 · 场景转化",
        [
            "忙碌的桌面，留一个小角落。",
            "让喝水，成为日常的停顿。",
            "简单的搭配，自然融入。",
            "你的桌面，想留给哪种风格？",
        ],
        ["lifestyle", "detail", "lifestyle", "hero"],
        ["pan_right", "push", "pull", "push"],
    ),
]


def music(path):
    """Original procedural ambient bed, no borrowed recordings or melodies."""
    rate = 24000
    seconds = 24
    data = bytearray()
    chords = [
        (130.81, 164.81, 196),
        (110, 130.81, 164.81),
        (87.31, 110, 130.81),
        (98, 123.47, 146.83),
    ]
    for n in range(rate * seconds):
        t = n / rate
        beat = t % 6
        env = min(1, beat / 0.7, (6 - beat) / 0.9)
        pad = (
            sum(
                math.sin(2 * math.pi * f * t) + 0.18 * math.sin(2 * math.pi * f * 2 * t)
                for f in chords[int(t / 6)]
            )
            / 4
        )
        chime = math.sin(2 * math.pi * 523.25 * t) * math.exp(-4 * (t % 1.5)) * 0.13
        value = max(-1, min(1, 0.17 * env * pad + chime * 0.1))
        data.extend(struct.pack("<h", int(value * 32767)))
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="var")
    args = parser.parse_args()
    data = Path(args.data).resolve()
    store = Store(data / "workflow.db")
    assets = ROOT / "examples/p4/assets"
    bgm = assets / "ambient-original.wav"
    if not bgm.exists():
        music(bgm)
    take = assets / "detail-take.mp4"
    if not take.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(assets / "detail.png"),
                "-vf",
                "scale=1080:1920,zoompan=z='1+on/240*0.08':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30",
                "-t",
                "8",
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "19",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                str(take),
            ],
            check=True,
        )
    report = []
    for style, title, lines, keys, motions in SAMPLES:
        fulltitle = "【P4 示例】随行杯 · " + title
        existing = next(
            (
                j
                for j in store.list_jobs()
                if (j["title"] == fulltitle or j["title"].startswith(fulltitle + " · "))
                and j["status"] in ("needs_review", "ready", "failed", "queued")
            ),
            None,
        )
        if existing:
            job = store.get(existing["id"])
        else:
            job = store.create_job(fulltitle, "\n".join(lines), 5)
            mapping = {}
            for name, path, kind in [
                ("hero", assets / "hero.png", "image"),
                ("detail", assets / "detail.png", "image"),
                ("lifestyle", assets / "lifestyle.png", "image"),
                ("take", take, "video"),
                ("music", bgm, "audio"),
            ]:
                aid = uuid.uuid4().hex
                relative = f"jobs/{job['id']}/assets/{aid}{path.suffix}"
                target = data / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                store.add_asset(
                    job["id"],
                    {
                        "id": aid,
                        "name": f"示例-{path.name}",
                        "path": relative,
                        "kind": kind,
                        "sha256": digest(target),
                        "size": target.stat().st_size,
                        "metadata": inspect_media(target, kind),
                    },
                )
                mapping[name] = aid
            job = store.get(job["id"])
            board = default_board(job)
            board.update(style=style, sample=True, music_id=mapping["music"], music_db=-26)
            board["narration"].update(mode="local", asset_id=None, rate=220)
            for shot, key, motion in zip(board["shots"], keys, motions, strict=True):
                shot.update(
                    asset_id=mapping[key],
                    duration=5,
                    motion=motion,
                    fit="cover",
                    source_in=2 if key == "take" else 0,
                )
            store.save_storyboard(job["id"], board, 0)
            store.submit(job["id"])
        worker = Worker(data)
        if job["status"] == "failed":
            store.retry(job["id"])
        while store.get(job["id"])["status"] == "queued":
            worker.run_once()
        job = store.get(job["id"])
        assert job["status"] in ("needs_review", "ready"), job["error"]
        out = ROOT / "examples/p4" / style
        out.mkdir(exist_ok=True)
        for a in job["artifacts"]:
            if a["kind"] in ("video", "video_clean", "subtitles", "manifest", "qc"):
                shutil.copyfile(data / a["path"], out / Path(a["path"]).name)
        report.append(
            {
                "style": style,
                "job_id": job["id"],
                "status": job["status"],
                "video": str(out / "output.mp4"),
            }
        )
        print(json.dumps(report[-1], ensure_ascii=False), flush=True)
        (ROOT / "examples/p4/jobs.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    sources = {
        "fictional": True,
        "images": "Built-in image_gen, generated 2026-10-14; see ASSETS.md for prompts; no real product claim",
        "voice": "macOS say / Tingting / local scene synthesis",
        "music": "Original procedural ambient audio from this script",
        "take": "Deterministic pan/zoom of generated detail.png; not filmed physical functionality",
        "files": {p.name: digest(p) for p in assets.iterdir() if p.is_file()},
    }
    (ROOT / "examples/p4/sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
