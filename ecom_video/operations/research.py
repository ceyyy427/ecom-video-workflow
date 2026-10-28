"""Descriptive authorized samples and fact-bound strategy, using Decimal/stdlib.

Upstream's arithmetic-first split is retained; its foreign fee presets, float
parsing and missing-to-zero helpers are deliberately not imported.
"""

import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal, localcontext
from statistics import median

from ..content_plan import ContentBrief
from ..customer import Customers
from ..db import Conflict
from ..products import Products
from ..reporting import decimal_text, number
from .contracts import SuiteBrief
from .positioning import position


def analyze_market(records, raw, declared_scope, platform):
    if (
        platform not in ("douyin", "xiaohongshu")
        or not 1 <= len(declared_scope.strip()) <= 1000
        or not 1 <= len(raw) <= 2 * 1024**2
    ):
        raise ValueError("请提供平台、已获许可的样本范围说明及小于2MiB的UTF-8 CSV")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        columns = {"sku", "product_name", "price", "currency", "sampled_at", "source"}
        if set(reader.fieldnames or []) != columns or len(reader.fieldnames) != len(columns):
            raise ValueError()
        rows, seen, groups = [], set(), {}
        for i, row in enumerate(reader):
            if (
                None in row
                or any(v is None for v in row.values())
                or i >= 10000
                or any(len(v) > 500 for v in row.values())
            ):
                raise ValueError()
            if (
                not row["sku"].strip()
                or not row["product_name"].strip()
                or not row["source"].strip()
            ):
                raise ValueError()
            if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                raise ValueError()
            date.fromisoformat(row["sampled_at"])
            key = (row["sku"], row["sampled_at"], row["source"])
            if key in seen:
                raise ValueError()
            seen.add(key)
            price = number(row["price"], money=True)
            if price is not None:
                groups.setdefault(row["currency"], []).append(Decimal(price))
            rows.append({**row, "price": price})
        if not rows:
            raise ValueError()
    except (UnicodeError, ValueError, TypeError, csv.Error):
        raise ValueError(
            "样本CSV须含sku/product_name/price/currency/sampled_at/source，来源与币种不可空，价格未知留空，行不得重复"
        ) from None
    payload = {
        "schema_version": "ResearchDraft.v1",
        "platform": platform,
        "declared_scope": declared_scope,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": rows,
        "sample_count": len(rows),
        "sample_quality": "limited" if len(rows) < 5 else "declared_sample_only",
        "missing_price_rows": sum(r["price"] is None for r in rows),
        "price_groups": {
            cur: {
                "count": len(values),
                "min": decimal_text(min(values)),
                "max": decimal_text(max(values)),
                "median": decimal_text(median(values)),
            }
            for cur, values in groups.items()
        },
        "market_size": None,
        "market_size_missing_reason": "用户提供的样本没有全平台抽样框或总体覆盖证明",
        "review_status": "pending",
        "note": "币种分别统计；不换汇，不推断销量、热度、排名或全市场份额",
    }
    return records.freeze_bytes("research", payload, raw, ".csv")


def gross_margin(values):
    keys = (
        "sale_price",
        "cost",
        "shipping",
        "payment_fee",
        "other_cost",
        "platform_rate",
        "currency",
        "rate_effective_from",
        "rate_effective_until",
        "as_of",
    )
    missing = [k for k in keys if values.get(k) in (None, "")]
    if missing or set(values) - set(keys):
        return {
            "available": False,
            "missing": missing,
            "reason": "费用、费率、币种及生效区间须完整填写，不默认为零",
        }
    try:
        numbers = {k: Decimal(number(values[k], money=True)) for k in keys[:6]}
        if (
            numbers["sale_price"] <= 0
            or numbers["platform_rate"] > 1
            or not re.fullmatch(r"[A-Z]{3}", values["currency"])
        ):
            raise ValueError()
        if (
            not date.fromisoformat(values["rate_effective_from"])
            <= date.fromisoformat(values["as_of"])
            <= date.fromisoformat(values["rate_effective_until"])
        ):
            raise ValueError()
    except (ValueError, TypeError):
        return {
            "available": False,
            "missing": [],
            "reason": "数值、币种或费率生效日期无效；费率用0–1的小数，全部金额须同币种",
        }
    with localcontext() as context:
        context.prec = 50
        profit = numbers["sale_price"] * (1 - numbers["platform_rate"]) - sum(
            numbers[k] for k in ("cost", "shipping", "payment_fee", "other_cost")
        )
        ratio = profit / numbers["sale_price"]
    return {
        "available": True,
        "profit": format(profit.quantize(Decimal("0.01")), "f"),
        "margin_ratio": format(ratio.quantize(Decimal("0.000001")), "f"),
        "currency": values["currency"],
        "inputs": values,
        "scope": "仅所填费用的贡献试算；不含未提供的税费、退货、广告及其他支出，不自动改价",
    }


def create_strategy(records, product_id, expected_revision, audience, tone, research_id):
    product = Products(records.store).get(product_id)
    if product["revision"] != expected_revision:
        raise Conflict("商品资料已变化，请刷新后重新定位")
    facts = Products.confirmed_facts(product)
    if not facts or not 1 <= len(audience.strip()) <= 120 or not 1 <= len(tone.strip()) <= 120:
        raise ValueError("请先确认商品事实，再填写人群和气质")
    research = records.get(research_id, "research") if research_id else None
    project = Customers(records.root, records.store).get(product_id)
    materials = [{"metadata": a["metadata"]} for a in project["media"] if a["kind"] != "audio"]
    # Do not truncate a model/conditional fact to squeeze it into another contract.
    subject = product["title"]
    if len(subject) > 60:
        raise ValueError("请先提供不超过60字且保留完整型号的商品标题")
    brief = SuiteBrief(
        platform="douyin",
        audience=audience,
        tone=tone,
        objective="product_showcase",
        duration_s=24,
        content_brief=ContentBrief(idea=subject, subject=subject),
    )
    positioned = position(brief, facts, materials, "confirmed_in_parent")
    payload = {
        "schema_version": "StrategyDraft.v1",
        "product_id": product_id,
        "product_revision": expected_revision,
        "fact_review_id": product["current_review_id"],
        "fact_refs": [
            {"id": f["id"], "text": f["text"], "source_id": f["source_id"], "locator": f["locator"]}
            for f in facts
        ],
        "research_ref": research_id,
        "research_basis": research["basis"] if research else None,
        "positioning": positioned,
        "review_status": "pending",
        "causal_inference": False,
        "note": "市场样本只提供背景，不会变成此商品的性能事实；素材缺口继续保留",
    }

    def guard(c):
        current = Products(records.store)._row(c, product_id)
        if (
            current["revision"] != expected_revision
            or current["current_review_id"] != product["current_review_id"]
        ):
            raise Conflict("定位冻结前商品依据已变化，请重新生成")

    return records.put("strategy", payload, on_create=guard)


def strategy_state(records, oid):
    row = records.get(oid, "strategy")
    p = row["payload"]
    product = Products(records.store).get(p["product_id"])
    current = (
        product["revision"] == p["product_revision"]
        and product["current_review_id"] == p["fact_review_id"]
    )
    return {
        "record": row,
        "current": current,
        "reason": None if current else "商品事实或版本已变化，请重新生成；旧稿仅作历史记录",
    }
