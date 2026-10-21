"""Immutable account/material/day evidence, not an experiment or placement engine."""

import hashlib
import json
import time
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, localcontext
from pathlib import Path

from .creative_features import Features, sha
from .db import Conflict
from .distribution import encode
from .media import safe_path
from .reporting import METRICS, Reporting, aggregate, dates, ratios
from .review_contracts import (
    ALGORITHM_VERSION,
    MAX_CELLS,
    MAX_MATERIALS,
    MAX_PAYLOAD,
    MAX_ROWS,
    MAX_SOURCE_BYTES,
    FreezeInput,
    enabled,
    identifier,
    metric_contract,
    parse,
)


def checked_file(root, path, expected, remaining):
    try:
        file = safe_path(root, path)
        if not file.is_file() or file.stat().st_size > remaining:
            raise Conflict("报表证据缺失或超过校验上限，未采用其内容。")
        total = 0
        digest = hashlib.sha256()
        with file.open("rb") as source:
            while chunk := source.read(min(1024**2, remaining - total + 1)):
                total += len(chunk)
                if total > remaining:
                    raise Conflict("报表证据超过校验上限。")
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise Conflict("报表证据哈希不符，请恢复原始文件或重新导入。")
        return file, total
    except (OSError, ValueError):
        raise Conflict("报表证据缺失或无法安全读取。") from None


def source_rows(c, bid, selected_dates):
    result = []
    for day in sorted(selected_dates):
        for r in c.execute(
            "SELECT material_id,metrics FROM report_rows WHERE batch_id=? AND date=? ORDER BY material_id",
            (bid, day),
        ):
            result.append(
                {"date": day, "material_id": r["material_id"], "metrics": json.loads(r["metrics"])}
            )
    return result


def declared_context(batch):
    try:
        metadata = json.loads(batch["metadata"])
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        k: v if isinstance(v, str) and len(v) <= 240 and all(ord(x) >= 32 for x in v) else None
        for k in ("scope", "metric_basis", "currency", "timezone", "attribution_window")
        for v in [metadata.get(k)]
    }


