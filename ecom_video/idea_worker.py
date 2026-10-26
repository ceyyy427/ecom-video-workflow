"""Consumes previews under the same compute lease as normal rendering."""

import contextlib
import logging
import threading
import time

from .db import Conflict
from .idea_media import check_materials
from .idea_plans import IdeaPlans
from .idea_renderer import cached, engine_key, render_option

log = logging.getLogger(__name__)


def run_once(worker, lease):
    service = IdeaPlans(worker.root, worker.store)
    row = service.claim()
    if row is None:
        return False
    pid, token = row["id"], row["lease_token"]
    stop = threading.Event()
    lost = threading.Event()
    started = time.monotonic()

    def heartbeat():
        while not stop.wait(5):
            try:
                service.check(pid, token, heartbeat=True)
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()

    def check():
        lease.check()
        if lost.is_set() or worker.shutdown.is_set():
            raise Conflict("预览已停止")
        if time.monotonic() - started > 1800:
            raise RuntimeError("六方案预览超过30分钟上限，请分批整理素材后重试")
        service.check(pid, token)

    try:
        if row["plan"]["engine"] != engine_key():
            raise ValueError("渲染引擎已更新，请按原想法重新生成方案；旧预览保留，不混用版本")
        check_materials(worker.root, row["plan"]["materials"])
        for option in row["plan"]["options"]:
            check()
            prior = row["previews"].get(option["id"])
            if cached(worker.root, prior, row["basis"], row["plan"]["engine"]):
                continue
            directory = worker.root / "ideas/previews" / pid / token / option["id"]
            result = render_option(row["plan"], option, worker.root, directory, check)
            service.progress(pid, token, option["id"], result)
        service.finish(pid, token)
    except Conflict:
        # Graceful shutdown leaves an explicit retryable state rather than a stuck lease.
        with contextlib.suppress(Conflict):
            service.finish(pid, token, "本次预览已中断，可手动重试；已完成方向保留")
    except Exception as exc:
        log.exception("Idea preview failed: %s", pid)
        with contextlib.suppress(Conflict):
            service.finish(pid, token, str(exc)[-800:])
    finally:
        stop.set()
        thread.join(timeout=2)
    return True
