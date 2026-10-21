"""Apply a disclosed visual-review correction through the public single-shot API.

The local models missed the desk/notebook match. This is an explicit operator
correction, not model output, and does not approve the final film for a customer.
"""

import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p8-live"
state = json.loads((OUT / "run.json").read_text())
with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=180) as c:
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    base = "/api/customer-projects/" + state["project_id"]

    def call(method, path, **kwargs):
        r = c.request(method, path, **kwargs)
        r.raise_for_status()
        return r.json()

    p = call("GET", base)
    if not state.get("corrected_job_id"):
        (OUT / "before-correction.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        video = next(a for a in p["media"] if a["kind"] == "video")
        candidate = video["analysis"]["result"]["segments"][0]
        correction = {
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
            "shot_id": "shot-004",
            "request_id": "p8-live-desk-correction-v1",
            "changes": {
                "media_id": video["id"],
                "source_in": candidate["start"],
                "treatment": "context",
            },
        }
        (OUT / "operator-correction.json").write_text(
            json.dumps(
                {
                    "operator": "Codex visual review, not human customer approval",
                    "reason": "第四句需要桌边笔记本场景；模型初选的静态商品图不合适。人工方式选取实际候选 clip-00。",
                    "request": correction,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        p = call("POST", base + "/revise-shot", json=correction)
        state["corrected_job_id"] = p["job"]["id"]
        (OUT / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    if p["job"]["status"] == "draft":
        p = call(
            "POST",
            base + "/submit",
            json={
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
            },
        )
    last = None
    start = time.monotonic()
    while p["job"]["status"] != "needs_review":
        status = p["job"]["status"]
        if status != last:
            print("RENDER", status, flush=True)
            last = status
        if status in ("failed", "cancelled", "blocked"):
            raise RuntimeError(p["job"].get("error"))
        if time.monotonic() - start > 900:
            raise TimeoutError("render")
        time.sleep(3)
        p = call("GET", base)
    state.update(
        status=p["job"]["status"],
        video=str(
            ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
        ),
        source_notice="Fictional product, animated stills, synthetic voice. Real model recognition/matching, explicit operator correction of shot 4. Customer review pending.",
    )
    (OUT / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    (OUT / "result.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
