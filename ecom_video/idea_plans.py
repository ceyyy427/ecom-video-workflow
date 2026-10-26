"""Immutable idea plans and a bounded, restart-safe local preview queue."""

import json
import time
import uuid
from pathlib import Path

from .content_plan import build_plan
from .db import Conflict
from .media import digest, safe_path
from .products import encoded


class IdeaPlans:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    @staticmethod
    def row(c, pid):
        row = c.execute("SELECT * FROM idea_plans WHERE id=?", (pid,)).fetchone()
        if not row:
            raise KeyError(pid)
        return dict(row)

    def get(self, pid, *, internal=False):
        with self.store.connect() as c:
            out = self.row(c, pid)
        out["plan"] = json.loads(out["plan"])
        out["previews"] = json.loads(out["previews"])
        invalid = (
            self.invalid_previews(out["plan"], out["previews"]) if out["status"] == "ready" else []
        )
        out["repair_needed"] = bool(invalid)
        out["completed"] = len(out["previews"]) - len([k for k in invalid if k in out["previews"]])
        if not internal:
            out.pop("lease_token", None)
        return out

    def create(self, brief, materials, *, engine="preview-v1"):
        from .idea_media import freeze_materials

        plan = build_plan(brief, freeze_materials(self.root, materials), engine=engine)
        with self.store.transaction() as c:
            prior = c.execute(
                "SELECT id FROM idea_plans WHERE basis=?", (plan["basis"],)
            ).fetchone()
            if prior:
                pid = prior["id"]
            else:
                if c.execute("SELECT COUNT(*) FROM idea_plans").fetchone()[0] >= 200:
                    raise Conflict("创意计划已达200个，请先备份并整理历史数据")
                pid, now = uuid.uuid4().hex, time.time()
                c.execute(
                    "INSERT INTO idea_plans(id,basis,plan,status,created_at,updated_at) VALUES(?,?,?,'draft',?,?)",
                    (pid, plan["basis"], encoded(plan), now, now),
                )
        return self.get(pid)

    def enqueue(self, pid, basis):
        with self.store.transaction() as c:
            row = self.row(c, pid)
            if row["basis"] != basis:
                raise Conflict("创意方案依据已变化，请重新比较")
            if row["status"] in ("queued", "rendering"):
                return self.get(pid)
            if row["status"] == "ready":
                plan, previews = json.loads(row["plan"]), json.loads(row["previews"])
                invalid = self.invalid_previews(plan, previews)
                if not invalid:
                    return self.get(pid)
                for key in invalid:
                    previews.pop(key, None)
                c.execute("UPDATE idea_plans SET previews=? WHERE id=?", (encoded(previews), pid))
            if (
                c.execute("SELECT COUNT(*) FROM idea_plans WHERE status='queued'").fetchone()[0]
                >= 8
            ):
                raise Conflict("预览队列已满，请等待本机任务完成")
            c.execute(
                "UPDATE idea_plans SET status='queued',error=NULL,lease_token=NULL,updated_at=? WHERE id=?",
                (time.time(), pid),
            )
        return self.get(pid)

    def cancel(self, pid):
        with self.store.transaction() as c:
            row = self.row(c, pid)
            if row["status"] in ("queued", "rendering"):
                c.execute(
                    "UPDATE idea_plans SET status='cancelled',lease_token=NULL,updated_at=? WHERE id=?",
                    (time.time(), pid),
                )
        return self.get(pid)

    def claim(self):
        with self.store.transaction() as c:
            c.execute(
                "UPDATE idea_plans SET status='failed',error='上次预览进程已中断，请手动重试；已完成项仍保留',lease_token=NULL WHERE status='rendering' AND updated_at<?",
                (time.time() - 90,),
            )
            row = c.execute(
                "SELECT id FROM idea_plans WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            pid, token = row["id"], uuid.uuid4().hex
            c.execute(
                "UPDATE idea_plans SET status='rendering',lease_token=?,updated_at=? WHERE id=?",
                (token, time.time(), pid),
            )
        return self.get(pid, internal=True)

    def check(self, pid, token, *, heartbeat=False):
        with self.store.transaction() if heartbeat else self.store.connect() as c:
            row = self.row(c, pid)
            if row["status"] != "rendering" or row["lease_token"] != token:
                raise Conflict("预览已取消或运行版本已变化")
            if heartbeat:
                c.execute("UPDATE idea_plans SET updated_at=? WHERE id=?", (time.time(), pid))

    def progress(self, pid, token, option_id, result):
        with self.store.transaction() as c:
            row = self.row(c, pid)
            if row["status"] != "rendering" or row["lease_token"] != token:
                raise Conflict("预览已停止")
            previews = json.loads(row["previews"])
            previews[option_id] = result
            c.execute(
                "UPDATE idea_plans SET previews=?,updated_at=? WHERE id=?",
                (encoded(previews), time.time(), pid),
            )

    def finish(self, pid, token, error=None):
        with self.store.transaction() as c:
            row = self.row(c, pid)
            if row["status"] != "rendering" or row["lease_token"] != token:
                raise Conflict("预览已停止")
            complete = len(json.loads(row["previews"])) == 6
            status = "ready" if complete and not error else "failed"
            c.execute(
                "UPDATE idea_plans SET status=?,error=?,lease_token=NULL,updated_at=? WHERE id=?",
                (status, error, time.time(), pid),
            )
        return self.get(pid)

    def invalid_previews(self, plan, previews):
        invalid = []
        for option in plan["options"]:
            record = previews.get(option["id"])
            try:
                if not record:
                    invalid.append(option["id"])
                    continue
                for kind in ("video", "poster"):
                    path = safe_path(self.root, record[kind]["path"])
                    if not path.is_file() or digest(path) != record[kind]["sha256"]:
                        invalid.append(option["id"])
                        break
            except (ValueError, KeyError):
                invalid.append(option["id"])
        return invalid

    def preview(self, pid, option, kind):
        record = self.get(pid)["previews"].get(option)
        if not record or kind not in ("video", "poster"):
            raise KeyError(option)
        path = safe_path(self.root, record[kind]["path"])
        if not path.is_file() or digest(path) != record[kind]["sha256"]:
            raise Conflict("预览文件缺失或已变化，请重试生成")
        return path
