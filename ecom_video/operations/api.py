"""Domestic content drafts use existing freezes/queue; no new execution or approvals."""

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import Field

from ..content_plan import ContentBrief
from ..db import Conflict
from ..idea_media import freeze_materials, resolve
from ..idea_plans import IdeaPlans
from ..idea_renderer import engine_key
from ..products import Products
from .contracts import ColorPolicy, ObjectRef, Strict, SuiteBrief
from .planner import plan_content
from .resources import load_resources


class ContentRequest(Strict):
    brief: SuiteBrief
    expected_project_revision: int | None = Field(default=None, ge=0)


def enabled():
    return os.getenv("ECOM_DOMESTIC_CONTENT", "1") != "0"


def prepare(root, store, request):
    brief = request.brief
    old = brief.content_brief
    if old is None:
        raise ValueError("请填写创作主题与资料")
    if brief.evidence_refs or brief.material_refs:
        raise ValueError("证据由当前项目解析；素材请使用含所属项目的原创意引用")
    evidence = {"source_state": "declared_unconfirmed"}
    guard = None
    if brief.project_id:
        if (
            not brief.product_ref
            or brief.product_ref.id != brief.project_id
            or brief.product_ref.revision is None
            or request.expected_project_revision is None
        ):
            raise ValueError("引用已有商品须提供当前项目和产品版本")
        products = Products(store)
        product = products.get(brief.project_id)
        if product["revision"] != brief.product_ref.revision:
            raise Conflict("产品资料版本已变化，请重新载入")
        facts = products.confirmed_facts(product)
        if old.data:
            raise ValueError("引用已确认项目时，请先在商品资料中核对新增数值，不混用表单数据")
        short = [f for f in facts if len(f["text"]) <= 100][:8]
        if not short:
            raise ValueError("请先确认一条不超过100字的完整事实，不截断原始条件")
        if len(product["title"]) > 60:
            raise ValueError("项目标题超过60字，请先提供保留完整型号的简短标题")
        old = ContentBrief.model_validate(
            {
                **old.model_dump(),
                "subject": product["title"],
                "facts": [
                    {
                        "text": f["text"],
                        "source": f["locator"]
                        if len(f["locator"]) <= 200
                        else "项目已确认事实：" + f["id"],
                    }
                    for f in short
                ],
            }
        )
        evidence.update(
            source_state="confirmed_in_parent",
            parent_project_id=brief.project_id,
            project_revision=request.expected_project_revision,
            product_revision=product["revision"],
            review_id=product["current_review_id"],
            fact_ids=[f["id"] for f in short],
        )

        def guard(c):
            row = c.execute(
                "SELECT revision,settings FROM customer_projects WHERE product_id=?",
                (brief.project_id,),
            ).fetchone()
            current = products._row(c, brief.project_id)
            if (
                not row
                or row["revision"] != request.expected_project_revision
                or current["revision"] != product["revision"]
                or current["current_review_id"] != product["current_review_id"]
            ):
                raise Conflict("项目或事实已变化，请按当前版本重新生成")
            return row

        with store.connect() as c:
            parent = guard(c)
        target = json.loads(parent["settings"]).get("identity_lock")
        evidence["identity_target"] = target
        if any(r.origin == "customer" and r.project_id != brief.project_id for r in old.materials):
            raise Conflict("已有事实只绑定当前商品；其他项目的素材请先在客户工作台核对后再加入")
        if target:
            policy = ColorPolicy(
                product_id=brief.project_id, mode="single", colors=[target["color"]]
            )
            if brief.sku_color_policy and brief.sku_color_policy != policy:
                raise Conflict("配色要求与当前项目的单色锁定不一致")
            brief = brief.model_copy(update={"sku_color_policy": policy})
        brief = brief.model_copy(
            update={
                "evidence_refs": [
                    ObjectRef(
                        kind="fact_review",
                        id=product["current_review_id"],
                        revision=product["revision"],
                    )
                ],
                "content_brief": old,
            }
        )
    elif brief.product_ref or request.expected_project_revision is not None:
        raise ValueError("商品引用须绑定已有客户项目")
    materials = resolve(root, store, old)
    target = evidence.get("identity_target")
    if target and any(
        a["metadata"].get("identity")
        and any(a["metadata"]["identity"].get(k) != target[k] for k in ("sku", "color"))
        for a in materials
    ):
        raise Conflict("素材的已标注款式/配色与当前商品不一致")
    if brief.sku_color_policy:
        colors = set(brief.sku_color_policy.colors)
        if any(
            a["metadata"].get("identity", {}).get("color") not in colors
            for a in materials
            if a["metadata"].get("identity", {}).get("color")
        ):
            raise Conflict("已标注素材配色与本次单色要求不一致，请核对再生成")
    evidence["materials"] = freeze_materials(root, materials)
    return brief, evidence, guard


def router(root, store):
    api = APIRouter(prefix="/api/operations")

    @api.get("/capabilities")
    def capabilities():
        valid = True
        try:
            load_resources()
        except (ValueError, OSError):
            valid = False
        return {
            "phase": "D1",
            "content_enabled": enabled() and valid,
            "resources_valid": valid,
            "model_policy": "local_first",
            "cloud_calls": False,
            "platform_writes": False,
            "preview_seconds": 7,
            "target_seconds": [15, *range(20, 31)],
            "planning_backend": "bounded_rules",
            "human_gates": ["facts", "script", "style", "voice_alignment", "film_review"],
        }

    @api.post("/plans", status_code=201)
    def create(data: ContentRequest):
        if not enabled():
            raise HTTPException(403, "国内内容编排已关闭，仍可使用原创意入口")
        resources = load_resources()
        brief, evidence, guard = prepare(root, store, data)
        plan = plan_content(brief, evidence, resources, engine=engine_key())
        return IdeaPlans(root, store).persist(plan, guard=guard)

    return api
