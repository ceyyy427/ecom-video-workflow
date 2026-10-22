"""Server-owned joint creative plans; adoption creates only an unconfirmed draft."""

import json
import time

from .creative import signature
from .db import Conflict
from .material_suitability import material_inputs
from .media import digest, safe_path
from .production_proposals import ProposalGuard, analysis_basis, enrich_candidates
from .script_alternatives import alternatives
from .semantic_mix import quotation, strategy
from .spoken_copy import PROTECTED, speak

VERSION = "joint-creative-v1"


def line_plan(job, i, style, category=""):
    spec = strategy(job, i, {"kind": "video"})
    kind = spec["kind"]
    if kind == "video" and any(
        w in job["script"].splitlines()[i] for w in ("口袋", "拉链", "抽绳")
    ):
        kind = "detail"
    if any(
        w in job["script"].splitlines()[i] for w in ("拉开", "开合", "拉一下", "收紧", "抽绳调节")
    ):
        kind = "action"
    qualified = bool(PROTECTED.search(job["script"].splitlines()[i]) and quotation(job, i))
    if qualified and kind != "action":
        kind = "qualified_fact"
    primary = style["prompt_direction"]["cards"][0]["id"]
    card = (
        None
        if kind == "action" or i == len(job["script"].splitlines()) - 1
        else primary
        if i == 0
        else "fact-row-soft-v1"
        if kind in ("sales", "data", "qualified_fact")
        else "detail-bracket-soft-v1"
        if kind == "detail"
        else "garment-portal-v1"
        if kind == "scene" and ("衣" in category or "服" in category)
        else "food-portal-v1"
        if kind == "scene" and ("食品" in category or "水果" in category)
        else "warm-portal-v1"
        if kind == "scene"
        else "relay-soft-v1"
        if kind == "text"
        else primary
    )
    from .prompt_catalog import card_record

    record = card_record(card) if card else None
    return {
        "line": i + 1,
        "kind": kind,
        "requires_quotation": spec["requires_quotation"] or qualified,
        "card": record,
        "reason": f"{kind}：{spec['explanation']}"
        + ("；完整动作优先，不叠加卡片" if kind == "action" else ""),
        "fallback": "素材清晰度/时长/事实条件不足时保留原画与字幕；动作原速连续，仍需人工选段与听审",
        "status": spec["status"],
        "missing": spec["missing"],
    }


def current_plan(product):
    draft = next(
        (d for d in product["script_drafts"] if d["id"] == product["current_draft_id"]), None
    )
    if not draft:
        return None
    for row in reversed(product["events"]):
        try:
            event = json.loads(row["message"])
        except (TypeError, ValueError):
            continue
        if (
            isinstance(event, dict)
            and event.get("kind") == VERSION
            and event.get("draft_id") == draft["id"]
        ):
            plan = event["plan"]
            if plan["payload"] == draft["payload"]:
                return plan
    return None


def execution_plan(job):
    plan = (job.get("provenance") or {}).get("creative_plan")
    if (
        plan
        and plan.get("version") == VERSION
        and [s["text"] for s in plan.get("payload", [])] == job["script"].splitlines()
    ):
        return plan
    return None


def proposals(service, pid, data):
    p = service.get(pid)
    product = p["product"]
    if data["revision"] != p["revision"] or data["product_revision"] != product["revision"]:
        raise Conflict("商品或素材已变化，请重新比较联合方案")
    facts = service.products.confirmed_facts(product)
    for source in product["sources"]:
        path = safe_path(service.root, source["path"])
        if not path.is_file() or digest(path) != source["sha256"]:
            raise Conflict("资料文件已变化，请重新上传核对")
    assets, constraints = material_inputs(p)
    brief = p["settings"]["brief"]
    bundle = alternatives(product, facts, brief, assets=assets, constraints=constraints)
    for c in bundle["candidates"]:
        selected = [
            next(f for f in facts if f["id"] == row["fact_ids"][0])
            for row in c["payload"]
            if row["fact_ids"]
        ][:4]
        from .generation import validate_scenes

        c["payload"] = validate_scenes(speak(selected, brief, c["id"]), facts)
        job = {
            "script": "\n".join(s["text"] for s in c["payload"]),
            "provenance": {"facts": facts, "scenes": c["payload"]},
        }
        c["shot_strategies"] = [
            strategy(job, i, {"kind": "video"}) for i in range(len(c["payload"]))
        ]
    enrich_candidates(bundle["candidates"], product, brief, assets, constraints, facts)
    for c in bundle["candidates"]:
        job = {
            "script": "\n".join(s["text"] for s in c["payload"]),
            "provenance": {"facts": facts, "scenes": c["payload"]},
        }
        c.update(
            version=VERSION,
            voice=c["direction"]["voice"],
            narrative=c["direction"]["production"]["structure"],
            audience=brief["audience"],
            category=brief["category"],
            tone=brief["tone"],
            fact_review_id=product["current_review_id"],
            visual_plan=[
                line_plan(job, i, c["direction"], brief["category"])
                for i in range(len(c["payload"]))
            ],
            copy_policy="中性连接词＋完整确认原文；条件/数字/否定句不改写，非自由模型生成",
            source_facts=[f for f in facts if any(f["id"] in s["fact_ids"] for s in c["payload"])],
        )
    basis = signature(
        {
            "version": VERSION,
            "base": bundle["basis"],
            "settings": p["settings"],
            "customer_revision": p["revision"],
            "analyses": analysis_basis(p["media"]),
            "candidates": bundle["candidates"],
        }
    )
    for c in bundle["candidates"]:
        c["basis"] = basis
    bundle.update(
        version=VERSION,
        basis=basis,
        customer_revision=p["revision"],
        material_analysis=analysis_basis(p["media"]),
        method="三套联合创意：文稿、实拍、语义卡片与声音一起比较。预览不改稿，明确采用后仍待事实/稿件/方向/听核/最终风格/成片人工确认。口语稿使用受控本机组合，不是自由模型扩写。",
    )
    return bundle, p


class PlanReceipt(ProposalGuard):
    def __init__(self, p, bundle, candidate):
        super().__init__(p["id"], p["revision"], bundle["material_analysis"])
        self.plan = candidate

    def guard(self, c):
        super().guard(c)
        job = c.execute(
            "SELECT j.status FROM customer_projects p JOIN jobs j ON j.id=p.active_job_id WHERE p.product_id=?",
            (self.pid,),
        ).fetchone()
        if job and job[0] in ("queued", "validating", "rendering", "auditing"):
            raise Conflict("当前制作正在运行，请完成或取消后再采用新稿")

    def __call__(self, c, draft_id):
        record = {"kind": VERSION, "draft_id": draft_id, "plan": self.plan}
        c.execute(
            "INSERT INTO product_events(product_id,revision,message,created_at) SELECT id,revision,?,? FROM products WHERE id=?",
            (json.dumps(record, ensure_ascii=False), time.time(), self.pid),
        )
