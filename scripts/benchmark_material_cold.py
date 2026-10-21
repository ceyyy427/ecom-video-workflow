"""Force both recognition caches off for the licensed five-file rehearsal.

Only use isolated fixture data; approvals remain pending, never live customer data.
"""

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def measured(start, wall_start):
    seconds, wall = time.monotonic() - start, time.time() - wall_start
    gap = abs(wall - seconds)
    return {
        "seconds": round(seconds, 4),
        "wall_seconds": round(wall, 4),
        "clock_gap_seconds": round(gap, 4),
        "measurement_valid": gap <= 5,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", default=str(root))
    p.add_argument("--source-data", type=Path, required=True)
    p.add_argument("--mode", choices=("legacy", "optimized"), default="optimized")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    a = p.parse_args()
    os.environ["ECOM_VISION_ACCELERATION"] = "off" if a.mode == "legacy" else "auto"
    sys.path.insert(0, a.package)
    from ecom_video import vision_model as v
    from ecom_video.db import Store
    from ecom_video.media import digest
    from ecom_video.media_analysis import Analysis

    old = a.source_data.resolve()
    b = a.out.resolve()
    assert not b.exists()
    assert not b.is_relative_to(root) and not old.is_relative_to(root / "var")
    assert not b.is_relative_to(old) and not old.is_relative_to(b)
    assert not a.evidence.resolve().is_relative_to(root / "var")
    assert not (a.evidence / "summary.json").exists()
    assert (old / "material-license.json").is_file()
    b.mkdir()
    a.evidence.mkdir(parents=True, exist_ok=True)
    for file in old.iterdir():
        if file.is_file() and (file.suffix == ".json" or file.name == "script.txt"):
            shutil.copy2(file, b / file.name)
    shutil.copytree(
        old / "runtime",
        b / "runtime",
        ignore=shutil.ignore_patterns(
            "workflow.db", "workflow.db-wal", "workflow.db-shm", "inference-cache"
        ),
    )
    with (
        sqlite3.connect("file:" + str(old / "runtime/workflow.db") + "?mode=ro", uri=True) as src,
        sqlite3.connect(b / "runtime/workflow.db") as dst,
    ):
        src.backup(dst)
    pid = json.loads((old / "documents-ready.json").read_text())["id"]
    svc = Analysis(b / "runtime", Store(b / "runtime/workflow.db"))
    model = v.identity()
    original = v.request
    original("/api/generate", {"model": model["model"], "keep_alive": 0}, timeout=20)
    requests = []
    rows = []
    current = ""

    def tracked(path, payload=None, **kwargs):
        start = time.monotonic()
        wall_start = time.time()
        try:
            result = original(path, payload, **kwargs)
        except Exception as e:
            if path == "/api/chat":
                print("REQUEST FAILED", current, str(e), flush=True)
            raise
        if path == "/api/chat":
            clone = json.loads(json.dumps(payload))
            ims = clone["messages"][-1].pop("images", [])
            hashes = [hashlib.sha256(base64.b64decode(i)).hexdigest() for i in ims]
            clone["messages"][-1]["image_sha256"] = hashes
            row = {
                "index": len(requests) + 1,
                "file": current,
                **measured(start, wall_start),
                "payload": clone,
                "response": result,
            }
            requests.append(row)
            with (a.evidence / "requests.jsonl").open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if not row["measurement_valid"]:
                raise ValueError("机器休眠或时钟跳变，本轮速度测量无效，请保持唤醒重新运行")
            print(
                "CALL",
                row["index"],
                current,
                row["seconds"],
                "sec",
                "load",
                result.get("load_duration", 0) / 1e9,
                "prefill",
                result.get("prompt_eval_duration", 0) / 1e9,
                "decode",
                result.get("eval_duration", 0) / 1e9,
                flush=True,
            )
        return result

    v.request = tracked
    guard = (
        subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
        if platform.system() == "Darwin" and Path("/usr/bin/caffeinate").is_file()
        else None
    )
    try:
        for current in ("pour.mp4", "view.mp4", "context.mp4", "other.mp4", "wide.mp4"):
            with svc.store.connect() as c:
                asset = dict(
                    c.execute(
                        "SELECT * FROM customer_media WHERE product_id=? AND name=?", (pid, current)
                    ).fetchone()
                )
            assert digest(b / "runtime" / asset["path"]) == asset["sha256"]
            print("START", current, flush=True)
            t = time.monotonic()
            wall = time.time()
            n = len(requests)
            queued = svc.start(pid, asset["id"], force_inference=True)
            row = svc.claim()
            assert row["id"] == queued["id"]
            svc.run(row, lambda current_row=row: svc.progress(current_row))
            result = svc.get(pid, asset["id"])
            elapsed = time.monotonic() - t
            timing = measured(t, wall)
            (b / (current + ".forced.json")).write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            (a.evidence / (current + ".json")).write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            assert result["status"] == "ready", result["error"]
            assert timing["measurement_valid"], "Invalid timing after sleep or clock jump"
            perf = result["result"]["performance"]["model_cache"]
            assert perf["forced_inference"] and perf["hits"] == 0
            assert len(requests) > n
            rows.append(
                {
                    "name": current,
                    **timing,
                    "model_calls": len(requests) - n,
                    "analysis_id": result["id"],
                    "cache": perf,
                    "source_sha256": asset["sha256"],
                }
            )
            (a.evidence / "summary.json").write_text(
                json.dumps(
                    {
                        "complete": False,
                        "files": rows,
                        "seconds": sum(x["seconds"] for x in rows),
                        "model": model,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("DONE", current, round(elapsed, 2), "sec", flush=True)
        report = {
            "complete": True,
            "files": rows,
            "seconds": sum(x["seconds"] for x in rows),
            "model": model,
            "backend_chat_calls": len(requests),
            "human_review": "pending",
            "computer_use": False,
            "platform_writes": 0,
            "mode": a.mode,
            "measurement_valid": all(r["measurement_valid"] for r in rows),
            "idle_sleep_prevention": guard is not None and guard.poll() is None,
        }
        (a.evidence / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print("FORCED BENCHMARK COMPLETE", report["seconds"], flush=True)
    finally:
        try:
            original("/api/generate", {"model": model["model"], "keep_alive": 0}, timeout=20)
        finally:
            if guard:
                guard.terminate()
                guard.wait(timeout=5)


if __name__ == "__main__":
    main()
