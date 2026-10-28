"""Actual native preview -> customer API -> bounded Runtime -> render/edit/restore/export.

All manufactured confirmations are explicitly engineering fixtures in a fresh copy.
Use the installed application's interpreter and --application to verify a delivered copy.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "AUTOMATED FIXTURE native suite; not customer facts/listening/signoff"


def native_headline(job):
    return job["script"].splitlines()[0][:4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--simulate-confirmations", action="store_true")
    args = parser.parse_args()
    app = args.application.resolve()
    work = args.workspace.resolve()
    if (
        not args.simulate_confirmations
        or work.exists()
        or work.is_relative_to(app)
        or work.is_relative_to(ROOT)
    ):
        parser.error("必须使用全新仓库外工程目录并明确 --simulate-confirmations")
    sys.path.insert(0, str(app))
    import ecom_video

    assert Path(ecom_video.__file__).resolve().is_relative_to(app)
    from fastapi.testclient import TestClient

    from ecom_video.agent_runtime import Runtime
    from ecom_video.api import create_app
    from ecom_video.db import Store
    from ecom_video.maintenance import backup, restore, verify
    from ecom_video.media import digest, probe, safe_path
    from ecom_video.operations.resources import load_resources
    from ecom_video.operations.video_acceptance import measured_audio
    from ecom_video.worker import Worker

    os.environ.update(
        ECOM_AGENT_ENABLED="1",
        ECOM_AGENT_EXECUTION_ENABLED="1",
        ECOM_MEDIA_AUDIT="0",
        ECOM_QIANCHUAN_WRITES="0",
    )
    work.mkdir(mode=0o700)
    (work / ".engineering-only").write_text(LABEL + "\n")
    restore(args.bundle, work / "runtime")
    root = work / "runtime"
    store = Store(root / "workflow.db")
    with store.connect() as db:
        rows = db.execute(
            "SELECT id,basis,plan FROM idea_plans WHERE status='ready' ORDER BY created_at"
        ).fetchall()
    plans = [dict(row) | {"plan": json.loads(row["plan"])} for row in rows]
    plans = [p for p in plans if p["plan"].get("version") == "domestic-creative-v1"]
    assert len(plans) >= 2
    report = {
        "application": str(app),
        "fixture": LABEL,
        "customer_signoff": False,
        "voice_scope": "showcase silent-native bridge; narrated PCM/listening exercised by D2 replay and runtime tests",
        "cloud_calls": 0,
        "platform_writes": 0,
        "model_calls": 0,
        "cases": [],
        "resource_files": len(
            load_resources(
                project_root=app, lock_path=app / "docs/third-party/domestic-toolkit.lock.json"
            ).entries
        ),
    }

    with TestClient(create_app(root), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def request(method, url, body=None):
            r = c.request(method, "/api" + url, **({"json": body} if body is not None else {}))
            assert r.is_success, (method, url, r.status_code, r.text[:500])
            return r.json()

        def post(url, body):
            return request("POST", url, body)

        for index, row in enumerate(plans[:2]):
            started = time.perf_counter()
            pid = post(
                "/idea-plans/" + row["id"] + "/adopt",
                {"basis": row["basis"], "option_id": "dark-keynote"},
            )["id"]
            base = "/customer-projects/" + pid

            def current(base=base):
                return request("GET", base)

            def versions(p):
                return {
                    "revision": p["revision"],
                    "job_id": p["job"]["id"],
                    "board_revision": p["job"]["storyboard_revision"],
                }

            p = current()
            product = post(
                "/products/" + pid + "/facts/confirm",
                {
                    "revision": p["product"]["revision"],
                    "fact_ids": [f["id"] for f in p["product"]["facts"]],
                    "reviewer": LABEL,
                    "note": LABEL,
                    "confirmed": True,
                },
            )
            product = post(
                "/idea-plans/" + row["id"] + "/script",
                {"project_id": pid, "revision": product["revision"], "basis": row["basis"]},
            )
            # The script endpoint returns a product, not an implicit approval.
            assert product["status"] != "script_confirmed"
            post(
                "/products/" + pid + "/scripts/confirm",
                {
                    "revision": product["revision"],
                    "draft_id": product["current_draft_id"],
                    "reviewer": LABEL,
                    "note": LABEL,
                    "confirmed": True,
                    "seconds": 6,
                },
            )
            p = current()
            proposal = post(
                "/operations/executions/propose",
                {
                    "request_id": "native-fixture-" + str(index),
                    "plan_id": row["id"],
                    "plan_basis": row["basis"],
                    "option_id": "dark-keynote",
                    "project_id": pid,
                    "expected_revision": p["revision"],
                    "expected_product_revision": p["product"]["revision"],
                    "policy": {
                        "policy_id": "local-v1",
                        "max_steps": 40,
                        "max_elapsed_s": 1800,
                        "max_model_calls": 40,
                        "max_cost_cny": "0",
                    },
                },
            )
            rid = proposal["checkpoint_ref"]["id"]
            runtime = Runtime(root, store)

            def bound(runtime=runtime, rid=rid):
                e = runtime.get(rid)
                return {
                    "revision": e["revision"],
                    "plan_hash": e["plan_hash"],
                    "policy_id": "local-v1",
                }

            runtime.control(rid, "execute", bound())
            runtime.choose(
                rid,
                {
                    **bound(),
                    "style_id": "cinema",
                    "direction_basis": p["direction_basis"],
                    "reviewer": LABEL,
                    "confirmed": True,
                },
            )
            for _ in range(10):
                runtime.tick()
                if runtime.get(rid)["waiting_for"] == "storyboard":
                    break
            p = current()
            assert runtime.get(rid)["waiting_for"] == "storyboard", runtime.get(rid)
            assert p["job"]["status"] == "draft" and not p["delivery_reviews"]["storyboard"]
            assert c.post("/api/jobs/" + p["job"]["id"] + "/submit").status_code == 409

            def confirm_board(base=base, current=current):
                now = current()
                return post(
                    base + "/style-reviews",
                    {
                        "revision": now["revision"],
                        "stage": "storyboard",
                        "style_id": "cinema",
                        "basis": now["delivery_reviews"]["storyboard_basis"],
                        "reviewer": LABEL,
                        "confirmed": True,
                    },
                )

            confirm_board()
            runtime.control(rid, "resume", bound())
            runtime.tick()
            assert current()["job"]["status"] == "queued"
            assert Worker(root).run_once()
            runtime.tick()
            p = current()
            parent = p["job"]
            assert parent["status"] == "needs_review" and not parent["reviews"], parent["error"]
            assert runtime.get(rid)["waiting_for"] == "film_review"
            video = next(a for a in parent["artifacts"] if a["kind"] == "video")
            path = safe_path(root, video["path"])
            duration = float(probe(path)["format"]["duration"])
            assert 20 <= duration <= 30
            (work / f"native-{index}-parent.json").write_text(
                json.dumps(parent, ensure_ascii=False, indent=2)
            )
            headline = native_headline(parent)
            p = post(
                base + "/revise-shot",
                {
                    **versions(p),
                    "shot_id": parent["storyboard"]["shots"][0]["shot_id"],
                    "request_id": "native-single-shot-fixture-" + str(index),
                    "changes": {
                        "headline": headline,
                        "typography": {"mode": "contrast", "keyword": headline[-2:]},
                    },
                },
            )
            assert not p["delivery_reviews"]["storyboard"]
            confirm_board()
            p = current()
            post(base + "/submit", versions(p))
            assert Worker(root).run_once()
            child = current()["job"]
            assert child["status"] == "needs_review" and not child["reviews"], child["error"]
            child_video = next(a for a in child["artifacts"] if a["kind"] == "video")
            child_path = safe_path(root, child_video["path"])
            old_dir, new_dir = path.parent, child_path.parent
            count = len(parent["storyboard"]["shots"])
            equal = [
                digest(old_dir / f"scene-{i:03d}.mp4") == digest(new_dir / f"scene-{i:03d}.mp4")
                for i in range(count)
            ]
            assert equal == [False] + [True] * (count - 1), equal
            assert measured_audio(path) == measured_audio(child_path)
            assert (old_dir / "subtitles.srt").read_bytes() == (
                new_dir / "subtitles.srt"
            ).read_bytes()
            assert digest(path) == video["sha256"]
            p = current()
            restored = post(
                base + "/restore-version",
                {
                    **versions(p),
                    "target_job_id": parent["id"],
                    "reviewer": LABEL,
                    "confirmed": True,
                },
            )
            assert restored["job"]["id"] == parent["id"]
            pack = post(
                "/operations/publication-packs",
                {
                    "job_id": parent["id"],
                    "platform": "douyin",
                    "title": "工程验收样片",
                    "text": "工程演练，尚非客户审片或发布文案",
                },
            )
            assert (
                pack["payload"]["review_status"] == "pending"
                and pack["payload"]["can_publish"] is False
            )
            report["cases"].append(
                {
                    "project_id": pid,
                    "plan_id": row["id"],
                    "parent_job_id": parent["id"],
                    "child_job_id": child["id"],
                    "duration_s": duration,
                    "seconds": round(time.perf_counter() - started, 3),
                    "unchanged_other_scenes": count - 1,
                    "pcm_unchanged": True,
                    "srt_unchanged": True,
                    "old_video_unchanged": True,
                    "restore_keeps_child": True,
                    "pack_id": pack["id"],
                    "new_film_review": "pending",
                    "fixture_approvals_only": True,
                    "native_bridge_rendered": True,
                }
            )
            (work / "progress.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print("NATIVE", row["id"], duration, flush=True)
    backup(root, work / "verified-backup")
    report["backup_verified"] = verify(work / "verified-backup")
    report["status"] = "engineering_passed_manual_pending"
    (work / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
