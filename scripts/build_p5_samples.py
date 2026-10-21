"""Explicit fictional acceptance fixtures, never customer approval or platform actions."""

import json
import math
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.alignment import AlignmentService  # noqa: E402
from ecom_video.creative import Brief, recommend  # noqa: E402
from ecom_video.db import Store  # noqa: E402
from ecom_video.media import digest, inspect_media  # noqa: E402
from ecom_video.storyboard import default_board  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "var/p5-acceptance"
root.mkdir(parents=True, exist_ok=True)
store = Store(root / "workflow.db")
service = AlignmentService(root, store, recover=False)
out = ROOT / "examples/p5"
out.mkdir(parents=True, exist_ok=True)
script = "一只杯子，留一点日常的从容。\n奶白杯身，深色杯盖。\n靠近一点，看清外观细节。\n把简洁，放进你的日常。"
(out / "script.txt").write_text(script)
voice = out / "narration.wav"
if not voice.exists():
    subprocess.run(
        [
            "say",
            "-v",
            "Tingting",
            "-r",
            "205",
            "-f",
            str(out / "script.txt"),
            "-o",
            str(out / "narration.aiff"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(out / "narration.aiff"),
            "-ar",
            "48000",
            "-ac",
            "2",
            str(voice),
        ],
        check=True,
    )


def add(job, path, kind):
    aid = uuid.uuid4().hex
    rel = f"jobs/{job['id']}/assets/{aid}{path.suffix}"
    dest = root / rel
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


reports = []
for wanted in ["editorial", "quiet", "collage"]:
    title = "【P5 fixture】随行杯 · " + wanted + (" · " + sys.argv[2] if len(sys.argv) > 2 else "")
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
        ids = []
        for name in ["hero", "detail", "lifestyle"]:
            ids.append(add(job, ROOT / f"examples/p4/assets/{name}.png", "image"))
        aid = add(job, voice, "audio")
        music = add(job, ROOT / "examples/p4/assets/ambient-original.wav", "audio")
        job = store.get(job["id"])
        ar = service.start(job["id"], aid)
        while ar["status"] == "running":
            time.sleep(1)
            ar = service.get(job["id"], ar["id"])
        if ar["status"] != "needs_review":
            raise RuntimeError(ar)
        # Acceptance automation is visibly identified. This is NOT human listening approval.
        ar = service.confirm(
            job["id"], ar["id"], None, "AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL"
        )
        board = default_board(job)
        brief = Brief(category="家居 日常", audience="生活场景", tone="安静 活泼 精致")
        recs = recommend(job, brief)
        choice = next(x for x in recs["options"] if x["id"] == wanted)
        board["creative"] = {
            "brief": recs["brief"],
            "fingerprint": recs["fingerprint"],
            "style_id": wanted,
            "brand": {
                "name": "日常 / DAILY OBJECTS",
                "paper": choice["colors"][0],
                "ink": choice["colors"][1],
                "accent": choice["colors"][2],
                "subtitle_size": 64,
            },
            "alignment_id": ar["id"],
            "sfx": True,
        }
        board["sample"] = True
        board["style"] = choice["family"]
        board["music_id"] = music
        board["narration"].update(mode="uploaded", asset_id=aid)
        ends = (
            [0]
            + [round(s["start"] * 30) / 30 for s in ar["result"]["sentences"][1:]]
            + [math.ceil(inspect_media(voice, "audio")["duration"] * 30) / 30]
        )
        for i, s in enumerate(board["shots"]):
            s.update(
                shot_id=f"shot-{i + 1:03d}",
                asset_id=ids[[0, 1, 1, 2][i]],
                duration=ends[i + 1] - ends[i],
                motion=["push", "pan_left", "pull", "push"][i],
                fit="cover",
                headline=["日常的从容", "奶白杯身", "外观细节", "放进你的日常"][i],
            )
        store.save_storyboard(job["id"], board, 0)
        store.submit(job["id"])
    job = store.get(job["id"])
    if job["status"] == "failed":
        store.retry(job["id"])
    if "--server" in sys.argv:
        deadline = time.monotonic() + 600
        while store.get(job["id"])["status"] in ("queued", "validating", "rendering", "auditing"):
            if time.monotonic() > deadline:
                raise RuntimeError("sample wait timeout")
            time.sleep(1)
    else:
        while store.get(job["id"])["status"] == "queued":
            Worker(root).run_once()
    job = store.get(job["id"])
    if job["status"] != "needs_review":
        raise RuntimeError(job.get("error"))
    folder = out / wanted
    folder.mkdir(exist_ok=True)
    for a in job["artifacts"]:
        shutil.copyfile(root / a["path"], folder / Path(a["path"]).name)
    reports.append(
        {
            "style": wanted,
            "job_id": job["id"],
            "status": job["status"],
            "video": str(folder / "output.mp4"),
            "cache": json.loads((folder / "manifest.json").read_text())["cache"],
        }
    )
    (out / "jobs.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print(reports[-1], flush=True)
