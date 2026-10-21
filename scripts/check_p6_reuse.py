"""Integration: scene edit reuses four clips; transition edit invalidates the adjoining clip."""

import copy
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402
from ecom_video.creative import recommend  # noqa: E402
from ecom_video.db import Store  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

root = ROOT / "var/p6-acceptance"
store = Store(root / "workflow.db")
source = store.get(
    next(
        j["job_id"]
        for j in json.loads((ROOT / "examples/p6/jobs.json").read_text())
        if j["style"] == "cinema"
    )
)
c = TestClient(create_app(root), base_url="http://localhost")
c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
results = []
for change in ["motion", "transition"]:
    clone = c.post(f"/api/jobs/{source['id']}/clone").json()
    board = clone["storyboard"]
    board["creative"] = copy.deepcopy(source["storyboard"]["creative"])
    board["creative"]["fingerprint"] = recommend(clone, board["creative"]["brief"])["fingerprint"]
    board["shots"][1][change] = "push" if change == "motion" else "iris"
    store.save_storyboard(clone["id"], board, clone["storyboard_revision"])
    store.submit(clone["id"])
    Worker(root).run_once()
    result = store.get(clone["id"])
    assert result["status"] == "needs_review", result.get("error")
    manifest = json.loads(
        (root / next(a["path"] for a in result["artifacts"] if a["kind"] == "manifest")).read_text()
    )
    expected = {
        "hits": 4 if change == "motion" else 3,
        "rendered": 1 if change == "motion" else 2,
        "total": 5,
    }
    assert manifest["cache"] == expected, manifest["cache"]
    results.append({"change": change, "job_id": clone["id"], "cache": manifest["cache"]})
(ROOT / "docs/evidence/p6/reuse.json").write_text(json.dumps(results, indent=2))
print(results)
