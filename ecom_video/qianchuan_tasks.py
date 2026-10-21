"""Immutable native publish intents and durable pre-dispatch human approval gates."""

import hashlib
import json
import time
import uuid
from decimal import Decimal
from pathlib import Path

from .db import Conflict
from .distribution import Distribution, approval, encode, label
from .platforms.qianchuan_http import platform_id
from .platforms.secret_store import credential_lock, task_ownership
from .qianchuan_auth import QianchuanAuth
from .reporting import number

ACTIVE = ("uploading", "checking_material", "creating")
JSON_FIELDS = (
    "source_snapshot",
    "parameters",
    "upload_approval",
    "material",
    "payload",
    "approval",
    "result",
)


def checksum(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def parameters(value):
    required = {"name", "product_id", "aweme_id", "title", "budget", "roi2_goal", "is_aigc"}
    if set(value) != required or type(value["is_aigc"]) is not bool:
        raise ValueError("请完整填写千川计划参数")
    result = {
        **value,
        "name": label(value["name"], 40),
        "title": label(value["title"], 30),
        "product_id": platform_id(value["product_id"]),
        "aweme_id": platform_id(value["aweme_id"]),
    }
    if len(result["title"]) < 5:
        raise ValueError("创意标题须为 5–30 字")
    for key in ("budget", "roi2_goal"):
        result[key] = number(value[key], money=True)
        if (
            result[key] is None
            or not Decimal("0") < Decimal(result[key]) <= Decimal("1000000")
            or Decimal(result[key]).as_tuple().exponent < -2
        ):
            raise ValueError("预算/目标 ROI2 须为正数，最多 2 位小数且不超过 1000000")
    return result


def create_payload(task):
    p, m = task["parameters"], task["material"]
    return {
        "advertiser_id": int(task["source_snapshot"]["account"]["advertiser_id"]),
        "name": p["name"] + "-" + task["id"][:8],
        "aweme_id": int(p["aweme_id"]),
        "marketing_goal": "VIDEO_PROM_GOODS",
        "product_ids": [int(p["product_id"])],
        "delivery_setting": {
            "smart_bid_type": "SMART_BID_CUSTOM",
            "roi2_goal": float(p["roi2_goal"]),
            "budget": float(p["budget"]),
            "video_schedule_type": "SCHEDULE_FROM_NOW",
        },
        "creative_setting": {"smart_select_material": False, "hide_in_aweme": True},
        "programmatic_creative_media_list": {
            "video_material": [
                {
                    "video_id": m["video_id"],
                    "video_cover_id": m["video_cover_id"],
                    "image_mode": "VIDEO_VERTICAL",
                }
            ],
            "title_material": [{"title": p["title"]}],
        },
    }


class QianchuanTasks:
    def __init__(self, root, store, auth=None):
        self.root = Path(root).resolve()
        self.store = store
        self.dist = Distribution(root, store)
        self.auth = auth if auth is not None else QianchuanAuth(root, store)

    def _row(self, c, sid):
        row = c.execute("SELECT * FROM qianchuan_tasks WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise KeyError(sid)
        return dict(row)

    def get(self, sid):
        with self.store.connect() as c:
            task = self._row(c, sid)
            task["events"] = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM qianchuan_events WHERE task_id=? ORDER BY id", (sid,)
                )
            ]
        for key in JSON_FIELDS:
            task[key] = json.loads(task[key]) if task[key] else None
        task["payload_preview"] = (
            json.dumps(task["payload"]["request"], ensure_ascii=False, indent=2, sort_keys=True)
            if task["payload"]
            else None
        )
        return task

    def list(self, aid):
        self.dist.account(aid)
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM qianchuan_tasks WHERE account_id=? ORDER BY created_at DESC LIMIT 200",
                    (aid,),
                )
            ]
        return [self.get(sid) for sid in ids]

    def _event(self, c, sid, status, detail):
        now = time.time()
        c.execute("UPDATE qianchuan_tasks SET status=?,updated_at=? WHERE id=?", (status, now, sid))
        c.execute(
            "INSERT INTO qianchuan_events(task_id,status,detail,created_at) VALUES(?,?,?,?)",
            (sid, status, detail, now),
        )

    def create(self, jid, aid, value):
        p = parameters(value)
        account = self.dist.account(aid)
        if account["platform"] != "qianchuan":
            raise ValueError("本版原生投放仅支持巨量千川")
        platform_id(account["advertiser_id"])
        artifacts = self.dist.verified_artifacts(jid)
        snapshot = {"job_id": jid, "account": account, "artifacts": artifacts}
        sid, now = uuid.uuid4().hex, time.time()
        with self.store.transaction() as c:
            if c.execute(
                "SELECT 1 FROM qianchuan_tasks WHERE account_id=? AND job_id=? AND status='unknown'",
                (aid, jid),
            ).fetchone():
                raise Conflict("同账户/成片仍有结果不明任务，请先人工核实，禁止重复投放")
            c.execute(
                "INSERT INTO qianchuan_tasks(id,job_id,account_id,status,source_snapshot,parameters,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (sid, jid, aid, "draft", encode(snapshot), encode(p), now, now),
            )
            self._event(c, sid, "draft", "原生任务草稿；尚未上传或创建广告")
        return self.get(sid)

    def _context(self, task, require_bound=False):
        if not self.auth.writes_enabled():
            raise Conflict("真实平台写入开关未启用；请先完成应用配置及授权")
        self.dist.verify(task["source_snapshot"])
        config = self.auth.config()
        grant = self.auth.grant(task["account_id"])
        if (
            grant["status"] != "authorized"
            or grant["config_revision"] != config["revision"]
            or grant["refresh_expires_at"] <= time.time()
        ):
            raise Conflict("广告主授权已失效，请重新授权")
        if Decimal(task["parameters"]["budget"]) > Decimal(config["max_budget"]):
            raise Conflict("计划 budget 超过本机配置上限")
        if require_bound and (
            task["config_revision"] != config["revision"] or task["grant_id"] != grant["id"]
        ):
            raise Conflict("应用配置或广告主授权发生变化，旧确认已失效")
        return config, grant

    def upload_confirm(self, sid, actor, note, confirmed):
        consent = approval(actor, note, confirmed)
        task = self.get(sid)
        config, grant = self._context(task)
        with self.store.transaction() as c:
            if self._row(c, sid)["status"] != "draft":
                raise Conflict("任务已提交，不能重复上传")
            c.execute(
                "UPDATE qianchuan_tasks SET upload_approval=?,config_revision=?,grant_id=? WHERE id=?",
                (encode(consent), config["revision"], grant["id"], sid),
            )
            self._event(c, sid, "upload_queued", "人工确认上传内容及 AIGC 属性；等待上传")
        return self.get(sid)

    def recheck(self, sid):
        config, grant = self._context(self.get(sid))
        with self.store.transaction() as c:
            row = self._row(c, sid)
            if row["status"] not in ("material_pending", "awaiting_approval") and not (
                row["status"] == "failed" and row["material"] and not row["dispatch_started"]
            ):
                raise Conflict("当前状态不能重新查询素材或预览")
            c.execute(
                "UPDATE qianchuan_tasks SET config_revision=?,grant_id=? WHERE id=?",
                (config["revision"], grant["id"], sid),
            )
            c.execute(
                "UPDATE qianchuan_tasks SET next_check_at=?,check_attempts=0,payload=NULL,snapshot_hash=NULL,approval=NULL,error=NULL WHERE id=?",
                (time.time(), sid),
            )
            self._event(c, sid, "material_pending", "重新读取平台素材；旧提交确认失效")
        return self.get(sid)

    def approve(self, sid, snapshot_hash, actor, note, confirmed):
        consent = approval(actor, note, confirmed)
        task = self.get(sid)
        self._context(task, True)
        if (
            not task["payload"]
            or checksum(task["payload"]) != snapshot_hash
            or task["prepared_until"] <= time.time()
        ):
            raise Conflict("提交预览已变化或过期，请重新查询素材生成预览")
        with self.store.transaction() as c:
            row = self._row(c, sid)
            if row["status"] != "awaiting_approval" or row["snapshot_hash"] != snapshot_hash:
                raise Conflict("任务已变化或已确认")
            c.execute(
                "UPDATE qianchuan_tasks SET approval=? WHERE id=?",
                (encode({**consent, "snapshot_hash": snapshot_hash}), sid),
            )
            self._event(c, sid, "create_queued", "人工确认精确 payload；提交后可能立即开始花费")
        return self.get(sid)

    def cancel(self, sid):
        with self.store.transaction() as c:
            if self._row(c, sid)["status"] not in (
                "draft",
                "upload_queued",
                "material_pending",
                "awaiting_approval",
                "create_queued",
            ):
                raise Conflict("当前任务已派发或结果不明，不能用本地取消替代平台核验")
            self._event(c, sid, "cancelled", "取消后续本地步骤；已经上传的素材不会删除")
        return self.get(sid)

    def claim(self):
        now = time.time()
        with self.store.transaction() as c:
            for row in c.execute(
                "SELECT * FROM qianchuan_tasks WHERE status IN ('uploading','checking_material','creating') AND lease_until<?",
                (now,),
            ).fetchall():
                with task_ownership(self.root, row["id"]) as owned:
                    if not owned:
                        continue
                    unknown = bool(row["dispatch_started"])
                    message = (
                        "进程中断；平台写入结果不明，禁止自动重试"
                        if unknown
                        else "进程中断；尚未派发平台写入"
                    )
                    c.execute("UPDATE qianchuan_tasks SET error=? WHERE id=?", (message, row["id"]))
                    self._event(c, row["id"], "unknown" if unknown else "failed", message)
            row = c.execute(
                "SELECT * FROM qianchuan_tasks WHERE status IN ('upload_queued','create_queued') OR (status='material_pending' AND next_check_at<=?) ORDER BY created_at LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            stage = {
                "upload_queued": "upload",
                "create_queued": "create",
                "material_pending": "check",
            }[row["status"]]
            status = {"upload": "uploading", "create": "creating", "check": "checking_material"}[
                stage
            ]
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE qianchuan_tasks SET lease_token=?,lease_until=?,stage=?,dispatch_started=0,check_attempts=check_attempts+? WHERE id=?",
                (token, now + 300, stage, int(stage == "check"), row["id"]),
            )
            self._event(
                c,
                row["id"],
                status,
                "开始"
                + {"upload": "上传", "check": "只读素材查询", "create": "广告创建前检查"}[stage],
            )
        return self.get(row["id"])

    def _fenced(self, c, task):
        row = self._row(c, task["id"])
        if (
            row["status"] not in ACTIVE
            or row["lease_token"] != task["lease_token"]
            or row["lease_until"] < time.time()
        ):
            raise Conflict("任务租约失效，禁止旧进程继续写入")
        return row

    def mark_dispatch(self, task):
        with credential_lock(self.auth.home), self.store.transaction() as c:
            row = self._fenced(c, task)
            if (
                not self.auth.writes_enabled()
                or self.auth.config()["revision"] != row["config_revision"]
            ):
                raise Conflict("派发前应用配置或真实写入开关已变化")
            if c.execute(
                "SELECT 1 FROM qianchuan_tasks WHERE account_id=? AND job_id=? AND status='unknown' AND id!=?",
                (row["account_id"], row["job_id"], row["id"]),
            ).fetchone():
                raise Conflict("同账户/成片存在结果不明任务，禁止继续写入")
            if row["stage"] == "create" and (
                row["prepared_until"] <= time.time()
                or json.loads(row["approval"])["at"] + 900 <= time.time()
            ):
                raise Conflict("最终派发前确认已过期，未提交")
            if row["stage"] not in ("upload", "create") or row["dispatch_started"]:
                raise Conflict("平台写入已派发，禁止重复发送")
            grant = c.execute(
                "SELECT * FROM qianchuan_grants WHERE account_id=?", (row["account_id"],)
            ).fetchone()
            if (
                not grant
                or grant["status"] != "authorized"
                or grant["id"] != row["grant_id"]
                or grant["config_revision"] != row["config_revision"]
            ):
                raise Conflict("派发前授权已发生变化")
            c.execute("UPDATE qianchuan_tasks SET dispatch_started=1 WHERE id=?", (task["id"],))
            self._event(c, task["id"], row["status"], "即将调用平台一次；结果不明时不会自动重发")

    def finish(self, task, status, detail, **changes):
        allowed = {
            "material",
            "payload",
            "snapshot_hash",
            "prepared_until",
            "result",
            "next_check_at",
            "dispatch_started",
            "error",
            "grant_id",
            "config_revision",
        }
        if set(changes) - allowed:
            raise ValueError("无效任务更新")
        with self.store.transaction() as c:
            self._fenced(c, task)
            for key, value in changes.items():
                c.execute(
                    f"UPDATE qianchuan_tasks SET {key}=? WHERE id=?",
                    (
                        encode(value) if value is not None and key in JSON_FIELDS else value,
                        task["id"],
                    ),
                )
            c.execute("UPDATE qianchuan_tasks SET lease_until=NULL WHERE id=?", (task["id"],))
            self._event(c, task["id"], status, detail)
        return self.get(task["id"])

    def fail(self, task, error):
        from .platforms.qianchuan_http import ProviderError

        with self.store.connect() as c:
            row = self._fenced(c, task)
        uncertain = bool(row["dispatch_started"]) and (
            not isinstance(error, ProviderError) or error.uncertain
        )
        message = (
            str(error)
            if isinstance(error, (Conflict, ProviderError))
            else "操作失败，请检查授权、素材与平台权限；未回显外部响应"
        )
        evidence = (
            {"request_id": error.request_id, "code": error.code}
            if isinstance(error, ProviderError)
            else None
        )
        return self.finish(
            task, "unknown" if uncertain else "failed", message, error=message, result=evidence
        )

    def resolve(self, sid, outcome, ad_id, actor, note, confirmed):
        consent = approval(actor, note, confirmed)
        with task_ownership(self.root, sid) as owned:
            if not owned:
                raise Conflict("仍有进程持有该任务；请先停止旧工作进程，再在平台核验，不能解除隔离")
            with self.store.transaction() as c:
                row = self._row(c, sid)
                if row["status"] != "unknown":
                    raise Conflict("仅结果不明任务可以人工核验")
                if outcome == "found" and row["stage"] == "create":
                    result = {
                        **consent,
                        "ad_id": platform_id(ad_id),
                        "source": "human_recorded",
                        "outcome": "found",
                    }
                    status = "submitted"
                elif outcome == "found" and row["stage"] == "upload":
                    result = {
                        **consent,
                        "source": "human_recorded",
                        "outcome": "uploaded_handle_manually",
                    }
                    status = "cancelled"
                elif outcome == "not_created":
                    result = {**consent, "source": "human_recorded", "outcome": "not_created"}
                    status = "failed"
                else:
                    raise ValueError("上传结果不明请先在平台按 MD5 核验；不要直接重新上传")
                c.execute("UPDATE qianchuan_tasks SET result=? WHERE id=?", (encode(result), sid))
                self._event(c, sid, status, encode(result))
        return self.get(sid)