class Reviews:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.reports = Reporting(root, store)
        self.features = Features(store)

    def row(self, c, rid):
        row = c.execute("SELECT * FROM review_snapshots WHERE id=?", (rid,)).fetchone()
        if not row:
            raise KeyError(rid)
        return dict(row)

    def public(self, row):
        try:
            data = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            raise Conflict("冻结复盘内容损坏。") from None
        if sha(data) != row["snapshot_hash"]:
            raise Conflict("冻结复盘哈希校验失败。")
        return {
            "review_id": row["id"],
            "request_id": row["request_id"],
            "actor": row["actor"],
            "created_at": row["created_at"],
            "snapshot_hash": row["snapshot_hash"],
            "snapshot": data,
        }

    def get(self, rid):
        identifier(rid)
        with self.store.connect() as c:
            return self.public(self.row(c, rid))

    def export(self, rid):
        return encode(self.get(rid)).encode("utf-8")

    def listing(self, aid, limit=50):
        identifier(aid)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("列表条数须为 1–100。")
        with self.store.connect() as c:
            if not c.execute("SELECT 1 FROM platform_accounts WHERE id=?", (aid,)).fetchone():
                raise KeyError(aid)
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id AS review_id,account_id,start_date,end_date,snapshot_hash,actor,created_at FROM review_snapshots WHERE account_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
                    (aid, limit),
                )
            ]

    def preflight(self, c, cmd):
        count = 0
        selected = {}
        for day in dates(cmd.start_date, cmd.end_date):
            r = c.execute(
                "SELECT id FROM report_batches WHERE account_id=? AND start_date<=? AND end_date>=? ORDER BY seq DESC LIMIT 1",
                (cmd.account_id, day, day),
            ).fetchone()
            if r:
                selected[day] = r["id"]
                count += c.execute(
                    "SELECT count(*) FROM report_rows WHERE batch_id=? AND date=?", (r["id"], day)
                ).fetchone()[0]
            if count > MAX_ROWS:
                raise ValueError("冻结范围超过 20000 行，请缩小日期范围。")
        if (
            c.execute(
                "SELECT count(*) FROM material_bindings WHERE account_id=?", (cmd.account_id,)
            ).fetchone()[0]
            > MAX_MATERIALS
        ):
            raise ValueError("账户已关联素材超过 500，请使用较小的复盘数据集。")
        return selected

    def create(self, value):
        cmd = parse(FreezeInput, value)
        if not enabled():
            raise ValueError("冻结复盘入口未启用。")
        command_hash = sha(cmd.model_dump())
        with self.store.transaction() as c, localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            old = c.execute(
                "SELECT * FROM review_snapshots WHERE request_id=?", (cmd.request_id,)
            ).fetchone()
            if old:
                if old["command_hash"] != command_hash:
                    raise Conflict("该 request_id 已冻结另一份复盘，请使用新标识。")
                return self.public(dict(old))
            selected = self.preflight(c, cmd)
            report = self.reports.dashboard(
                cmd.account_id,
                cmd.start_date,
                cmd.end_date,
                connection=c,
                batch_ids=list(set(selected.values())),
            )
            bindings = {
                r["material_id"]: dict(r)
                for r in c.execute(
                    "SELECT * FROM material_bindings WHERE account_id=? ORDER BY material_id",
                    (cmd.account_id,),
                )
            }
            mids = sorted(set(bindings) | {r["material_id"] for r in report["rows"]})
            if len(mids) > MAX_MATERIALS or len(mids) * len(report["daily"]) > MAX_CELLS:
                raise ValueError("冻结范围超过 500 个素材或 15500 个素材日，请缩小范围。")
            selected_dates = defaultdict(list)
            day_batches = {}
            batch_map = {b["id"]: b for b in report["batches"]}
            for daily in report["daily"]:
                batch = batch_map.get(selected.get(daily["date"]))
                day_batches[daily["date"]] = batch
                if batch:
                    selected_dates[batch["id"]].append(daily["date"])
            sources = []
            source_records = []
            remaining = MAX_SOURCE_BYTES
            for batch in sorted(report["batches"], key=lambda b: b["seq"]):
                _, size = checked_file(self.root, batch["path"], batch["sha256"], remaining)
                remaining -= size
                row_hash = sha(source_rows(c, batch["id"], selected_dates[batch["id"]]))
                source_records.append(
                    (
                        batch["id"],
                        batch["path"],
                        batch["sha256"],
                        encode(selected_dates[batch["id"]]),
                        row_hash,
                    )
                )
                sources.append(
                    {
                        k: batch[k]
                        for k in (
                            "id",
                            "seq",
                            "start_date",
                            "end_date",
                            "source",
                            "sha256",
                            "actor",
                            "created_at",
                        )
                    }
                    | {
                        "selected_dates": selected_dates[batch["id"]],
                        "selected_rows_hash": row_hash,
                        "source_bytes": size,
                        "source_integrity_at_capture": "sha256_verified",
                        "declared_context": declared_context(batch),
                        "metadata_sha256": hashlib.sha256(batch["metadata"].encode()).hexdigest(),
                    }
                )
            contract = metric_contract(report["account"])
            windows = {
                b["declared_context"]["attribution_window"]
                for b in sources
                if b["declared_context"]["attribution_window"]
            }
            if len(windows) == 1 and all(
                b["declared_context"]["attribution_window"] for b in sources
            ):
                contract["attribution_window"] = next(iter(windows))
                contract["attribution_window_status"] = "source_declared;not_independently_verified"
            issues = []
            for b in sources:
                declared = b["declared_context"]
                for key, expected in [
                    ("currency", report["account"]["currency"]),
                    ("timezone", report["account"]["timezone"]),
                    ("metric_basis", "payment_material_v1"),
                ]:
                    if declared[key] and declared[key] != expected:
                        issues.append(
                            {
                                "batch_id": b["id"],
                                "kind": "incompatible_" + key,
                                "declared": declared[key],
                            }
                        )
            if len(windows) > 1:
                issues.append({"kind": "incompatible_attribution_windows"})
            aggregation_allowed = not issues
            contract["derived_metrics_status"] = (
                "allowed_under_declared_import_contract"
                if aggregation_allowed
                else "disabled_incompatible_sources"
            )
            rows = {(r["date"], r["material_id"]): r for r in report["rows"]}
            per_day = defaultdict(int)
            per_material = defaultdict(list)
            for r in report["rows"]:
                per_day[r["date"]] += 1
                per_material[r["material_id"]].append(r)
            grid = []
            materials = []
            links = []
            for mid in mids:
                material_grid = []
                for day in report["daily"]:
                    row = rows.get((day["date"], mid))
                    batch = day_batches[day["date"]]
                    metrics = {k: row[k] if row else None for k in METRICS}
                    availability = (
                        "reported"
                        if row
                        else "missing_report"
                        if not day["covered"]
                        else "covered_empty"
                        if not per_day[day["date"]]
                        else "not_reported"
                    )
                    cell = {
                        "account_id": cmd.account_id,
                        "date": day["date"],
                        "material_id": mid,
                        "availability": availability,
                        "batch_id": batch["id"] if batch else None,
                        "metrics": metrics,
                        "missing_metrics": [k for k, v in metrics.items() if v is None],
                        "metric_context_status": "import_contract_declared"
                        if aggregation_allowed
                        else "incompatible_sources",
                        "ratios": ratios(metrics)
                        if aggregation_allowed
                        else dict.fromkeys(ratios(metrics)),
                    }
                    grid.append(cell)
                    material_grid.append(cell)
                observed = (
                    aggregate(per_material[mid]) if aggregation_allowed else dict.fromkeys(METRICS)
                )
                interval = (
                    aggregate([r["metrics"] for r in material_grid])
                    if aggregation_allowed
                    else dict.fromkeys(METRICS)
                )
                binding = bindings.get(mid)
                feature = None
                binding_status = "unbound"
                if binding:
                    feature, binding_status = self.features.capture(c, binding)
                materials.append(
                    {
                        "material_id": mid,
                        "reported_days": sum(
                            r["availability"] == "reported" for r in material_grid
                        ),
                        "missing_dates": [
                            r["date"] for r in material_grid if r["availability"] != "reported"
                        ],
                        "observed_totals": observed,
                        "interval_totals": interval,
                        "observed_ratios": ratios(observed),
                        "interval_ratios": ratios(interval),
                        "binding": binding,
                        "binding_status": binding_status,
                        "creative_feature": feature,
                    }
                )
                links.append(
                    (
                        mid,
                        feature["feature_id"] if feature else None,
                        binding["job_id"] if binding else None,
                    )
                )
            account = {
                k: report["account"][k]
                for k in ("id", "name", "platform", "advertiser_id", "currency", "timezone")
            }
            feature_ids = sorted({x[1] for x in links if x[1]})
            label_upper = (
                c.execute(
                    "SELECT COALESCE(max(seq),0) FROM creative_labels WHERE feature_id IN ("
                    + ",".join("?" for _ in feature_ids)
                    + ")",
                    feature_ids,
                ).fetchone()[0]
                if feature_ids
                else 0
            )
            frozen_daily = [
                {
                    **day,
                    "totals": day["totals"] if aggregation_allowed else dict.fromkeys(METRICS),
                    "batch_id": selected.get(day["date"]),
                    "availability": "reported"
                    if per_day[day["date"]]
                    else "covered_empty"
                    if day["covered"]
                    else "missing_report",
                    "declared_context": declared_context(day_batches[day["date"]])
                    if day_batches[day["date"]]
                    else None,
                }
                for day in report["daily"]
            ]
            data = {
                "schema_version": 1,
                "algorithm_version": ALGORITHM_VERSION,
                "account": account,
                "start_date": cmd.start_date,
                "end_date": cmd.end_date,
                "status": report["status"] if aggregation_allowed else "partial",
                "batch_seq_upper_bound": c.execute(
                    "SELECT COALESCE(max(seq),0) FROM report_batches WHERE account_id=?",
                    (cmd.account_id,),
                ).fetchone()[0],
                "label_seq_upper_bound": label_upper,
                "metric_contract": contract,
                "source_context_issues": issues,
                "aggregation_allowed": aggregation_allowed,
                "missing_dates": report["missing_dates"],
                "totals": report["totals"] if aggregation_allowed else dict.fromkeys(METRICS),
                "observed_totals": report["observed_totals"]
                if aggregation_allowed
                else dict.fromkeys(METRICS),
                "ratios": report["ratios"]
                if aggregation_allowed
                else dict.fromkeys(report["ratios"]),
                "daily": frozen_daily,
                "material_daily": grid,
                "materials": materials,
                "batches": sources,
                "material_universe_policy": "observed_rows_union_local_bindings;not_all_platform_inventory",
                "coverage_policy": "latest_complete_batch_per_day;absent_material_unknown_not_zero",
                "notes": report["notes"]
                + [
                    "描述性复盘；不做因果归因、胜出判断或自动投放。",
                    "归因窗口未知或来源口径未独立核验时，不作可比性或因果结论。",
                ],
            }
            payload = encode(data)
            if len(payload.encode()) > MAX_PAYLOAD:
                raise ValueError("冻结结果超过 8 MiB，请缩小范围。")
            rid = uuid.uuid4().hex
            now = time.time()
            c.execute(
                "INSERT INTO review_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    cmd.request_id,
                    command_hash,
                    cmd.account_id,
                    cmd.start_date,
                    cmd.end_date,
                    sha(data),
                    payload,
                    cmd.actor,
                    now,
                ),
            )
            c.executemany(
                "INSERT INTO review_sources VALUES(?,?,?,?,?,?)",
                [(rid, *r) for r in source_records],
            )
            c.executemany(
                "INSERT INTO review_feature_links VALUES(?,?,?,?)", [(rid, *r) for r in links]
            )
            result = self.public(self.row(c, rid))
        return result

    def source(self, rid, bid):
        identifier(rid)
        identifier(bid)
        self.get(rid)
        with self.store.connect() as c:
            r = c.execute(
                "SELECT * FROM review_sources WHERE review_id=? AND batch_id=?", (rid, bid)
            ).fetchone()
        if not r:
            raise KeyError(bid)
        return checked_file(self.root, r["path"], r["sha256"], MAX_SOURCE_BYTES)[0]

    def verify(self, rid):
        frozen = self.get(rid)
        sources = []
        remaining = MAX_SOURCE_BYTES
        with self.store.connect() as c:
            c.execute("BEGIN")
            for r in c.execute(
                "SELECT * FROM review_sources WHERE review_id=? ORDER BY batch_id", (rid,)
            ):
                available = True
                reason = None
                try:
                    _, size = checked_file(self.root, r["path"], r["sha256"], remaining)
                    remaining -= size
                except Conflict:
                    available = False
                    reason = "source_missing_changed_or_over_limit"
                rows_match = (
                    sha(source_rows(c, r["batch_id"], json.loads(r["selected_dates"])))
                    == r["selected_rows_hash"]
                )
                sources.append(
                    {
                        "batch_id": r["batch_id"],
                        "available": available and rows_match,
                        "file_hash_matches": available,
                        "normalized_rows_match": rows_match,
                        "reason": reason or (None if rows_match else "normalized_rows_changed"),
                    }
                )
            features = []
            for material in frozen["snapshot"]["materials"]:
                f = material["creative_feature"]
                if not f:
                    continue
                row = c.execute(
                    "SELECT payload,feature_hash FROM creative_features WHERE id=?",
                    (f["feature_id"],),
                ).fetchone()
                features.append(
                    {
                        "feature_id": f["feature_id"],
                        "registered_feature_hash_matches": bool(
                            row and sha(json.loads(row["payload"])) == f["feature_hash"]
                        ),
                        "video_bytes_checked": False,
                    }
                )
        return {
            "review_id": rid,
            "snapshot_hash_valid": True,
            "sources": sources,
            "features": features,
            "verification_time": time.time(),
            "verification_is_current_observation": True,
        }
