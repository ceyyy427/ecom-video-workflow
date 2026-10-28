"""Account × content × date observations, separate from paid-ad reporting.

No cumulative-to-daily differencing, zero filling or causal attribution.
"""

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from ..media import safe_path
from .contracts import Strict
from .records import encoded

METRICS = ("views", "likes", "comments", "shares", "collects", "downloads", "clicks")


class MetricContract(Strict):
    counting: Literal["daily", "cumulative"]
    timezone: Literal["Asia/Shanghai"]
    observed_at: str = Field(min_length=20, max_length=40)
    metric_definitions: dict[str, str]
    currency: None = None
    attribution_window: None = None


def count(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value):
        raise ValueError("次数须为非负整数字符串；空白保留缺失，不能用科学计数、公式或小数")
    return value


def build_batch(records, source, contract, rows):
    cfg = MetricContract.model_validate(contract)
    observed = datetime.fromisoformat(cfg.observed_at)
    if observed.tzinfo is None:
        raise ValueError("观测时间须包含时区")
    if set(cfg.metric_definitions) - set(METRICS) or any(
        not 1 <= len(v.strip()) <= 240 for v in cfg.metric_definitions.values()
    ):
        raise ValueError("请填写支持指标的完整口径说明")
    if not 1 <= len(rows) <= 10000:
        raise ValueError("报表须有1–10000行")
    output, seen = [], set()
    for row in rows:
        content = row["content_id"]
        if (
            not isinstance(content, str)
            or not 1 <= len(content) <= 256
            or any(ord(c) < 33 for c in content)
        ):
            raise ValueError("作品ID必须保持原始字符串，不能留空或包含空白")
        day = date.fromisoformat(row["metric_date"])
        if day > observed.astimezone(ZoneInfo(cfg.timezone)).date():
            raise ValueError("指标日期不能晚于观测时间")
        key = (content, day.isoformat())
        if key in seen:
            raise ValueError("同一报表内作品×日重复，不能重复汇总")
        seen.add(key)
        values = {m: count(row.get(m)) for m in METRICS}
        if any(v is not None and m not in cfg.metric_definitions for m, v in values.items()):
            raise ValueError("有数值的指标必须提供口径，不能猜测列含义")
        output.append(
            {
                "content_ref": content,
                "metric_date": day.isoformat(),
                "values": values,
                "missing_reasons": {
                    m: "报表未提供该值或该列，不补零" for m, v in values.items() if v is None
                },
            }
        )
    src = source["payload"]
    return records.put(
        "observation_batch",
        {
            "schema_version": "ObservationBatch.v1",
            "source_ref": source["id"],
            "source_sha256": src["sha256"],
            "platform": src["platform"],
            "account_ref": src["account_ref"],
            "source_grade": src["ownership"],
            "dataset_kind": "organic",
            **cfg.model_dump(),
            "rows": sorted(output, key=lambda r: (r["content_ref"], r["metric_date"])),
            "causal_inference": False,
        },
        files=source["files"],
    )


def import_csv(records, source_id, contract):
    source = records.get(source_id, "source")
    if len(source["files"]) != 1 or not source["files"][0]["path"].endswith(".csv"):
        raise ValueError("请选择已冻结的UTF-8 CSV来源")
    raw = safe_path(records.root, source["files"][0]["path"]).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    headers = reader.fieldnames or []
    if (
        len(headers) != len(set(headers))
        or set(headers) - {*METRICS, "content_id", "metric_date"}
        or not {"content_id", "metric_date"} <= set(headers)
    ):
        raise ValueError("CSV须含content_id、metric_date及明确的次数列；广告报表请用原投放复盘入口")
    rows = list(reader)
    if any(None in r or None in r.values() for r in rows):
        raise ValueError("CSV行列数不一致")
    return build_batch(records, source, contract, rows)


