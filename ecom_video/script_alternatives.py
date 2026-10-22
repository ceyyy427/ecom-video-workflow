"""Stateless local alternatives. Only explicit adoption creates a pending draft."""

from .creative import Brief, signature
from .generation import validate_scenes
from .semantic_mix import strategy

PROFILES = {
    "overview": (
        "整体与细节",
        "先看整体，再看细节。",
        ["video", "image", "detail", "data", "action", "scene", "sales", "text"],
    ),
    "details": (
        "细节与依据",
        "了解这款产品的几个细节。",
        ["detail", "data", "video", "image", "action", "scene", "sales", "text"],
    ),
    "scene": (
        "使用与场景",
        "挑选之前，先看实际使用的样子。",
        ["scene", "action", "video", "image", "detail", "data", "sales", "text"],
    ),
}


def alternatives(product, facts, brief, *, assets=None, constraints=None):
    brief = Brief.model_validate(brief or {}).model_dump()
    assets, constraints = assets or [], constraints or {}
    basis = signature(
        {
            "version": 2,
            "revision": product["revision"],
            "review": product["current_review_id"],
            "facts": facts,
            "brief": brief,
            "material_assets": assets,
            "constraints": constraints,
        }
    )
    classified = []
    for i, fact in enumerate(facts):
        job = {"script": fact["text"]}
        classified.append((i, fact, strategy(job, 0, {"kind": "video"})["kind"]))
    result = []
    from .generation import compose_directed
    from .readiness import check_materials

    availability = check_materials([f["text"] for f in facts], assets, constraints=constraints)
    availability_rank = {"suggestion": 0, "unknown": 1, "gap": 2}
    for key, (name, hook, order) in PROFILES.items():
        if key == "overview":
            hook = compose_directed(facts, brief)[0]["text"]
        if key == "scene" and not any(a["kind"] == "video" for a in assets):
            hook = "别急着下结论，先把产品看清。"
        ordered = sorted(
            classified,
            key=lambda f: (
                availability_rank[availability["lines"][f[0]]["status"]],
                order.index(f[2]),
                f[0],
            ),
        )[:6]
        rows = [{"text": hook, "fact_ids": [], "intent": "hook", "brief": brief}]
        rows += [{"text": f["text"], "fact_ids": [f["id"]]} for _, f, _ in ordered]
        rows += [{"text": "请结合自己的使用需求选择。", "fact_ids": [], "intent": "closing"}]
        rows = validate_scenes(rows, facts)
        job = {
            "title": product["title"],
            "script": "\n".join(s["text"] for s in rows),
            "provenance": {"facts": facts, "scenes": rows},
        }
        plans = [strategy(job, i, {"kind": "video"}) for i in range(len(rows))]
        for row, plan in zip(rows, plans, strict=True):
            row["visual_hint"] = plan["explanation"]
        result.append(
            {
                "id": key,
                "name": name,
                "payload": rows,
                "shot_strategies": plans,
                "human_confirmation_required": True,
            }
        )
    from .production_proposals import enrich_candidates

    enrich_candidates(result, product, brief, assets, constraints, facts)
    return {
        "version": 2,
        "basis": basis,
        "revision": product["revision"],
        "brief": brief,
        "candidates": result,
        "method": "本机有限叙事编排；三种讲法仅重排完整确认事实与中性句，不是模型自由改写。不覆盖当前确认稿，采用后仍需人工确认。",
    }
