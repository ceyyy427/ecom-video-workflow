"""Delivery format gates. Evidence presence does not establish truth: review remains required."""


def validate_production(board, assets):
    creative = board.get("creative")
    if not creative:
        return
    mode = creative["brief"].get("format", "auto")
    voice = board["narration"]["mode"]
    if mode == "showcase" and voice != "silent":
        raise ValueError("纯商品展示不含口播，请关闭配音或选择商品展示＋配音")
    if mode in ("recommendation", "review", "narrated") and voice == "silent":
        raise ValueError("此片种需要配音，请上传成品配音并听核，或在分镜页选择本机配音")
    if mode == "review":
        owned = {a["id"]: a for a in assets}
        if not creative.get("review_context", "").strip():
            raise ValueError("测评需要测试条件、方法与结论来源说明")
        evidence = [s for s in board["shots"] if s["role"] == "evidence"]
        if not evidence or any(
            not s["evidence_note"].strip() or owned[s["asset_id"]]["kind"] != "video"
            for s in evidence
        ):
            raise ValueError(
                "测评需要真实测试视频证据镜头，并逐镜填写测试来源；图片外观解说不能作为测评"
            )