def import_official(records, result):
    account = records.get(result["account_ref"], "connection")["payload"]
    if (
        account.get("ownership") != "oauth_verified_owner"
        or result["platform"] != account["platform"]
    ):
        raise ValueError("官方观测须绑定本次已验证的本人授权")
    raw = encoded(result).encode()
    import hashlib

    src = records.freeze_bytes(
        "source",
        {
            "account_ref": result["account_ref"],
            "platform": "douyin",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "filename": "official-read.json",
            "ownership": "official_own_public_video",
            "declaration": "固定本人公开作品只读接口",
        },
        raw,
        ".json",
    )
    contract = {
        k: result[k]
        for k in ("counting", "timezone", "observed_at", "currency", "attribution_window")
    }
    definitions = {
        "views": "抖音本人公开作品statistics.play_count实时累计次数",
        "likes": "statistics.digg_count实时累计次数",
        "comments": "statistics.comment_count实时累计次数",
        "shares": "statistics.share_count实时累计次数",
        "downloads": "statistics.download_count实时累计次数",
    }
    rows = [
        {"content_id": r["content_ref"], "metric_date": result["metric_date"], **r["values"]}
        for r in result["rows"]
    ]
    return build_batch(records, src, {**contract, "metric_definitions": definitions}, rows)


def freeze_observations(records, batch_ids):
    if not 1 <= len(batch_ids) <= 30 or len(set(batch_ids)) != len(batch_ids):
        raise ValueError("请选择1–30份不重复观测批次")
    batches = [records.get(oid, "observation_batch") for oid in batch_ids]
    contracts = [
        {
            k: b["payload"][k]
            for k in (
                "counting",
                "timezone",
                "metric_definitions",
                "dataset_kind",
                "currency",
                "attribution_window",
            )
        }
        for b in batches
    ]
    if any(c != contracts[0] for c in contracts):
        raise ValueError("累计/每日、时区或指标口径不同，请分别冻结，不能混算")
    registrations = []
    for account in {b["payload"]["account_ref"] for b in batches}:
        registrations.extend(records.matches("publication_registration", {"account_ref": account}))
    lookup = {
        (r["payload"]["platform"], r["payload"]["account_ref"], r["payload"]["content_ref"]): r
        for r in registrations
    }
    output, seen, files = [], set(), {}
    for b in batches:
        p = b["payload"]
        for file in b["files"]:
            files[file["path"]] = file
        for raw in p["rows"]:
            key = (p["platform"], p["account_ref"], raw["content_ref"], raw["metric_date"])
            if key in seen:
                raise ValueError("作品×日跨批次重复；保留不同观测，分别冻结比较，不覆盖原值")
            seen.add(key)
            binding = lookup.get(key[:3])
            output.append(
                {
                    **raw,
                    "platform": p["platform"],
                    "account_ref": p["account_ref"],
                    "observed_at": p["observed_at"],
                    "source_ref": p["source_ref"],
                    "batch_ref": b["id"],
                    "source_grade": p["source_grade"],
                    "binding_status": "declared_mapping" if binding else "unlinked",
                    "registration_ref": binding["id"] if binding else None,
                    "binding": binding["payload"] if binding else None,
                    "binding_missing_reason": None
                    if binding
                    else "未登记本账户作品与成片版本的对应关系",
                }
            )
    if len(output) > 10000:
        raise ValueError("单快照最多10000行，请分组冻结")
    daily = contracts[0]["counting"] == "daily"
    groups = {}
    for row in output:
        groups.setdefault((row["platform"], row["account_ref"], row["content_ref"]), []).append(
            row["metric_date"]
        )
    gaps = []
    for key, days in groups.items():
        first, last = date.fromisoformat(min(days)), date.fromisoformat(max(days))
        if (last - first).days > 365:
            raise ValueError("单快照同一作品跨度最多366天，请按期间分别冻结")
        missing = [
            (first + timedelta(days=i)).isoformat()
            for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).isoformat() not in days
        ]
        if missing:
            gaps.append(
                {
                    "platform": key[0],
                    "account_ref": key[1],
                    "content_ref": key[2],
                    "missing_dates": missing[:366],
                }
            )
    totals = (
        {
            m: str(sum(int(r["values"][m]) for r in output))
            if all(r["values"][m] is not None for r in output) and not gaps
            else None
            for m in METRICS
        }
        if daily
        else None
    )
    return records.put(
        "observation_snapshot",
        {
            "schema_version": "ObservationSnapshot.v1",
            **contracts[0],
            "batch_refs": sorted(batch_ids),
            "rows": sorted(
                output, key=lambda r: (r["account_ref"], r["content_ref"], r["metric_date"])
            ),
            "aggregation_allowed": daily and not gaps,
            "totals": totals,
            "coverage_gaps": gaps,
            "total_scope": "仅这些已报告日期与作品；不能推断未报告日期",
            "causal_inference": False,
            "not_daily_reason": None if daily else "实时累计观测不相加、不差分冒充日增量",
        },
        files=list(files.values()),
    )
