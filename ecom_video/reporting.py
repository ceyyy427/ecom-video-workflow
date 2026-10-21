"""Daily complete snapshots with explicit nulls and source-backed ratios."""

import csv
import hashlib
import io
import json
import re
import time
import uuid
from contextlib import nullcontext
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from .db import Conflict
from .distribution import Distribution, encode, identifier, label

METRICS = ("spend", "impressions", "clicks", "orders", "revenue", "video_views", "completed_views")
COLUMNS = ("date", "material_id", *METRICS)
MAX_BYTES = 5 * 1024**2


def number(value, money=False):
    if value is None or value == "":
        return None
    value = str(value).strip()
    pattern = r"[0-9]{1,15}(?:\.[0-9]{1,6})?" if money else r"[0-9]{1,15}"
    if not re.fullmatch(pattern, value):
        raise ValueError("指标须为有限非负数：计数为整数，金额/比例最多 6 位小数、15 位整数")
    return decimal_text(Decimal(value))


def decimal_text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def dates(start, end, maximum=31):
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValueError("日期须为 YYYY-MM-DD") from None
    if a.isoformat() != start or b.isoformat() != end or not 0 <= (b - a).days < maximum:
        raise ValueError(f"日期范围须有序且最多 {maximum} 天")
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def normalize(rows, start, end):
    allowed = set(dates(start, end))
    result, seen = [], set()
    if len(rows) > 5000:
        raise ValueError("单批最多 5000 行")
    for row in rows:
        day, mid = row.get("date"), identifier(row.get("material_id"))
        if day not in allowed or (day, mid) in seen:
            raise ValueError("存在范围外日期或重复的 日期+素材 ID")
        seen.add((day, mid))
        metrics = {k: number(row.get(k), k in ("spend", "revenue")) for k in METRICS}
        if (
            metrics["completed_views"] is not None
            and metrics["video_views"] is not None
            and Decimal(metrics["completed_views"]) > Decimal(metrics["video_views"])
        ):
            raise ValueError("完播次数不得超过播放次数")
        result.append({"date": day, "material_id": mid, **metrics})
    return result


def aggregate(rows):
    result = {}
    for key in METRICS:
        values = [r[key] for r in rows]
        result[key] = (
            decimal_text(sum((Decimal(v) for v in values), Decimal(0)))
            if values and all(v is not None for v in values)
            else None
        )
    return result


def ratios(totals):
    def divide(a, b, factor=1):
        if totals[a] is None or totals[b] is None or Decimal(totals[b]) == 0:
            return None
        with localcontext() as context:
            context.prec = 50
            return decimal_text(
                (Decimal(totals[a]) / Decimal(totals[b]) * factor).quantize(Decimal("0.000001"))
            )

    return {
        "ctr": divide("clicks", "impressions"),
        "cpc": divide("spend", "clicks"),
        "cpm": divide("spend", "impressions", 1000),
        "cpa": divide("spend", "orders"),
        "payment_roi": divide("revenue", "spend"),
        "order_per_click": divide("orders", "clicks"),
        "completion_rate": divide("completed_views", "video_views"),
    }


