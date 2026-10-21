"""Reproducible warm-reuse benchmark for the licensed five-file material rehearsal.

This is an isolated automated fixture, never human approval or live customer data.
"""

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))


def main():
    from fastapi.testclient import TestClient

    from ecom_video import vision_model
    from ecom_video.api import create_app
    from ecom_video.current_observation_reuse import reuse
    from ecom_video.db import Store
    from ecom_video.media_analysis import Analysis
    from ecom_video.product_inspection import context_for

    ap = argparse.ArgumentParser(
        description="Repeat the five-file licensed material rehearsal; unexpected inference misses stop without a cold rerun."
    )
    ap.add_argument("--source-data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument(
        "--baseline-log",
        type=Path,
        default=root / "docs/evidence/material-suitability/bounded-inference.log",
    )
    args = ap.parse_args()
    old, base = args.source_data.resolve(), args.output.resolve()
    assert not base.exists(), "Output must be a fresh external directory"
    assert not base.is_relative_to(root) and not old.is_relative_to(root / "var")
    assert not base.is_relative_to(old) and not old.is_relative_to(base)
    assert not args.evidence.resolve().is_relative_to(root / "var")
    args.evidence.mkdir(parents=True, exist_ok=True)
    assert not (args.evidence / "benchmark.json").exists(), "Keep the prior benchmark receipt"
    if not base.exists():
        base.mkdir()
        for p in old.iterdir():
            if p.is_file():
                shutil.copy2(p, base / p.name)
        shutil.copytree(
            old / "runtime",
            base / "runtime",
            ignore=shutil.ignore_patterns(
                "workflow.db", "workflow.db-wal", "workflow.db-shm", "inference-cache"
            ),
        )
        with (
            sqlite3.connect(
                "file:" + str(old / "runtime/workflow.db") + "?mode=ro", uri=True
            ) as source,
            sqlite3.connect(base / "runtime/workflow.db") as target,
        ):
            source.backup(target)
    assert not (base / "speed-benchmark.json").exists(), "Never overwrite a completed benchmark"
    pid = json.loads((base / "documents-ready.json").read_text())["id"]
    c = TestClient(create_app(base / "runtime"), base_url="http://localhost")
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    url = "/api/customer-projects/" + pid
    svc = Analysis(base / "runtime", Store(base / "runtime/workflow.db"))
    model = vision_model.identity()
    original = vision_model.request
    calls = []

    def tracked(path, payload=None, **kwargs):
        if path == "/api/chat":
            calls.append(path)
            raise AssertionError(
                "Benchmark cache expected eligible; do not silently rerun 76-minute cold inference"
            )
        return original(path, payload, **kwargs)

    vision_model.request = tracked
    rows = []
    for round_no in range(2):
        for name in ("pour.mp4", "view.mp4", "context.mp4", "other.mp4", "wide.mp4"):
            p = c.get(url).json()
            asset = next(a for a in p["media"] if a["name"] == name)
            with svc.store.connect() as db:
                raw = dict(
                    db.execute("SELECT * FROM customer_media WHERE id=?", (asset["id"],)).fetchone()
                )
                context = context_for(db, pid)
            # Prove eligibility before using the normal service; never mask a cold miss as a fast result.
            target = base / "runtime/analyses" / ("eligibility-" + str(round_no) + "-" + name)
            eligible = reuse(base / "runtime", svc.store, raw, context, model, target, lambda: None)
            assert eligible is not None, (name, "cache not eligible")
            shutil.rmtree(target)
            t = time.monotonic()
            svc.start(pid, asset["id"], refresh=True)
            svc.run(svc.claim(), lambda: None)
            result = svc.get(pid, asset["id"])
            elapsed = time.monotonic() - t
            assert result["status"] == "ready", result["error"]
            before = json.loads((old / (name + ".bounded.json")).read_text())["result"]
            after = result["result"]

            def evidence(d):
                return [
                    {
                        "observation": s["observation"],
                        "samples": s["motion_check"]["samples"],
                        "events": s["motion_check"]["events"],
                        "ranges": s["motion_check"].get("material_visible_ranges", []),
                        "planned_samples": s["motion_check"]["planned_samples"],
                    }
                    for s in d["segments"]
                ]

            assert evidence(before) == evidence(after), (name, "recognition changed")
            rows.append(
                {
                    "round": round_no + 1,
                    "name": name,
                    "seconds": round(elapsed, 4),
                    "analysis_id": result["id"],
                    "mode": after["raw_reuse_validation"],
                    "evidence_equal": True,
                    "performance": after["performance"],
                }
            )
            (base / (name + ".speed-round-" + str(round_no + 1) + ".json")).write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            print(rows[-1], flush=True)
    log = args.baseline_log.read_text()
    baseline = {
        name: float(seconds) for name, seconds in re.findall(r"DONE (\S+) ([\d.]+) sec", log)
    }
    report = {
        "historical_cold_baseline_seconds": sum(baseline.values()),
        "baseline_per_file": baseline,
        "new_cold_first_run_tested": False,
        "rounds": [
            {"round": n, "seconds": round(sum(r["seconds"] for r in rows if r["round"] == n), 4)}
            for n in (1, 2)
        ],
        "files": rows,
        "backend_chat_calls": len(calls),
        "sampling_and_thresholds_unchanged": True,
        "comparison": "historical actual cold run vs provenance-verified warm reuse, not cold inference acceleration",
        "human_review": "pending",
        "computer_use": False,
        "platform_writes": 0,
    }
    (base / "speed-benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (args.evidence / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (base / "project-verified.json").write_text(
        json.dumps(c.get(url).json(), ensure_ascii=False, indent=2)
    )
    print("BENCHMARK COMPLETE", flush=True)


if __name__ == "__main__":
    main()
