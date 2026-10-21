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
    basis = signature(
        {
            "version": 1,
            "revision": product["revision"],
            "review": product["current_review_id"],
            "facts": facts,
            "brief": brief,
            **(
                {"material_assets": assets, "constraints": constraints}
                if constraints and constraints.get("material_checks")
                else {}
            ),
        }
    )
    classified = []
    for i, fact in enumerate(facts):
        job = {"script": fact["text"]}
        classified.append((i, fact, strategy(job, 0, {"kind": "video"})["kind"]))
    result = []
    for key, (name, hook, order) in PROFILES.items():
        ordered = sorted(classified, key=lambda f: (order.index(f[2]), f[0]))[:6]
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
        if constraints and constraints.get("material_checks"):
            from .material_suitability import check_materials, fit_summary

            result[-1]["material_fit"] = fit_summary(
                check_materials(job["script"].splitlines(), assets or [], constraints=constraints)
            )
    return {
        "version": 1,
        "basis": basis,
        "revision": product["revision"],
        "brief": brief,
        "candidates": result,
        "method": "本机有限叙事编排；三种讲法仅重排完整确认事实与中性句，不是模型自由改写。不覆盖当前确认稿，采用后仍需人工确认。",
    }
