"""Same fictional product, three distinct client discussion films. No human approval claim."""

import json
import math
import shutil
import subprocess
import sys
import time
import uuid
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.alignment import AlignmentService  # noqa: E402
from ecom_video.creative import Brief, recommend  # noqa: E402
from ecom_video.db import Store  # noqa: E402
from ecom_video.media import digest, inspect_media  # noqa: E402
from ecom_video.storyboard import default_board  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

DATA = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "var/p6-acceptance"
REV = sys.argv[2] if len(sys.argv) > 2 else "v1"
DATA.mkdir(parents=True, exist_ok=True)
store = Store(DATA / "workflow.db")
service = AlignmentService(DATA, store, recover=False)
OUT = ROOT / "examples/p6"
OUT.mkdir(parents=True, exist_ok=True)
SPECS = [
    {
        "style": "cinema",
        "format": "showcase",
        "title": "形与留白",
        "script": [
            "一只杯子，留一点日常的从容。",
            "深色杯盖，勾勒干净轮廓。",
            "奶白杯身，让配色简单一点。",
            "近看细节，远看整体。",
            "把简洁，放进你的日常。",
        ],
        "headlines": ["日常", "深色杯盖", "奶白杯身", "近看细节", "放进你的日常"],
        "durations": [5.4, 3, 3, 3, 4],
        "assets": [0, 1, 0, 1, 2],
        "treatments": ["hero", "macro", "split", "context", "end"],
        "focus": [0.5, 0.22, 0.66, 0.6, 0.5],
    },
    {
        "style": "social",
        "format": "recommendation",
        "title": "桌边的一刻",
        "script": [
            "桌上少一点杂乱，会是什么感觉？",
            "让一只简单的杯子，融入你的桌边日常。",
            "奶白杯身配深色杯盖，颜色不用太多。",
            "先看看杯盖，感受深色和奶白的搭配。",
            "如果你也喜欢简洁，可以再了解它的细节。",
        ],
        "headlines": ["少一点杂乱", "桌边日常", "颜色不用太多", "看看杯盖", "喜欢简洁"],
        "assets": [2, 0, 1, 1, 2],
        "treatments": ["hero", "context", "split", "macro", "end"],
        "focus": [0.5, 0.5, 0.5, 0.24, 0.5],
    },
    {
        "style": "lab",
        "format": "narrated",
        "title": "先看细节",
        "script": [
            "看一只杯子，你会先看哪里？",
            "先看杯盖，深色轮廓和开口都在这里。",
            "再看杯身，奶白色和深色形成对比。",
            "拉远一点，看它放在桌上的整体感觉。",
            "这些是外观细节，实际规格请查看商品说明。",
        ],
        "headlines": ["先看哪里", "深色轮廓", "奶白色", "整体感觉", "外观细节"],
        "assets": [0, 1, 0, 2, 0],
        "treatments": ["hero", "macro", "split", "context", "end"],
        "focus": [0.5, 0.2, 0.66, 0.5, 0.5],
    },
]


def upload(job, path, kind):
    aid = uuid.uuid4().hex
    rel = f"jobs/{job['id']}/assets/{aid}{path.suffix}"
    dest = DATA / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    store.add_asset(
        job["id"],
        {
            "id": aid,
            "name": path.name,
            "path": rel,
            "kind": kind,
            "sha256": digest(dest),
            "size": dest.stat().st_size,
            "metadata": inspect_media(dest, kind),
        },
    )
    return aid


def music(path, duration, style):
    rate = 48000
    t = np.arange(round(duration * rate)) / rate
    audio = np.zeros_like(t)
    # Original restrained harmonic bed. Not a beat-synced advertisement claim.
    notes = {
        "cinema": [130.81, 164.81, 196, 246.94],
        "social": [174.61, 220, 261.63, 329.63],
        "lab": [146.83, 185, 220, 293.66],
    }[style]
    step = {"cinema": 1.5, "social": 0.75, "lab": 1.2}[style]
    for i, at in enumerate(np.arange(0, duration, step)):
        phase = t - at
        mask = phase >= 0
        u = np.maximum(phase, 0)
        freq = notes[i % 4]
        audio += (
            0.06
            * mask
            * np.minimum(1, u / 0.02)
            * np.exp(-u / 1.7)
            * (np.sin(2 * np.pi * freq * u) + 0.22 * np.sin(2 * np.pi * freq * 2 * u))
        )
    audio *= np.minimum(1, t / 0.6) * np.minimum(1, np.maximum(0, duration - t) / 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat((audio * 32767).astype("<i2")[:, None], 2, axis=1).tobytes())


