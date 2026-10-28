"""Interleaved real-render benchmark, isolated engineering fixtures only.

Measures coordinator + render from the SAME prepared/previously aligned board.
Does NOT measure first-time visual recognition, script generation or human review.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE D2 benchmark; not customer approval"


def fixture(project):
    if not project["title"].startswith("AUTOMATED FIXTURE"):
        raise ValueError("只能重放标记的工程项目，禁止借用客户审批")


def source_choices(job):
    assets = {a["id"]: a["sha256"] for a in job["assets"]}
    return [
        [{**c, "asset_id": assets[c["asset_id"]]} for c in s.get("source_cuts", [])]
        for s in job["storyboard"]["shots"]
    ]


def changes_for(condition):
    return (
        {"headline": "穿得利落"}
        if condition == "cold_render_cache"
        else {"typography": {"mode": "contrast", "keyword": "利落"}}
    )


def run_unit(work, bundle, pid, mode):
    from ecom_video.agent_runtime import Runtime
    from ecom_video.agent_service import AgentService
    from ecom_video.customer import Customers
    from ecom_video.db import Store
    from ecom_video.delivery_reviews import confirm_style
    from ecom_video.maintenance import restore
    from ecom_video.media import digest, safe_path
    from ecom_video.operations.video_acceptance import measured_audio
    from ecom_video.worker import Worker

    restore(bundle, work / "runtime")
    root = work / "runtime"
    service = Customers(root, Store(root / "workflow.db"))
    fixture(service.get(pid)["product"])
    rows = []
    for condition in ("cold_render_cache", "warm_single_shot"):
        p = service.get(pid)
        old_video = next(a for a in p["job"]["artifacts"] if a["kind"] == "video")
        old_hash = digest(safe_path(root, old_video["path"]))
        old_shots = p["job"]["storyboard"]["shots"]
        old_choices = source_choices(p["job"])
        started = time.perf_counter()
        p = service.revise(
            pid,
            {
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
                "request_id": "bench-" + condition,
                "shot_id": old_shots[0]["shot_id"],
                "changes": changes_for(condition),
            },
        )
        style = p["job"]["storyboard"]["creative"]["style_id"]

        def confirm(stage, style=style):
            current = service.get(pid)
            return confirm_style(
                service,
                pid,
                {
                    "revision": current["revision"],
                    "stage": stage,
                    "style_id": style,
                    "basis": current["delivery_reviews"][stage + "_basis"],
                    "reviewer": LABEL,
                    "confirmed": True,
                },
            )

        if mode == "fixed":
            service.prepare(pid, p["revision"])
            confirm("direction")
            p = confirm("storyboard")
            service.submit(pid, p["revision"], p["job"]["id"], p["job"]["storyboard_revision"])
        else:
            policy = {
                "policy_id": "local-v1",
                "max_steps": 40,
                "max_elapsed_s": 1800,
                "max_model_calls": 40,
                "max_cost_cny": "0",
            }
            proposal = AgentService(root, service.store).create(
                {
                    "schema_version": 1,
                    "request_id": "bench-" + condition,
                    "operation": "project.produce",
                    "input": {
                        "project_id": pid,
                        "expected_revision": p["revision"],
                        "expected_product_revision": p["product"]["revision"],
                        "policy": policy,
                    },
                }
            )
            assert proposal["status"] == "proposed", proposal
            runtime = Runtime(root, service.store)
            rid = proposal["run_id"]

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
                    "style_id": style,
                    "direction_basis": p["direction_basis"],
                    "reviewer": LABEL,
                    "confirmed": True,
                },
            )
            for _ in range(8):
                runtime.tick()
                e = runtime.get(rid)
                if e["waiting_for"] == "storyboard":
                    confirm("storyboard")
                    runtime.control(rid, "resume", bound())
                if service.get(pid)["job"]["status"] == "queued":
                    break
            assert service.get(pid)["job"]["status"] == "queued", runtime.get(rid)
        assert Worker(root).run_once()
        p = service.get(pid)
        assert p["job"]["status"] == "needs_review" and not p["job"]["reviews"], p["job"]["error"]
        if mode == "agent":
            runtime.tick()
            assert runtime.get(rid)["waiting_for"] == "film_review"
        elapsed = time.perf_counter() - started
        video = next(a for a in p["job"]["artifacts"] if a["kind"] == "video")
        folder = safe_path(root, video["path"]).parent
        manifest = json.loads((folder / "manifest.json").read_text())
        assert digest(safe_path(root, old_video["path"])) == old_hash
        assert old_choices == source_choices(p["job"])
        rows.append(
            {
                "condition": condition,
                "mode": mode,
                "seconds": round(elapsed, 3),
                "cache": manifest["cache"],
                "job_id": p["job"]["id"],
                "video_sha256": video["sha256"],
                "pcm": measured_audio(folder / "output.mp4"),
                "srt_sha256": digest(folder / "subtitles.srt"),
                "source_cuts_unchanged": True,
                "customer_film_review": "pending",
            }
        )
        (work / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    assert rows[1]["cache"] == {"hits": 5, "rendered": 1, "total": 6}, rows
    return rows


def tree_rss(pid):
    text = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss="], text=True, timeout=5)
    rows = [tuple(map(int, line.split())) for line in text.splitlines() if line.strip()]
    ids = {pid}
    for _ in range(20):
        found = {p for p, parent, _ in rows if parent in ids}
        if found <= ids:
            break
        ids |= found
    return sum(rss for p, _, rss in rows if p in ids) * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--unit", choices=["fixed", "agent"])
    parser.add_argument("--simulate-confirmations", action="store_true")
    args = parser.parse_args()
    work = args.workspace.resolve()
    if not args.simulate_confirmations or work.exists() or work.is_relative_to(ROOT):
        parser.error("必须选择全新仓库外目录，并明确 --simulate-confirmations")
    os.environ.update(
        ECOM_AGENT_ENABLED="1",
        ECOM_AGENT_EXECUTION_ENABLED="1",
        ECOM_MEDIA_AUDIT="0",
        ECOM_QIANCHUAN_WRITES="0",
    )
    if args.unit:
        work.mkdir(parents=True)
        rows = run_unit(work, args.bundle, args.project, args.unit)
        (work / "result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    # Read-only validation before the backup; Store is only constructed on the backup clone later.
    import sqlite3

    from ecom_video.maintenance import backup

    with sqlite3.connect(args.source.as_uri() + "/workflow.db?mode=ro", uri=True) as db:
        title = db.execute("SELECT title FROM products WHERE id=?", (args.project,)).fetchone()
    fixture({"title": title[0] if title else ""})
    work.mkdir(parents=True)
    bundle = work / "bundle"
    backup(args.source, bundle)
    rows = []
    for round_id in range(3):
        for mode in ("agent", "fixed") if round_id % 2 == 0 else ("fixed", "agent"):
            unit = work / f"round-{round_id + 1}-{mode}"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--bundle",
                str(bundle),
                "--project",
                args.project,
                "--workspace",
                str(unit),
                "--unit",
                mode,
                "--simulate-confirmations",
            ]
            with (work / f"round-{round_id + 1}-{mode}.log").open("w") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                peak = 0
                while process.poll() is None:
                    peak = max(peak, tree_rss(process.pid))
                    time.sleep(0.5)
                if process.returncode:
                    raise RuntimeError(f"工程测试失败，保留 {unit} 及日志")
            rows.extend(
                {**r, "round": round_id + 1, "unit_tree_peak_rss_bytes": peak}
                for r in json.loads((unit / "result.json").read_text())
            )
            (work / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print("BENCH", round_id + 1, mode, flush=True)
    assert len({r["pcm"] for r in rows}) == 1
    assert len({r["srt_sha256"] for r in rows}) == 1
    result = {
        "scope": "prepared_board_coordinator_and_render_only",
        "rounds": rows,
        "not_first_recognition_benchmark": True,
        "model_calls": 0,
        "cloud_calls": 0,
        "platform_writes": 0,
        "fixture_confirmations": True,
        "customer_approval": False,
        "backend_default_changed": False,
        "memory_definition": "sampled process tree peak RSS; shared pages may count more than once",
    }
    (work / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
