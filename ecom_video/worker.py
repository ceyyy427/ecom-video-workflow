"""Independent leased queue consumer. Run with python -m ecom_video.worker."""

import argparse
import json
import logging
import os
import signal
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path

from .audit import audit_script
from .db import Conflict, Store
from .maintenance_lock import worker_guard
from .media import digest, inspect_media, safe_path
from .renderer import artifact, render, verify_output, write_json

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = Store(self.root / "workflow.db")
        self.owner = uuid.uuid4().hex
        self.shutdown = threading.Event()

    @worker_guard(lambda self: self.root)
    def run_once(self):
        from .resource_leases import Lease

        lease = Lease(self.store)
        if not lease.acquire():
            return False
        lease.keepalive()
        try:
            return self._run_once(lease)
        finally:
            lease.release()

    def _run_once(self, lease):
        if self.shutdown.is_set():
            return False
        self.store.worker_heartbeat(self.owner)
        job = self.store.claim(self.owner)
        if job is None:
            return False
        jid, token = job["id"], job["lease_token"]
        directory = self.root / "jobs" / jid / f"attempt-{job['attempts']}-{token}"
        directory.mkdir(parents=True, exist_ok=False)
        stop, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not stop.wait(5):
                try:
                    self.store.worker_heartbeat(self.owner)
                    if not self.store.heartbeat(jid, token):
                        lost.set()
                        return
                except Exception:
                    log.exception("Worker heartbeat failed")
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        started = time.monotonic()

        def check():
            from .agent_guard import check_target

            lease.check()
            check_target(self.store, "job", jid)
            if lost.is_set() or self.shutdown.is_set():
                raise Conflict("任务已取消或租约失效")
            if time.monotonic() - started > 1800:
                raise RuntimeError("任务超过 30 分钟上限")

        report = None
        try:
            report = audit_script(job["snapshot"]["script"])
            provenance = job["snapshot"].get("provenance")
            if provenance:
                for source in provenance["sources"]:
                    check()
                    path = safe_path(self.root, source["path"])
                    if not path.is_file() or digest(path) != source["sha256"]:
                        raise ValueError("产品原始资料缺失或哈希不符，已停止渲染")
                report["provenance"] = {
                    "product_id": provenance["product_id"],
                    "fact_review_id": provenance["fact_review"]["id"],
                    "script_approval_id": provenance["script_approval"]["id"],
                    "semantic_verification": "human_only",
                    "source_integrity": "verified",
                }
                report["manual_checks"].append(
                    "对照产品事实来源，确认脚本改写未夸大、遗漏条件或混用规格。"
                )
                write_json(directory / "provenance.json", provenance)
            write_json(directory / "audit.json", report)
            if report["status"] == "blocked":
                self.store.finish(
                    jid,
                    token,
                    "blocked",
                    [artifact(self.root, directory / "audit.json", "audit")]
                    + (
                        [artifact(self.root, directory / "provenance.json", "provenance")]
                        if provenance
                        else []
                    ),
                    report,
                    guard=lease.guard,
                )
                return True
            for a in job["snapshot"]["assets"]:
                check()
                path = safe_path(self.root, a["path"])
                if digest(path) != a["sha256"]:
                    raise ValueError("素材文件在提交后发生变化，请复制为新草稿重新上传")
                inspect_media(path, a["kind"])
            self.store.advance(jid, token, "rendering")
            output, duration = render(job, self.root, directory, check)
            self.store.advance(jid, token, "auditing")
            qc = verify_output(output, duration, check)
            write_json(directory / "qc.json", qc)
            from .audit_media import collect
            from .comprehensive_audit import build_report, html_report, scene_timeline

            snapshot = job["snapshot"]
            board = snapshot.get("storyboard") or {}
            mode = board.get("narration", {}).get("mode")
            has_voice = mode != "silent" and (
                mode is not None or any(a["kind"] == "audio" for a in snapshot["assets"])
            )
            from contextlib import nullcontext

            from .agent_guard import check_target, scope

            owner = check_target(self.store, "job", jid)
            with scope(self.store, owner, check) if owner else nullcontext():
                media_checks = collect(
                    output,
                    directory,
                    snapshot["script"],
                    scene_timeline(
                        snapshot,
                        json.loads((directory / "manifest.json").read_text()).get("scenes"),
                    ),
                    has_voice,
                    check,
                )
            report = build_report(
                jid,
                snapshot,
                qc,
                media_checks,
                output_sha256=digest(output),
                actual_scenes=json.loads((directory / "manifest.json").read_text()).get("scenes"),
                source_verified=True,
            )
            write_json(directory / "audit.json", report)
            (directory / "audit.html").write_text(html_report(report))
            paths = [
                ("output.mp4", "video"),
                ("subtitles.srt", "subtitles"),
                ("audit.json", "audit"),
                ("manifest.json", "manifest"),
                ("qc.json", "qc"),
                ("audit.html", "audit_html"),
            ]
            if (directory / "voice-only.mp4").is_file():
                verify_output(directory / "voice-only.mp4", duration, check)
                paths.append(("voice-only.mp4", "video_clean"))
            if (directory / "shotbook.json").is_file():
                paths.append(("shotbook.json", "shotbook"))
            if provenance:
                paths.append(("provenance.json", "provenance"))
            artifacts = [artifact(self.root, directory / name, kind) for name, kind in paths]
            check()
            self.store.finish(jid, token, "needs_review", artifacts, report, guard=lease.guard)
        except Conflict:
            log.info("Lease lost or job cancelled: %s", jid)
        except Exception as exc:
            log.exception("Job failed: %s", jid)
            with suppress(Conflict):
                self.store.finish(
                    jid, token, "failed", [], report, error=str(exc)[:3000], guard=lease.guard
                )
        finally:
            stop.set()
            thread.join(timeout=6)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--data", default=os.getenv("ECOM_DATA_DIR", "var"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker = Worker(args.data)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: worker.shutdown.set())
    while not worker.shutdown.is_set():
        worked = worker.run_once()
        if args.once:
            return
        if not worked:
            worker.shutdown.wait(2)


if __name__ == "__main__":
    main()