def voice(path, lines):
    rate = 48000
    parts = [np.zeros(round(0.18 * rate), dtype="<i2")]
    for i, line in enumerate(lines):
        text = path.parent / f"line-{i}.txt"
        text.write_text(line)
        aiff = path.parent / f"line-{i}.aiff"
        wav = path.parent / f"line-{i}.wav"
        subprocess.run(
            ["say", "-v", "Tingting", "-r", "185", "-f", str(text), "-o", str(aiff)], check=True
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(aiff),
                "-ar",
                str(rate),
                "-ac",
                "1",
                str(wav),
            ],
            check=True,
        )
        with wave.open(str(wav), "rb") as w:
            parts.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))
        parts.append(np.zeros(round((0.4 if i < len(lines) - 1 else 1.25) * rate), dtype="<i2"))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate(parts).tobytes())


reports = []
for spec in SPECS:
    style = spec["style"]
    folder = OUT / style
    folder.mkdir(exist_ok=True)
    script = "\n".join(spec["script"])
    (folder / "script.txt").write_text(script)
    title = f"【P6 示例】随行杯 · {spec['title']} · {REV}"
    old = next(
        (
            j
            for j in store.list_jobs()
            if j["title"] == title and j["status"] in ("needs_review", "queued", "failed")
        ),
        None,
    )
    if old:
        job = store.get(old["id"])
    else:
        job = store.create_job(title, script, 5)
        ids = [
            upload(job, ROOT / f"examples/p4/assets/{name}.png", "image")
            for name in ["hero", "detail", "lifestyle"]
        ]
        alignment = None
        if spec["format"] != "showcase":
            voice_path = folder / "narration.wav"
            voice_script = folder / "narration-script.txt"
            if (
                not voice_path.exists()
                or not voice_script.exists()
                or voice_script.read_text() != script
            ):
                voice(voice_path, spec["script"])
                voice_script.write_text(script)
            aid = upload(job, voice_path, "audio")
            alignment = service.start(job["id"], aid)
            while alignment["status"] == "running":
                time.sleep(0.5)
                alignment = service.get(job["id"], alignment["id"])
            if alignment["status"] != "needs_review":
                raise RuntimeError(alignment)
            alignment = service.confirm(
                job["id"], alignment["id"], None, "AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL"
            )
            ends = (
                [0]
                + [round(s["start"] * 30) / 30 for s in alignment["result"]["sentences"][1:]]
                + [math.ceil(inspect_media(voice_path, "audio")["duration"] * 30) / 30]
            )
            durations = [b - a for a, b in zip(ends, ends[1:], strict=False)]
        else:
            durations = spec["durations"]
        bgm = folder / "music-original.wav"
        music(bgm, sum(durations), style)
        mid = upload(job, bgm, "audio")
        job = store.get(job["id"])
        board = default_board(job)
        rec = recommend(
            job,
            Brief(
                format=spec["format"],
                category="家居 随行杯",
                audience="办公与生活场景",
                tone="简洁 自然",
            ),
        )
        choice = next(s for s in rec["options"] if s["id"] == style)
        board["creative"] = {
            "brief": rec["brief"],
            "fingerprint": rec["fingerprint"],
            "style_id": style,
            "brand": {
                "name": "日常 / EVERYDAY",
                "paper": choice["colors"][0],
                "ink": choice["colors"][1],
                "accent": choice["colors"][2],
                "subtitle_size": 64,
            },
            "sfx": True,
            "alignment_id": alignment["id"] if alignment else None,
        }
        board["sample"] = True
        board["style"] = choice["family"]
        board["music_id"] = mid
        board["music_db"] = -26 if alignment else -18
        board["narration"].update(
            mode="uploaded" if alignment else "silent", asset_id=aid if alignment else None
        )
        for i, shot in enumerate(board["shots"]):
            shot.update(
                shot_id=f"{style}-{i + 1}",
                asset_id=ids[spec["assets"][i]],
                duration=durations[i],
                headline=spec["headlines"][i],
                treatment=spec["treatments"][i],
                transition="wipe" if i in (1, 2) else "cut",
                motion="static" if i == 4 else ["push", "pull", "pan_left", "push"][i % 4],
                fit="cover",
                focus_y=spec["focus"][i],
                role="detail" if i in (1, 2) else "lifestyle" if i == 3 else "product",
            )
        store.save_storyboard(job["id"], board, 0)
        store.submit(job["id"])
    if store.get(job["id"])["status"] == "failed":
        store.retry(job["id"])
    if "--server" in sys.argv:
        deadline = time.monotonic() + 900
        while store.get(job["id"])["status"] in ("queued", "validating", "rendering", "auditing"):
            if time.monotonic() > deadline:
                raise RuntimeError("render timeout")
            time.sleep(1)
    else:
        while store.get(job["id"])["status"] == "queued":
            Worker(DATA).run_once()
    job = store.get(job["id"])
    if job["status"] != "needs_review":
        raise RuntimeError(job.get("error"))
    for a in job["artifacts"]:
        shutil.copyfile(DATA / a["path"], folder / Path(a["path"]).name)
    report = {
        "style": style,
        "format": spec["format"],
        "job_id": job["id"],
        "status": job["status"],
        "duration": json.loads((folder / "qc.json").read_text())["duration"],
        "video": str(folder / "output.mp4"),
    }
    reports.append(report)
    (OUT / "jobs.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print(report, flush=True)
