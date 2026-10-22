"""Read-only bounded material coverage. Suggestions are never visual or SKU verification."""

import re

from .clip_grounding import NEGATIVE, UNCERTAIN, VOCABULARY, assess, requirements
from .creative import signature
from .production_direction import closing_reminder, folding_action, supports_action

VERSION = "material-readiness-v1"
# Editorial actions outside the measured local model vocabulary remain unverified.
EDITORIAL_ACTIONS = {
    "walk": "走动",
    "shoulder_bag": "背上(?:背)?包",
    "splash": "泼水|水花|水滴",
}


def required_actions(line):
    found = []
    for clause in re.split(r"[，。；！？,;.!?]", line):
        if re.search("不要|请勿|切勿|禁止|不必|无需|不用|不需要|没有|未", clause):
            continue
        if folding_action(clause):
            found.append("fold")
        for kind, pattern in (
            ("pour", "倒水|倒入|倾倒"),
            ("open_lid", "开盖|打开.*盖|旋开"),
            ("close_lid", "合上.*盖|盖上|关盖"),
            ("wear", "戴上|佩戴|戴在"),
            ("lift", "拿起|提起|取出"),
            *EDITORIAL_ACTIONS.items(),
        ):
            if re.search(pattern, clause):
                found.append(kind)
    return list(dict.fromkeys(found))


def action_occurrences(line):
    """Finite action spellings shared with voice timing, in actual script order."""
    from .product_motion import PATTERNS

    result = []
    patterns = {
        **PATTERNS,
        "fold": r"折叠|收拢|合拢|靠拢",
        "wear": r"戴上|佩戴|戴在",
        "lift": r"拿起|提起|取出",
        **EDITORIAL_ACTIONS,
    }
    patterns["open_lid"] += r"|(?:打开|拧开|旋开|揭开)[^，。；！？,;.!?]*?盖|旋开"
    patterns["close_lid"] += r"|合上[^，。；！？,;.!?]*?盖|盖上|关盖"
    for clause in re.split(r"[，。；！？,;.!?]", line):
        matches = sorted(
            (m.start(), m.end(), action)
            for action, pattern in patterns.items()
            for m in re.finditer(pattern, clause)
        )
        for start, _, action in matches:
            prefix = clause[max(0, start - 16) : start]
            if re.search(
                r"(?:不要|请勿|切勿|禁止|不必|无需|不用|不需要|不能|不可|没有|未|不|勿)(?:(?:手动|再次|再|先|急着|进行|去))*$",
                prefix,
            ):
                continue
            result.append(action)
    return result


def required_action(line):
    return next(iter(required_actions(line)), None)


def action_observed(candidate, action, line):
    if not action:
        return True
    if candidate["kind"] != "video":
        return False
    if action in EDITORIAL_ACTIONS:
        return False  # Requires manual selection; neither tags nor prose prove a complete action.
    if action == "fold":
        return supports_action(candidate, line)
    events = candidate.get("motion_check", {}).get("events", [])
    if any(
        e.get("kind") == action
        and candidate["start"] <= e.get("start", -1) < e.get("end", -1) <= candidate["end"]
        for e in events
    ):
        return True
    pattern = {
        "pour": "倒水|倒入|倾倒",
        "open_lid": "开盖|打开.*盖|旋开",
        "close_lid": "合上.*盖|盖上|关盖",
        "wear": "佩戴|戴上|戴在",
        "lift": "拿起|提起|取出",
    }[action]
    return any(
        re.search(pattern, tag)
        and not re.search("可|能够|支持|已|之后|状态", tag)
        and not NEGATIVE.search(tag)
        and not UNCERTAIN.search(tag)
        for tag in candidate["observation"].get("actions", [])
    )


