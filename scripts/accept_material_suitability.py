"""Continue the licensed material rehearsal in an EXTERNAL directory.

Inputs/recognition receipts are kept separately; fixtures never approve a live project.
No new cloud synthesis, platform write or browser UI operation.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE — NOT HUMAN APPROVAL"


def main():
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.db import Store
    from ecom_video.worker import Worker

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--stage", choices=("prepare", "plan", "render", "retake"), required=True)
    ap.add_argument("--retake-request-id", default="material-checks-retake-0001")
    args = ap.parse_args()
    data = args.data.resolve()
    assert not data.is_relative_to(ROOT), "Never use the live repository or var/"
    runtime = data / "runtime"
    pid = json.loads((data / "documents-ready.json").read_text())["id"]
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_MEDIA_AUDIT"] = "0"
    client = TestClient(create_app(runtime), base_url="http://localhost")
    client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
    url = "/api/customer-projects/" + pid

    def save(name, value):
        (data / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def req(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        if not r.is_success:
            save("last-api-failure.json", {"path": path, "status": r.status_code, "body": r.json()})
        assert r.is_success, (path, r.text)
        return r.json()

    def current():
        return req("GET", url)

    p = current()
    if args.stage == "prepare":
        assert (data / "project-verified.json").is_file(), "Finish real recognition first"
        assert all(
            a["analysis"] and a["analysis"]["status"] == "ready" and not a.get("analysis_stale")
            for a in p["media"]
            if a["kind"] != "audio"
        )
        prod = p["product"]
        bundle = req(
            "POST",
            "/api/products/" + pid + "/scripts/alternatives",
            json={"revision": prod["revision"], "brief": p["settings"]["brief"]},
        )
        save("alternatives.json", bundle)
        p = req("POST", url + "/prepare", json={"revision": p["revision"]})
        save("prepared.json", p)
        voice = next(a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice")
        aid = req(
            "POST", "/api/jobs/" + p["job"]["id"] + "/alignments", json={"asset_id": voice["id"]}
        )["id"]
        deadline = time.monotonic() + 180
        while True:
            alignment = req("GET", "/api/jobs/" + p["job"]["id"] + "/alignments/" + aid)
            if alignment["status"] != "running":
                break
            assert time.monotonic() < deadline, "Local ASR exceeded bounded rehearsal wait"
            time.sleep(1)
        assert alignment["status"] == "needs_review", alignment.get("error")
        save("alignment-actual.json", alignment)
        req(
            "POST",
            "/api/jobs/" + p["job"]["id"] + "/alignments/" + aid + "/confirm",
            json={"confirmed": True, "reviewer": LABEL},
        )
        save("aligned-project.json", current())
    elif args.stage == "plan":
        assert p["alignment"]["status"] == "confirmed" and p["alignment"]["reviewer"] == LABEL
        save("preflight.json", req("GET", url + "/preflight"))
        save("recommendations.json", p["recommendations"])
        style = next(
            (
                o["id"]
                for o in p["recommendations"]["options"]
                if o["id"] in ("quiet", "collage", "editorial", "evidence", "lab")
            ),
            p["recommendations"]["options"][0]["id"],
        )
        p = req(
            "POST",
            url + "/plan",
            json={
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
                "style_id": style,
                "fingerprint": p["recommendations"]["fingerprint"],
                "alignment_id": p["alignment"]["id"],
            },
        )
        save("planned.json", p)
        save(
            "selection.json",
            {
                "notes": p["planning_notes"],
                "shots": p["job"]["storyboard"]["shots"],
                "fixture": LABEL,
                "human_review": "pending",
            },
        )
    elif args.stage == "render":
        req(
            "POST",
            url + "/submit",
            json={
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
            },
        )
        assert Worker(runtime).run_once()
        job = req("GET", "/api/jobs/" + p["job"]["id"])
        save("rendered-job.json", job)
        assert job["status"] == "needs_review", job.get("error")
        assert not job["reviews"]
        save("job.json", job)
    elif args.stage == "retake":
        from scripts.build_prompt_samples import variant_for

        old = json.loads((data / "job.json").read_text())
        assert old["id"] == p["job"]["id"] and p["job"]["status"] == "needs_review"
        shot = old["storyboard"]["shots"][0]
        old_card = shot.get("motion_plan", {}).get("prompt_card")
        changes = (
            {"motion_plan": {"prompt_card": variant_for(old_card)}}
            if old_card
            else {"headline": ""}
        )
        p = req(
            "POST",
            url + "/revise-shot",
            json={
                "revision": p["revision"],
                "job_id": old["id"],
                "board_revision": old["storyboard_revision"],
                "shot_id": shot["shot_id"],
                "request_id": args.retake_request_id,
                "changes": changes,
            },
        )
        req(
            "POST",
            url + "/submit",
            json={
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
            },
        )
        assert Worker(runtime).run_once()
        child = req("GET", "/api/jobs/" + p["job"]["id"])
        save("retake-job.json", child)
        assert child["status"] == "needs_review", child.get("error")
        assert (
            not child["reviews"]
            and Store(runtime / "workflow.db").get(old["id"])["storyboard"] == old["storyboard"]
        )
    print(args.stage + " complete in isolated fixture only; human listening/film review pending")


if __name__ == "__main__":
    main()
