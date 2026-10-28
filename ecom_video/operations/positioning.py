"""Literal product evidence and descriptive material support, not generated facts."""

import re


def category_for(subject, facts):
    text = subject + " " + " ".join(f["text"] for f in facts)
    for category, pattern in [
        ("clothes", "外套|衣|软壳|口袋|袖口|下摆"),
        ("food", "鲜橙|水果|食品|果皮|切片"),
        ("beauty", "护肤|滴管|精华|面霜"),
        ("electronics", "耳机|充电|数码|键盘"),
    ]:
        if re.search(pattern, text):
            return category
    return "generic"


def position(brief, facts, materials, source_state):
    subject = brief.content_brief.subject or brief.content_brief.idea.split("。", 1)[0][:40]
    category = category_for(subject, facts)
    keywords = re.findall(
        r"口袋|袖口|下摆|抽绳|拉链|上身|切片|切面|果皮|开盖|倒水|参数|容量|配色",
        brief.content_brief.idea,
    )
    ranked = sorted(
        enumerate(facts),
        key=lambda row: (-sum(word in row[1]["text"] for word in keywords), row[0]),
    )
    core = ranked[0][1] if ranked else None
    gaps = []
    if not facts:
        gaps.append("尚无完整事实依据；当前只做主题与画面设定，请补充并人工核对资料")
    if source_state != "confirmed_in_parent":
        gaps.append("本次输入资料尚待人工核对，未作为已确认商品事实")
    if not materials:
        gaps.append("没有实拍；仅提供标记为非实拍的代码图示，商品外观与动作需补素材")
    elif any(m["metadata"].get("inspection_status") != "current" for m in materials):
        gaps.append("部分素材的同款、主体可见度与动作检查未知或已过期，须人工逐镜核对")
    identities = [m["metadata"].get("identity") for m in materials if m["metadata"].get("identity")]
    if len(identities) != len(materials) and materials:
        gaps.append("尚未取得全部素材的同款/配色确认，不凭文件名自动确认")
    return {
        "category": category,
        "subject": subject,
        "source_state": source_state,
        "core_selling_point": core,
        "reason": "按本次主题中的细节词匹配完整原文；不从目标人群推导性能"
        if core
        else "资料不足，保留待补项",
        "audience": brief.audience,
        "tone": brief.tone,
        "objective": brief.objective,
        "material_count": len(materials),
        "gaps": gaps,
    }
