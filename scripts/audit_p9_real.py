"""Read-only preservation and actual film checks; never implies customer approval."""

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p9"
s = json.loads((OUT / "run.json").read_text())
v = s.get("final_video", s["video"])
probe = json.loads(
    subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", v]
    )
)
(OUT / "film-probe.json").write_text(json.dumps(probe, indent=2))
subprocess.run(
    ["ffmpeg", "-v", "error", "-i", v, "-f", "null", "-"],
    check=True,
    stderr=(OUT / "film-decode.log").open("w"),
)
with (OUT / "film-signal.log").open("w") as log:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            v,
            "-af",
            "astats=metadata=0:reset=0",
            "-vf",
            "blackdetect=d=0.12:pix_th=0.05",
            "-f",
            "null",
            "-",
        ],
        check=True,
        stderr=log,
    )
frames = []
for i, t in enumerate([0.7, 2.5, 4.3, 6.3, 8.5, 11]):
    p = OUT / f"film-{i}.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(t),
            "-i",
            v,
            "-frames:v",
            "1",
            "-vf",
            "scale=270:480",
            str(p),
        ],
        check=True,
    )
    frames.append((p, t))
canvas = Image.new("RGB", (810, 1020), "#151515")
draw = ImageDraw.Draw(canvas)
for i, (p, t) in enumerate(frames):
    x = (i % 3) * 270
    y = (i // 3) * 510
    canvas.paste(Image.open(p), (x, y))
    draw.text((x + 8, y + 486), f"{t:.1f}s", fill="white")
canvas.save(OUT / "film-contact.jpg")
before = json.loads((OUT / "before.json").read_text())
with sqlite3.connect(ROOT / "var/workflow.db") as db:
    jobs = {r[0] for r in db.execute("select id from jobs")}
    counts = {
        table: db.execute("select count(*) from " + table).fetchone()[0]
        for table in before["platform_counts"]
    }
unchanged = {
    name: hashlib.sha256((ROOT / "var" / name).read_bytes()).hexdigest() == sha
    for name, sha in before["videos"].items()
}
assert all(unchanged.values())
assert set(before["jobs"]) <= jobs
assert counts == before["platform_counts"]
stream = next(st for st in probe["streams"] if st["codec_type"] == "video")
assert (stream["width"], stream["height"], stream["r_frame_rate"]) == (1080, 1920, "30/1")
assert any(st["codec_type"] == "audio" for st in probe["streams"])
assert not (OUT / "film-decode.log").read_text().strip()
report = {
    "video": v,
    "duration": probe["format"]["duration"],
    "dimensions": [1080, 1920],
    "fps": 30,
    "decode_errors": False,
    "old_jobs_preserved": len(before["jobs"]),
    "old_video_hashes_preserved": len(unchanged),
    "platform_counts": counts,
    "human_review": "pending",
    "voice": "synthetic; no human listening claim",
}
(OUT / "preservation-and-qc.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
