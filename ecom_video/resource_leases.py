"""Cross-process compute exclusion for this application's own heavy tasks."""

import threading
import time
import uuid

from .db import Conflict


class Lease:
    def __init__(self, store, name="local_compute", ttl=30):
        self.store, self.name, self.ttl = store, name, ttl
        self.token = uuid.uuid4().hex
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = None

    def acquire(self, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as c:
            c.execute(
                "DELETE FROM resource_leases WHERE name=? AND expires_at<=?", (self.name, now)
            )
            return bool(
                c.execute(
                    "INSERT OR IGNORE INTO resource_leases VALUES(?,?,?)",
                    (self.name, self.token, now + self.ttl),
                ).rowcount
            )

    def renew(self, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as c:
            return bool(
                c.execute(
                    "UPDATE resource_leases SET expires_at=? WHERE name=? AND token=? AND expires_at>?",
                    (now + self.ttl, self.name, self.token, now),
                ).rowcount
            )

    def check(self):
        if self.lost.is_set():
            raise Conflict("本机资源租约已失效")
        with self.store.connect() as c:
            self.guard(c)

    def guard(self, c):
        row = c.execute(
            "SELECT 1 FROM resource_leases WHERE name=? AND token=? AND expires_at>?",
            (self.name, self.token, time.time()),
        ).fetchone()
        if not row:
            raise Conflict("本机资源租约已失效")

    def keepalive(self):
        def beat():
            while not self.stop.wait(min(5, self.ttl / 3)):
                try:
                    if self.renew():
                        continue
                except Exception:
                    pass
                self.lost.set()
                return

        self.thread = threading.Thread(target=beat, daemon=True)
        self.thread.start()
        return self

    def release(self):
        self.stop.set()
        if self.thread:
            self.thread.join(6)
        with self.store.transaction() as c:
            c.execute(
                "DELETE FROM resource_leases WHERE name=? AND token=?", (self.name, self.token)
            )

    def __enter__(self):
        if not self.acquire():
            raise Conflict("本机正在执行其他重任务，请稍后继续")
        return self.keepalive()

    def __exit__(self, *args):
        self.release()
