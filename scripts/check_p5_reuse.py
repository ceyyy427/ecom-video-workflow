"""Real incremental rerender and second-product fixture (not human acceptance)."""

import copy
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402
from ecom_video.creative import Brief, recommend  # noqa: E402
from ecom_video.db import Store  # noqa: E402
from ecom_video.media import digest, inspect_media  # noqa: E402
from ecom_video.storyboard import default_board  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

root = ROOT / "var/p5-acceptance"
store = Store(root / "workflow.db")
sample_jobs = json.loads((ROOT / "examples/p5/jobs.json").read_text())
source = store.get(next(j["job_id"] for j in sample_jobs if j["style"] == "editorial"))
c = TestClient(create_app(root), base_url="http://localhost")
c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
clone = c.post(f"/api/jobs/{source['id']}/clone").json()
board = clone["storyboard"]
board["creative"] = copy.deepcopy(source["storyboard"]["creative"])
old = board["creative"]["alignment_id"]
aid = uuid.uuid4().hex
with store.transaction() as con:
    row = con.execute("SELECT * FROM alignments WHERE id=?", (old,)).fetchone()
    con.execute(
        "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
        (
            aid,
            clone["id"],
            row["fingerprint"],
            "confirmed",
            row["result"],
            None,
            "AUTOMATED FIXTURE — NOT HUMAN APPROVAL",
            time.time(),
            time.time(),
        ),
    )
board["creative"]["alignment_id"] = aid
board["shots"][0]["motion"] = "pull"
store.save_storyboard(clone["id"], board, clone["storyboard_revision"])
store.submit(clone["id"])
Worker(root).run_once()
result = store.get(clone["id"])
assert result["status"] == "needs_review", result.get("error")
manifest = json.loads(
    (root / next(a["path"] for a in result["artifacts"] if a["kind"] == "manifest")).read_text()
)
assert manifest["cache"] == {"hits": 3, "rendered": 1, "total": 4}, manifest["cache"]
report = {"incremental": {"job_id": result["id"], "cache": manifest["cache"]}}
# Original vector notebook illustration: tests new content, not photorealistic quality.
folder = ROOT / "examples/p5/notebook"
folder.mkdir(exist_ok=True)
im = Image.new("RGB", (1080, 1440), "#e6decd")
d = ImageDraw.Draw(im)
d.rounded_rectangle((270, 250, 820, 1190), 30, fill="#34393d")
d.rectangle((300, 250, 315, 1190), fill="#72716c")
d.line((740, 250, 740, 1190), fill="#171a1b", width=16)
im.save(folder / "notebook.png")
job = store.create_job("【P5 fixture】文具笔记本", "深色封面\n把想法留在纸上", 3)
asset = uuid.uuid4().hex
rel = f"jobs/{job['id']}/assets/{asset}.png"
(root / rel).parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(folder / "notebook.png", root / rel)
store.add_asset(
    job["id"],
    {
        "id": asset,
        "name": "notebook.png",
        "path": rel,
        "kind": "image",
        "sha256": digest(root / rel),
        "size": (root / rel).stat().st_size,
        "metadata": inspect_media(root / rel, "image"),
    },
)
job = store.get(job["id"])
board = default_board(job)
rec = recommend(job, Brief(category="文具 设计", tone="简洁"))
style = rec["options"][0]
assert style["id"] == "bauhaus"
board["creative"] = {
    "brief": rec["brief"],
    "fingerprint": rec["fingerprint"],
    "style_id": style["id"],
    "brand": {
        "name": "NOTE / 原创示意图",
        "paper": style["colors"][0],
        "ink": style["colors"][1],
        "accent": style["colors"][2],
    },
    "sfx": False,
}
board["sample"] = True
board["style"] = style["family"]
board["narration"]["mode"] = "local"
for i, s in enumerate(board["shots"]):
    s.update(
        shot_id=f"notebook-{i}",
        headline=["深色封面", "想法"][i],
        motion="push",
        fit="contain",
        duration=4,
    )
store.save_storyboard(job["id"], board, 0)
store.submit(job["id"])
Worker(root).run_once()
result = store.get(job["id"])
assert result["status"] == "needs_review", result.get("error")
for a in result["artifacts"]:
    shutil.copyfile(root / a["path"], folder / Path(a["path"]).name)
report["second_product"] = {
    "job_id": job["id"],
    "style": style["id"],
    "status": result["status"],
    "asset": "original vector illustration, not real product photograph",
}
(ROOT / "docs/evidence/p5/reuse.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(report)
