"""One local inference at a time; restart never pretends an interrupted scan completed."""

import argparse
import signal
import threading
import time
from pathlib import Path

from .db import Store
from .maintenance_lock import worker_guard
from .media_analysis import Analysis, cleanup_removed


class Worker:
    def __init__(self, root):
        self.service = Analysis(root, Store(Path(root) / "workflow.db"))
        self.stop = threading.Event()

    @worker_guard(lambda self: self.service.root)
    def once(self):
        from .agent_guard import check_target, scope
        from .resource_leases import Lease

        lease = Lease(self.service.store)
        if not lease.acquire():
            return False
        lease.keepalive()
        try:
            return self._once(lease, check_target, scope)
        finally:
            lease.release()

    def _once(self, lease, check_target, scope):
        row = self.service.claim()
        if not row:
            return False
        done = threading.Event()
        lost = threading.Event()
        started = time.monotonic()

        def heartbeat():
            while not done.wait(5):
                try:
                    self.service.progress(row)
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()

        def check():
            lease.check()
            check_target(self.service.store, "analysis", row["id"])
            if self.stop.is_set() or lost.is_set() or time.monotonic() - started > 1800:
                raise RuntimeError("识别已停止、取消或超过30分钟，请缩短素材后重试")
            self.service.progress(row)

        try:
            from .agent_guard import owner

            rid = owner(self.service.store, "analysis", row["id"])
            with (
                scope(self.service.store, rid, lease.check)
                if rid
                else __import__("contextlib").nullcontext()
            ):
                self.service.run(row, check, resource=lease)
        except Exception as exc:
            self.service.fail(row, exc)
        finally:
            done.set()
            thread.join(6)
            cleanup_removed(self.service.root, self.service.store, row["media_id"], row["id"])
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="var")
    args = parser.parse_args()
    worker = Worker(args.data)
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: worker.stop.set())
    while not worker.stop.is_set():
        if not worker.once():
            worker.stop.wait(1)


if __name__ == "__main__":
    main()