class Reporting:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.distribution = Distribution(root, store)

    def import_csv(
        self,
        aid,
        start,
        end,
        data,
        actor,
        confirmed,
        *,
        attribution_window=None,
        context_confirmed=False,
    ):
        if confirmed is not True:
            raise ValueError("须确认文件为该账户日期范围内的完整素材日报快照")
        if len(data) > MAX_BYTES:
            raise ValueError("报表最大 5 MiB")
        try:
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), strict=True)
            if reader.fieldnames != list(COLUMNS):
                raise ValueError("CSV 列名及顺序须与下载模板一致")
            rows = []
            for row in reader:
                if None in row or any(row[k] is None for k in COLUMNS):
                    raise ValueError("CSV 列数错误")
                rows.append(row)
                if len(rows) > 5000:
                    raise ValueError("单批最多 5000 行")
        except (UnicodeDecodeError, csv.Error):
            raise ValueError("请提供 UTF-8 CSV 文件") from None
        rows = normalize(rows, start, end)
        metadata = {"scope": "complete_account_material_daily_snapshot"}
        if attribution_window:
            if (
                context_confirmed is not True
                or not isinstance(attribution_window, str)
                or not 1 <= len(attribution_window.strip()) <= 80
                or any(ord(c) < 32 for c in attribution_window)
            ):
                raise ValueError(
                    "填写归因窗口时，须确认它与平台导出设置一致（1–80 字）；未知请留空。"
                )
            metadata.update(
                attribution_window=attribution_window.strip(),
                attribution_window_origin="human_declared_export_setting;not_platform_verified",
            )
        return self.ingest(
            aid,
            start,
            end,
            rows,
            data,
            "csv",
            actor,
            metadata,
        )

    def ingest(self, aid, start, end, rows, raw, source, actor, metadata, sync=None):
        self.distribution.account(aid)
        dates(start, end)
        actor = label(actor)
        rows = normalize(rows, start, end)
        if source not in ("csv", "ocean_watch_api", "qianchuan_api") or len(raw) > 20 * 1024**2:
            raise ValueError("无效数据来源或响应过大")
        sha, bid = hashlib.sha256(raw).hexdigest(), uuid.uuid4().hex
        rel = f"reports/{bid}/source.{'csv' if source == 'csv' else 'json'}"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        try:
            with self.store.transaction() as c:
                if sync:
                    live = c.execute(
                        "SELECT * FROM report_syncs WHERE id=?", (sync["id"],)
                    ).fetchone()
                    if (
                        not live
                        or live["status"] != "fetching"
                        or live["lease_token"] != sync["lease_token"]
                        or live["lease_until"] < time.time()
                    ):
                        raise Conflict("同步租约已失效")
                old = c.execute(
                    "SELECT * FROM report_batches WHERE account_id=? AND start_date=? AND end_date=? AND source=? AND sha256=? ORDER BY seq DESC LIMIT 1",
                    (aid, start, end, source, sha),
                ).fetchone()
                if old and json.loads(old["metadata"]).get("attribution_window") != metadata.get(
                    "attribution_window"
                ):
                    old = None  # New context gets a new batch; historical declarations stay intact.
                if old:
                    bid = old["id"]
                    path.unlink()
                else:
                    c.execute(
                        "INSERT INTO report_batches(id,account_id,start_date,end_date,source,sha256,path,actor,metadata,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            bid,
                            aid,
                            start,
                            end,
                            source,
                            sha,
                            rel,
                            actor,
                            encode(metadata),
                            time.time(),
                        ),
                    )
                    c.executemany(
                        "INSERT INTO report_rows(batch_id,date,material_id,metrics) VALUES(?,?,?,?)",
                        [
                            (bid, r["date"], r["material_id"], encode({k: r[k] for k in METRICS}))
                            for r in rows
                        ],
                    )
                if sync:
                    c.execute(
                        "UPDATE report_syncs SET status='completed',batch_id=?,updated_at=?,lease_until=NULL WHERE id=?",
                        (bid, time.time(), sync["id"]),
                    )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return next(b for b in self.batches(aid) if b["id"] == bid)

    def batches(self, aid):
        self.distribution.account(aid)
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM report_batches WHERE account_id=? ORDER BY seq DESC", (aid,)
                )
            ]

    def dashboard(self, aid, start, end, *, connection=None, batch_ids=None):
        days = dates(start, end)
        rows, daily, selected_batches, missing = [], [], {}, []
        with nullcontext(connection) if connection is not None else self.store.connect() as c:
            if connection is None:
                c.execute("BEGIN")
            account_row = c.execute("SELECT * FROM platform_accounts WHERE id=?", (aid,)).fetchone()
            if not account_row:
                raise KeyError(aid)
            account = dict(account_row)
            restriction = (
                (" AND id IN (" + ",".join("?" for _ in batch_ids) + ")")
                if batch_ids
                else (" AND 0" if batch_ids is not None else "")
            )
            batches = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM report_batches WHERE account_id=? AND start_date<=? AND end_date>=?"
                    + restriction
                    + " ORDER BY seq DESC",
                    (aid, end, start, *(batch_ids or ())),
                )
            ]
            bindings = {
                r["material_id"]: dict(r)
                for r in c.execute("SELECT * FROM material_bindings WHERE account_id=?", (aid,))
            }
            for day in days:
                batch = next((b for b in batches if b["start_date"] <= day <= b["end_date"]), None)
                current = []
                if batch is None:
                    missing.append(day)
                else:
                    selected_batches[batch["id"]] = batch
                    for row in c.execute(
                        "SELECT * FROM report_rows WHERE batch_id=? AND date=?", (batch["id"], day)
                    ):
                        current.append(
                            {
                                "date": day,
                                "material_id": row["material_id"],
                                "batch_id": batch["id"],
                                "source": batch["source"],
                                **json.loads(row["metrics"]),
                            }
                        )
                rows.extend(current)
                daily.append(
                    {"date": day, "covered": batch is not None, "totals": aggregate(current)}
                )
        observed = aggregate(rows)
        # Covered but empty dates still have unknown metrics, not implicit zeroes.
        totals = {
            k: observed[k] if all(d["totals"][k] is not None for d in daily) else None
            for k in METRICS
        }
        materials = []
        for mid in sorted({r["material_id"] for r in rows}):
            subset = [r for r in rows if r["material_id"] == mid]
            subtotal = aggregate(subset)
            materials.append(
                {
                    "material_id": mid,
                    "observed_totals": subtotal,
                    "ratios": ratios(subtotal),
                    "binding": bindings.get(mid),
                    "reported_days": len(subset),
                }
            )
        status = (
            "empty"
            if not selected_batches
            else ("partial" if missing or any(v is None for v in totals.values()) else "complete")
        )
        return {
            "account": account,
            "start_date": start,
            "end_date": end,
            "status": status,
            "missing_dates": missing,
            "totals": totals,
            "observed_totals": observed,
            "ratios": ratios(totals),
            "daily": daily,
            "materials": materials,
            "batches": list(selected_batches.values()),
            "rows": rows,
            "basis": "素材支付口径；支付 ROI=支付金额/花费（不是 ROI2 或利润率）；订单/点击仅为描述比值",
            "attribution": "账户/素材聚合，非单计划归因；只统计当前范围最新快照，不因重复投放任务重复计数",
            "generated_at": time.time(),
            "notes": [
                f"{len(missing)} 天无报表；区间合计不完整" if missing else "日期快照已覆盖",
                "空白指标显示未知；比率分母为 0 时不计算",
                "素材表为已观测合计；完整性请结合日期覆盖与来源批次判断",
            ],
        }

    def bind(self, aid, mid, jid, actor):
        self.distribution.account(aid)
        mid, actor = identifier(mid), label(actor)
        artifacts = self.distribution.verified_artifacts(jid)
        video = next(a for a in artifacts if a["kind"] == "video")
        with self.store.transaction() as c:
            previous = c.execute(
                "SELECT * FROM material_bindings WHERE account_id=? AND material_id=?", (aid, mid)
            ).fetchone()
            if previous and (
                previous["job_id"] != jid or previous["video_sha256"] != video["sha256"]
            ):
                raise Conflict("该平台素材已关联其他成片；请核对素材 ID")
            c.execute(
                "INSERT OR IGNORE INTO material_bindings VALUES(?,?,?,?,?,?)",
                (aid, mid, jid, video["sha256"], actor, time.time()),
            )
        return {"material_id": mid, "job_id": jid, "video_sha256": video["sha256"]}

    def enqueue(self, aid, start, end, actor):
        account = self.distribution.account(aid)
        if account["platform"] != "qianchuan":
            raise ValueError("本版 API 报表适配仅支持巨量千川；巨量引擎请使用 CSV")
        dates(start, end, 7)
        actor, sid, now = label(actor), uuid.uuid4().hex, time.time()
        with self.store.transaction() as c:
            if c.execute(
                "SELECT 1 FROM report_syncs WHERE account_id=? AND status IN ('queued','fetching')",
                (aid,),
            ).fetchone():
                raise Conflict("该账户已有待完成同步任务")
            c.execute(
                "INSERT INTO report_syncs(id,account_id,start_date,end_date,status,actor,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (sid, aid, start, end, "queued", actor, now, now),
            )
        return self.syncs(aid)[0]

    def syncs(self, aid):
        self.distribution.account(aid)
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM report_syncs WHERE account_id=? ORDER BY created_at DESC LIMIT 50",
                    (aid,),
                )
            ]

    def claim(self):
        with self.store.transaction() as c:
            c.execute(
                "UPDATE report_syncs SET status='failed',error='同步中断；未应用部分报表，可手动重新同步',updated_at=? WHERE status='fetching' AND lease_until<?",
                (time.time(), time.time()),
            )
            row = c.execute(
                "SELECT * FROM report_syncs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            token, until = uuid.uuid4().hex, time.time() + 600
            c.execute(
                "UPDATE report_syncs SET status='fetching',lease_token=?,lease_until=?,updated_at=? WHERE id=?",
                (token, until, time.time(), row["id"]),
            )
            return {**dict(row), "status": "fetching", "lease_token": token, "lease_until": until}

    def fail_sync(self, task):
        with self.store.transaction() as c:
            c.execute(
                "UPDATE report_syncs SET status='failed',error='报表同步失败；检查原生千川 / 独立 Ocean Watch 授权、账户权限和日期，未应用任何部分数据',updated_at=? WHERE id=? AND status='fetching' AND lease_token=?",
                (time.time(), task["id"], task["lease_token"]),
            )
