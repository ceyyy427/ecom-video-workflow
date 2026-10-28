"""Compile domestic content decisions into the existing frozen preview protocol."""

import copy
import json
import re

from ..content_plan import build_plan
from ..creative import signature
from ..idea_media import source_windows
from ..semantic_mix import DETAIL
from ..spoken_copy import PROTECTED
from .content import LABELS, make_publication_copy, script_for
from .contracts import ObjectRef, SuitePlan
from .positioning import position

STRUCTURES = {
    "dark-keynote": "以字形遮罩登场，再用主视觉留白看清整体，适合先认商品。",
    "swiss-motion": "用局部急推抓住注意，再用短标注指出细节，强调观察落点。",
    "paper-popup": "形状展开接实拍，配柔和滑移，让场景与商品自然接力。",
    "kino-montage": "同帧多窗与短切交替，先给情境，再回到同一商品的可见细节。",
    "blueprint": "用扫描标注、整体与局部双窗解释结构；不展示未证实的内部原理。",
    "dataviz": "信息卡逐项展开，原文与局部并列；没有数值依据就不补造数据。",
}


def load_policy(resources):
    policy = json.loads(resources.read("domestic-d1-policy"))
    if policy.get("version") != "domestic-policy-v1" or {
        n["id"] for n in policy["narratives"]
    } != set(LABELS):
        raise ValueError("国内内容策略版本无效")
    return policy


def choose_material(materials, text, seconds, variant, used, preview_seconds=None):
    words = set(re.findall(r"口袋|拉链|袖口|下摆|抽绳|上身|切片|切面|果皮|倒水|开盖", text))
    ranked = sorted(
        materials,
        key=lambda a: (
            -(
                len([w for w in words if w in a.get("note", "") + a["name"]]) * 5
                + (2 if a["kind"] == "video" else 0)
            ),
            used.count(a["id"]),
        ),
    )
    for a in ranked:
        if a["kind"] == "image":
            return a, 0, "图片构图候选，非动作证据"
        start = a["source_in"]
        candidates = [start + used.count(a["id"]) * 4 + variant * 0.5, start + variant * 0.5, start]
        candidates += [r["start"] for r in a["metadata"].get("verified_visible_ranges", [])]
        candidates += [r["end"] for r in a["metadata"].get("complete_actions", [])]
        for at in candidates:
            if at < start or at + seconds > a["metadata"]["duration"] + 0.001:
                continue
            try:
                source_windows(a, at, seconds)
                if preview_seconds is not None:
                    source_windows(a, at, preview_seconds)
            except ValueError:
                continue
            status = (
                "已有检查范围内"
                if a["metadata"].get("inspection_status") == "current"
                else "按素材描述弱匹配，内容及同款仍待人工核对"
            )
            return a, at, status
    return None, 0, "缺少能安全覆盖本段的画面；仅预演图示，需补素材"


