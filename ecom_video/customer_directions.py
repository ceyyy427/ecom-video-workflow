"""Early creative choice is independent of production readiness; execution stays gated."""

from .creative import recommend_saved, signature


def direction_input(p):
    draft = next(
        (d for d in p["product"]["script_drafts"] if d["id"] == p["product"]["current_draft_id"]),
        None,
    )
    if not draft or p["product"]["status"] != "script_confirmed":
        raise ValueError("请先核对并确认当前文稿")
    if not any(a["draft_id"] == draft["id"] for a in p["product"]["script_approvals"]):
        raise ValueError("当前文稿缺少确认记录")
    return {
        "id": "customer-" + p["id"],
        "title": p["product"]["title"],
        "script": "\n".join(s["text"] for s in draft["payload"]),
        "assets": p["media"],
    }


def preparation_blockers(p):
    reasons = []
    settings = p["settings"]
    visual = [a for a in p["media"] if a["kind"] != "audio"]
    if p["product"]["status"] != "script_confirmed":
        reasons.append("先核对并确认当前文稿")
    if not visual:
        reasons.append("上传至少一份商品图片或实拍视频")
    if settings["brief"]["format"] != "showcase" and not any(
        a["role"] == "voice" for a in p["media"]
    ):
        reasons.append("上传成品配音，或使用火山语音合成后继续制作")
    if settings.get("auto_select"):
        if (
            settings.get("strict_product")
            or settings.get("action_timing")
            or settings.get("material_checks")
        ) and not any(
            a["id"] == settings.get("product_reference_id") and a["kind"] == "image" for a in visual
        ):
            reasons.append("在第一步选择并保存商品参照图")
        pending = [
            a
            for a in visual
            if not a.get("analysis")
            or a.get("analysis_stale")
            or a["analysis"]["status"] != "ready"
        ]
        if pending:
            reasons.append(
                "完成素材内容识别："
                + "、".join(a["name"] for a in pending[:3])
                + ("等" if len(pending) > 3 else "")
            )
        if settings.get("action_timing") and settings["brief"]["format"] == "showcase":
            reasons.append("纯商品展示请关闭配音动作词对齐，或切换带配音片种")
    return reasons


def editorial_basis(p):
    from .delivery_plan import identity_state

    return signature({"draft": p["product"]["current_draft_id"], "title": p["product"]["title"],
                      "brief": p["settings"]["brief"],
                      "visuals": sorted((a["sha256"], a["kind"]) for a in p["media"] if a["kind"] != "audio"),
                      **({"delivery": p["settings"].get("delivery_version"),
                          "identity_lock": p["settings"].get("identity_lock"),
                          "identity": identity_state(p["media"]),
                          "review": p["product"]["current_review_id"]}
                         if p["settings"].get("delivery_version") else {})})


def directions(p):
    try:
        source = direction_input(p)
    except ValueError:
        return None, None
    # Audio and analysis completion do not invalidate an editorial style choice.
    basis = editorial_basis(p)
    ready = bool(p["job"] and not p["inputs_changed"])
    job = p["job"] if ready else source
    rec = recommend_saved(job, p["settings"]["brief"])
    from .material_suitability import material_inputs
    from .production_proposals import production_readiness

    assets, constraints = material_inputs(p)
    for option in rec["options"]:
        plan = production_readiness(
            source["script"].splitlines(), assets, constraints, option["id"], p["settings"]["brief"]
        )
        option["production_readiness"] = plan
        if p["settings"].get("material_checks"):
            option["material_fit"] = plan["fit"]
    return {**rec, "scope": "job" if ready else "project"}, basis