def check_materials(lines, assets, durations=None, *, constraints=None):
    if not 1 <= len(lines) <= 30 or len(assets) > 100:
        raise ValueError("素材检查限1–30句、100份素材")
    measured = durations is not None
    durations = durations or [round(max(3, min(12, len(line) / 4)), 2) for line in lines]
    if len(durations) != len(lines):
        raise ValueError("素材检查时长与文稿不一致")
    if constraints and constraints.get("material_checks"):
        from .material_suitability import check_materials as enhanced_check

        return enhanced_check(lines, assets, durations if measured else None, constraints)
    pool, unknown = [], False
    visuals = [a for a in assets if a["kind"] != "audio"]
    for a in visuals:
        analysis = a["metadata"].get("content_analysis")
        if not analysis or analysis.get("source_sha256") != a["sha256"] or a.get("analysis_stale"):
            unknown = True
            continue
        for s in analysis.get("segments", [])[:40]:
            if not s["observation"].get("usable") or s.get("quality", {}).get("blank"):
                continue
            start = (
                max(s["start"], a["metadata"].get("source_in", 0)) if a["kind"] == "video" else 0
            )
            pool.append(
                {
                    "asset_id": a["id"],
                    "asset_name": a["name"],
                    "sha256": a["sha256"],
                    "kind": a["kind"],
                    "analysis_id": analysis.get("analysis_id"),
                    "start": start,
                    "end": min(s["end"], a["metadata"].get("duration", s["end"])),
                    "observation": s["observation"],
                    "motion_check": s.get("motion_check", {}),
                }
            )
    products = {"cup", "headphone", "bottle", "computer", "book", "bag", "plant"} & set(
        requirements("\n".join(lines))["required"]
    )
    product_label = VOCABULARY[next(iter(products))][0] if len(products) == 1 else None
    rows = []
    for i, (line, duration) in enumerate(zip(lines, durations, strict=True)):
        actions = required_actions(line)
        action = next(iter(actions), None)
        need = requirements(line)
        objects = set(need["required"]) - {"desk", "kitchen", "outdoor"}
        understood = bool(objects or need["excluded"] or product_label)
        relevant = [
            p
            for p in pool
            if assess(line, p)["eligible"]
            and (objects or not product_label or assess(product_label, p)["eligible"])
        ]
        # Pure reminder is an editorial product hold, not evidence of checking parameters.
        if closing_reminder(line, i, len(lines)):
            from .production_direction import outro_candidate

            relevant = [p for p in relevant if outro_candidate(p, lines, i, allow_image=True)]
        long = [
            p for p in relevant if p["kind"] == "image" or p["end"] - p["start"] >= duration - 0.001
        ]
        choices = [p for p in long if all(action_observed(p, action, line) for action in actions)]
        if not understood:
            choices = []
        status, code = (
            ("suggestion", "observed_candidate")
            if choices
            else (
                ("gap", "no_visuals")
                if not visuals
                else ("unknown", "analysis_missing_or_stale")
                if unknown
                else ("unknown", "unsupported_vocabulary")
                if not understood
                else ("gap", "unrelated_material")
                if not relevant
                else ("gap", "duration_short")
                if not long
                else ("gap", "action_not_observed")
            )
        )
        messages = {
            "observed_candidate": "发现候选，仍须回看动作、同款与连续性；不是自动确认",
            "no_visuals": "请补充商品实拍或图片",
            "analysis_missing_or_stale": "部分素材未识别或结果已过期，无法判断是否缺镜头",
            "unrelated_material": "未发现满足文稿商品/场景要求的画面，请补拍或人工核对",
            "duration_short": "候选连续时长不足，请补拍更长片段或调整文稿/配音",
            "action_not_observed": "没有明确进行中的动作证据；补充对应连续实拍或人工回看选段",
            "unsupported_vocabulary": "此句/品类不在有限可核对词表中，无法自动判断；请人工选段或补充清楚的商品描述",
        }
        rows.append(
            {
                "line": i + 1,
                "text": line,
                "duration": duration,
                "duration_basis": "measured" if measured else "estimated",
                "required_action": action,
                "required_actions": actions,
                "status": status,
                "code": code,
                "message": messages[code],
                "candidates": [
                    {
                        "asset_id": p["asset_id"],
                        "name": p["asset_name"],
                        "sha256": p["sha256"],
                        "analysis_id": p["analysis_id"],
                        "source_in": p["start"],
                        "source_end": p["end"],
                        "observation": p["observation"]["description"],
                    }
                    for p in choices[:3]
                ],
            }
        )
    return {
        "version": VERSION,
        "human_review_required": True,
        "lines": rows,
        "gap_count": sum(r["status"] == "gap" for r in rows),
        "unknown_count": sum(r["status"] == "unknown" for r in rows),
        "scope": "逐句关键帧候选检查；非完整选段分配、非SKU鉴定或事实认证",
    }


def project_preflight(p):
    product = p["product"]
    draft = next(
        (d for d in product["script_drafts"] if d["id"] == product["current_draft_id"]), None
    )
    if not draft:
        return {
            "version": VERSION,
            "human_review_required": True,
            "lines": [],
            "gap_count": 0,
            "unknown_count": 0,
            "message": "先确认事实并生成或输入文稿",
        }
    media = []
    for a in p["media"]:
        analysis = a.get("analysis") or {}
        media.append(
            {
                **a,
                "metadata": {
                    **a["metadata"],
                    "source_in": a["source_in"],
                    "content_analysis": analysis.get("result")
                    if analysis.get("status") == "ready"
                    else None,
                },
            }
        )
    lines = [s["text"] for s in draft["payload"]]
    job = p.get("job") or {}
    durations = None
    if not p.get("inputs_changed") and job.get("script") == "\n".join(lines):
        board = job.get("storyboard") or {}
        if board.get("shots"):
            durations = [s["duration"] for s in board["shots"]]
        elif (p.get("alignment") or {}).get("status") == "confirmed":
            import math

            alignment = p["alignment"]["result"]
            voice = next(
                (a for a in job["assets"] if a["metadata"].get("customer_role") == "voice"), None
            )
            if voice:
                ends = (
                    [0]
                    + [round(s["start"] * 30) / 30 for s in alignment["sentences"][1:]]
                    + [math.ceil(voice["metadata"]["duration"] * 30) / 30]
                )
                durations = [b - a for a, b in zip(ends, ends[1:], strict=False)]
    from .material_suitability import material_inputs

    enhanced_media, constraints = material_inputs(p)
    result = check_materials(
        lines,
        enhanced_media if constraints["material_checks"] else media,
        durations,
        constraints=constraints,
    )
    result.update(
        draft_id=draft["id"],
        script_confirmed=product["status"] == "script_confirmed",
        fingerprint=signature(
            {"draft": draft, "media": media, "durations": durations, "version": VERSION}
        ),
        production_blockers=p.get("preparation_blockers", []),
    )
    return result