def plan_content(brief, evidence, resource_bundle, *, engine):
    if brief.content_brief is None:
        raise ValueError("请填写创作想法和完整资料")
    # A default 0 and a form's explicit 0.0 describe the same source interval.
    # Preserve the existing integral representation; never rewrite frozen records.
    refs = [
        r.model_copy(
            update={
                "source_in": int(r.source_in) if int(r.source_in) == r.source_in else r.source_in
            }
        )
        for r in brief.content_brief.materials
    ]
    brief = brief.model_copy(
        update={"content_brief": brief.content_brief.model_copy(update={"materials": refs})}
    )
    evidence = copy.deepcopy(evidence)
    for a in evidence.get("materials", []):
        if int(a["source_in"]) == a["source_in"]:
            a["source_in"] = int(a["source_in"])
    policy = load_policy(resource_bundle)
    old = brief.content_brief.model_copy(update={"audience": brief.audience, "tone": brief.tone})
    materials = copy.deepcopy(evidence.get("materials", []))
    p = build_plan(old, materials, engine=engine)
    p["version"] = "domestic-creative-v1"
    p["suite_brief"] = brief.model_dump()
    p["domestic_policy"] = policy
    p["source_context"] = {k: v for k, v in evidence.items() if k != "materials"}
    facts = [c for c in p["claims"] if c["id"].startswith("fact-")]
    positioning = position(
        brief, facts, materials, evidence.get("source_state", "declared_unconfirmed")
    )
    p["positioning"] = positioning
    core = positioning["core_selling_point"]
    ordered = ([core] if core else []) + [f for f in facts if not core or f["id"] != core["id"]]
    lookup = {s["id"]: s for s in p["options"]}
    options = []
    calm = bool(re.search("克制|平静|安静|柔和|沉静", brief.tone))
    for group in policy["narratives"]:
        narrative = group["id"]
        for variant, style in enumerate(group["styles"]):
            option = lookup[style]
            rows = script_for(
                p["subject"],
                positioning["category"],
                narrative,
                variant,
                ordered,
                brief.audience,
                brief.platform,
            )
            weights = [
                [3, 8, 8, 5],
                [2, 7, 9, 6],
                [4, 7, 8, 5],
                [2.5, 8.5, 8, 5],
                [3, 9, 7, 5],
                [2, 8, 10, 4],
            ][len(options)]
            frames = [round(w / sum(weights) * brief.duration_s * 30) for w in weights]
            frames[-1] += brief.duration_s * 30 - sum(frames)
            used = []
            unavailable = []
            for i, (scene, row) in enumerate(zip(option["scenes"], rows, strict=True)):
                seconds = frames[i] / 30
                required = max(seconds, option["preview_scene_seconds"][i]) if i < 2 else seconds
                asset, at, reason = choose_material(
                    materials,
                    row["text"],
                    required,
                    variant,
                    used,
                    option["preview_scene_seconds"][i] if i < 2 else None,
                )
                if asset:
                    used.append(asset["id"])
                elif materials:
                    unavailable.append(scene["id"])
                scene.update(
                    row,
                    seconds=seconds,
                    material_id=asset["id"] if asset else None,
                    source_in=at,
                    visual_reason=f"{LABELS[narrative]}：{reason}",
                )
                phrase = next(
                    (s.strip() for s in re.split("[，。！？；：]", row["text"]) if s.strip()), ""
                )
                detail = DETAIL.search(phrase)
                scene["headline"] = (
                    ""
                    if PROTECTED.search(row["text"])
                    else phrase
                    if len(phrase) <= 8
                    else detail.group()
                    if detail
                    else ""
                )
                if style == "dataviz":
                    scene["claim_ids"] += [
                        c["id"] for c in p["claims"] if c["id"].startswith("data-")
                    ]
                if narrative == "detail_explain":
                    scene["visual_reason"] += "；原文与画面并列核对，标注只解释可见细节"
            option.update(
                narrative=narrative,
                name=f"{LABELS[narrative]} · {option['name']}",
                script="\n".join(r["text"] for r in rows),
                feasibility="needs_materials"
                if unavailable
                else "ready_to_plan"
                if materials
                else "code_diagram_only",
                gaps=[f"{s} 缺少完整画面，请补素材或改稿" for s in unavailable],
                reason=f"面向{brief.audience}，以{brief.tone}讲“{p['subject']}”。{STRUCTURES[style]} 素材检查未知时仍须人工核对。",
                voice_suggestion={
                    "tone": "像自然分享，短句后留观察停顿"
                    if narrative == "scenario_share"
                    else "重点清楚，证据处放慢"
                    if narrative == "detail_explain"
                    else "克制留白"
                    if calm
                    else "简洁有力",
                    "speed": 0.95 if calm else 1.05,
                },
            )
            options.append(option)
    rank = {"product_showcase": 0, "scenario_share": 0, "detail_explain": 0}
    if brief.objective in rank:
        rank[brief.objective] += 10
    if re.search("通勤|周末|日常|家庭", brief.audience):
        rank["scenario_share"] += 2
    if re.search("细节|参数|为什么|依据", old.idea):
        rank["detail_explain"] += 2
    if calm:
        rank["product_showcase"] += 2
    options.sort(
        key=lambda o: (o["id"] != old.preferred if old.preferred else False, -rank[o["narrative"]])
    )
    p["options"] = options
    p["missing"] = list(
        dict.fromkeys(positioning["gaps"] + [g for o in options for g in o["gaps"]])
    )
    p["publication_copy"] = make_publication_copy(p, brief.platform)
    seed = signature(
        {
            "compiled": {k: v for k, v in p.items() if k != "basis"},
            "brief": brief.model_dump(),
            "evidence": evidence,
            "engine": engine,
            "fork": resource_bundle.fork_commit,
        }
    )
    plan_id = seed[:32]
    p["brief_record"] = {
        "id": seed[32:],
        "sha256": signature(brief.model_dump()),
        "value": brief.model_dump(),
    }
    suite = {
        "schema_version": "SuitePlan.v1",
        "plan_id": plan_id,
        "revision": 0,
        "brief_ref": ObjectRef(
            kind="creative_brief", id=seed[32:], sha256=p["brief_record"]["sha256"]
        ).model_dump(),
        "six_options": [
            {
                "id": o["id"],
                "narrative": o["narrative"],
                "hook": o["scenes"][0]["text"],
                "script_refs": [],
                "storyboard_ref": None,
                "voice_profile": {"provider": "none"},
                "render_recipe": o["native_style"],
                "evidence_refs": brief.evidence_refs
                and [r.model_dump() for r in brief.evidence_refs]
                or [],
                "feasibility": o["feasibility"],
            }
            for o in options
        ],
        "tasks": [],
        "gaps": [s[:120] for s in p["missing"][:30]],
        "cost_policy": {"max_cost_cny": "0"},
        "source_versions": [
            {
                "repository": "heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit",
                "commit": resource_bundle.upstream_commit,
            },
            {"repository": resource_bundle.fork_repository, "commit": resource_bundle.fork_commit},
        ],
    }
    suite["basis"] = signature(suite)
    p["suite_plan"] = SuitePlan.model_validate(suite).model_dump()
    p.pop("basis", None)
    p["basis"] = signature(p)
    return p
