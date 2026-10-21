"""Immutable human approvals and local export; no platform write is performed."""

import hashlib
import json
import re
import time
import uuid
import zipfile
from pathlib import Path

from .db import Conflict
from .media import digest, safe_path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,29}", value):
        raise ValueError("平台 ID 须为 1–30 位数字字符串，不可使用科学计数法")
    return value


def label(value, maximum=120):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"文字须为 1–{maximum} 字")
    if any(ord(c) < 32 for c in value):
        raise ValueError("文字不可包含控制字符")
    return value.strip()


def approval(actor, note, confirmed):
    if confirmed is not True:
        raise ValueError("请人工勾选确认")
    return {
        "reviewer": label(actor),
        "note": label(note, 2000),
        "confirmed": True,
        "at": time.time(),
    }


class Distribution:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    def accounts(self):
        with self.store.connect() as c:
            return [
                dict(r) for r in c.execute("SELECT * FROM platform_accounts ORDER BY created_at")
            ]

    def account(self, aid):
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM platform_accounts WHERE id=?", (aid,)).fetchone()
        if row is None:
            raise KeyError(aid)
        return dict(row)

    def add_account(self, name, platform, advertiser_id, auth_account_id=""):
        if platform not in ("qianchuan", "oceanengine"):
            raise ValueError("仅支持巨量千川 / 巨量引擎账户")
        advertiser_id = identifier(advertiser_id)
        if auth_account_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", auth_account_id):
            raise ValueError("授权账号别名仅允许字母、数字、下划线和连字符")
        name = label(name)
        aid = uuid.uuid4().hex
        with self.store.transaction() as c:
            if c.execute(
                "SELECT 1 FROM platform_accounts WHERE platform=? AND advertiser_id=?",
                (platform, advertiser_id),
            ).fetchone():
                raise Conflict("该平台广告主已登记")
            c.execute(
                "INSERT INTO platform_accounts(id,name,platform,advertiser_id,auth_account_id,created_at) VALUES(?,?,?,?,?,?)",
                (aid, name, platform, advertiser_id, auth_account_id, time.time()),
            )
        return self.account(aid)

    def verified_artifacts(self, jid):
        job = self.store.get(jid)
        if job["status"] != "ready":
            raise Conflict("仅人工审核通过的成片可以进入投放")
        if not any(a["kind"] == "video" for a in job["artifacts"]):
            raise Conflict("成片缺失")
        for a in job["artifacts"]:
            path = safe_path(self.root, a["path"])
            if not path.is_file() or digest(path) != a["sha256"]:
                raise Conflict("成片或审核证据已缺失/改变，请重新生成并审核")
        return job["artifacts"]

    def verify(self, snapshot):
        artifacts = self.verified_artifacts(snapshot["job_id"])
        if artifacts != snapshot["artifacts"]:
            raise Conflict("投放快照对应的证据已变化")

    def create(self, jid, aid, name, budget, target_roi):
        from .reporting import number

        name = label(name, 100)
        budget = number(budget, money=True)
        target_roi = number(target_roi, money=True)
        if budget is None or float(budget) <= 0 or target_roi is None or float(target_roi) <= 0:
            raise ValueError("预算与目标 ROI 须为正数")
        snapshot = {
            "job_id": jid,
            "account": self.account(aid),
            "name": name,
            "budget_cny": budget,
            "target_roi": target_roi,
            "adapter": "manual_package",
            "budget_scope": "请在平台确认预算周期；本系统不会执行花费",
            "artifacts": self.verified_artifacts(jid),
        }
        frozen = encode(snapshot)
        sid, now = uuid.uuid4().hex, time.time()
        with self.store.transaction() as c:
            c.execute(
                "INSERT INTO distribution_tasks(id,job_id,account_id,status,snapshot,snapshot_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    sid,
                    jid,
                    aid,
                    "awaiting_approval",
                    frozen,
                    hashlib.sha256(frozen.encode()).hexdigest(),
                    now,
                    now,
                ),
            )
            self._event(c, sid, "awaiting_approval", "冻结成片、账户和投放意向；等待人工确认")
        return self.get(sid)

    def _row(self, c, sid):
        row = c.execute("SELECT * FROM distribution_tasks WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise KeyError(sid)
        return dict(row)

    def _event(self, c, sid, status, detail):
        now = time.time()
        c.execute(
            "UPDATE distribution_tasks SET status=?,updated_at=? WHERE id=?", (status, now, sid)
        )
        c.execute(
            "INSERT INTO distribution_events(task_id,status,detail,created_at) VALUES(?,?,?,?)",
            (sid, status, detail, now),
        )

    def get(self, sid):
        with self.store.connect() as c:
            row = self._row(c, sid)
            row["events"] = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM distribution_events WHERE task_id=? ORDER BY id", (sid,)
                )
            ]
        for key in ("snapshot", "approval", "receipt"):
            row[key] = json.loads(row[key]) if row[key] else None
        return row

    def tasks(self):
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM distribution_tasks ORDER BY created_at DESC LIMIT 200"
                )
            ]
        return [self.get(sid) for sid in ids]

    def approve(self, sid, snapshot_hash, actor, note, confirmed):
        consent = approval(actor, note, confirmed)
        task = self.get(sid)
        self.verify(task["snapshot"])
        with self.store.transaction() as c:
            row = self._row(c, sid)
            if row["status"] != "awaiting_approval" or row["snapshot_hash"] != snapshot_hash:
                raise Conflict("任务已变化或已确认，请刷新后检查")
            c.execute("UPDATE distribution_tasks SET approval=? WHERE id=?", (encode(consent), sid))
            self._event(c, sid, "queued", "人工确认完成，等待生成本地投放包")
        return self.get(sid)

    def cancel(self, sid):
        with self.store.transaction() as c:
            row = self._row(c, sid)
            if row["status"] not in ("awaiting_approval", "queued"):
                raise Conflict("仅尚未导出的任务可以取消；已交接任务请在平台操作")
            self._event(c, sid, "cancelled", "人工取消未执行任务")
        return self.get(sid)

    def claim(self):
        with self.store.transaction() as c:
            for r in c.execute(
                "SELECT id FROM distribution_tasks WHERE status='exporting' AND lease_until<?",
                (time.time(),),
            ).fetchall():
                self._event(
                    c, r[0], "failed", "导出进程中断；未执行任何平台写入，可新建任务重新确认"
                )
            row = c.execute(
                "SELECT id FROM distribution_tasks WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE distribution_tasks SET lease_token=?,lease_until=? WHERE id=?",
                (token, time.time() + 300, row[0]),
            )
            self._event(c, row[0], "exporting", "生成本地投放包")
        return self.get(row[0])

    def export(self, task):
        sid, token = task["id"], task["lease_token"]
        path = safe_path(self.root, f"distribution/{sid}/{token}.zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.verify(task["snapshot"])
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for artifact in task["snapshot"]["artifacts"]:
                    source = safe_path(self.root, artifact["path"])
                    name = artifact["kind"] + source.suffix
                    sha = hashlib.sha256()
                    with source.open("rb") as src, z.open(name, "w") as out:
                        while chunk := src.read(1024 * 1024):
                            sha.update(chunk)
                            out.write(chunk)
                    if sha.hexdigest() != artifact["sha256"]:
                        raise Conflict("生成投放包时文件发生变化")
                z.writestr(
                    "投放确认.json",
                    encode(
                        {
                            "snapshot": task["snapshot"],
                            "snapshot_hash": task["snapshot_hash"],
                            "approval": task["approval"],
                        }
                    ),
                )
                z.writestr(
                    "操作说明.txt",
                    "此包尚未上传或投放。请在巨量平台核对广告主、商品、预算周期、目标 ROI、视频内容及平台规则；上传并人工创建计划后，在工作台登记计划 ID 和状态。支付 ROI 不等于利润率。",
                )
            package_hash = digest(path)
            with self.store.transaction() as c:
                row = self._row(c, sid)
                if (
                    row["status"] != "exporting"
                    or row["lease_token"] != token
                    or row["lease_until"] < time.time()
                ):
                    raise Conflict("导出任务租约已失效")
                c.execute(
                    "UPDATE distribution_tasks SET package_path=?,package_hash=?,lease_until=NULL WHERE id=?",
                    (str(path.relative_to(self.root)), package_hash, sid),
                )
                self._event(c, sid, "awaiting_manual", "投放包生成完成，等待人工在平台创建计划")
        except Exception:
            path.unlink(missing_ok=True)
            with self.store.transaction() as c:
                row = self._row(c, sid)
                if row["status"] == "exporting" and row["lease_token"] == token:
                    self._event(c, sid, "failed", "投放包导出失败，检查成片完整性后新建任务")
            raise
        return self.get(sid)

    def package(self, sid):
        task = self.get(sid)
        if not task["package_path"]:
            raise Conflict("投放包尚未完成")
        path = safe_path(self.root, task["package_path"])
        if not path.is_file() or digest(path) != task["package_hash"]:
            raise Conflict("投放包缺失或校验失败")
        return path

    def receipt(self, sid, status, ad_id, actor, note, confirmed):
        consent = approval(actor, note, confirmed)
        ad_id = identifier(ad_id)
        transitions = {
            "awaiting_manual": {"submitted"},
            "submitted": {"active", "paused", "rejected", "completed"},
            "active": {"paused", "completed", "rejected"},
            "paused": {"active", "completed", "rejected"},
        }
        with self.store.transaction() as c:
            row = self._row(c, sid)
            if status not in transitions.get(row["status"], set()):
                raise Conflict("该平台状态转换无效；请先登记提交回执")
            previous = json.loads(row["receipt"]) if row["receipt"] else None
            if previous and previous["ad_id"] != ad_id:
                raise Conflict("已登记的计划 ID 不可更改，请新建任务")
            receipt = {**consent, "ad_id": ad_id, "status": status, "source": "human_recorded"}
            c.execute("UPDATE distribution_tasks SET receipt=? WHERE id=?", (encode(receipt), sid))
            self._event(c, sid, status, encode(receipt))
        return self.get(sid)
