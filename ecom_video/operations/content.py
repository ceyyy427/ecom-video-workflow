"""Fact-locked spoken candidates and platform copy drafts, no model or platform call."""

import re

from ..spoken_copy import PREFIXES, PROTECTED, validate_copy

LABELS = {
    "product_showcase": "商品展示",
    "scenario_share": "场景分享",
    "detail_explain": "细节讲解",
}


def script_for(subject, category, narrative, variant, facts, audience, platform):
    groups = {
        "clothes": [
            "外套怎么挑，先看上身和细节。",
            "别只看颜色，把细节拉近看看。",
            "上班一件，周末又要换一件？",
            "周末想出门，先看看外套的样子。",
            "选外套，口袋和下摆得看清。",
            "照片没讲清的细节，放近一点看。",
        ],
        "food": [
            "切开以后，细节才看得清。",
            "先别划走，看看这个切面。",
            "周末准备吃点什么？",
            "准备一份轻食，你会先选什么？",
            "挑水果，先把外观和切面看清。",
            "这段切片过程，值得凑近看看。",
        ],
        "beauty": [
            "先看清这件商品，再看细节。",
            "瓶身之外，还有哪些细节？",
            "日常怎么选，先从细节看起。",
            "挑选之前，你会先看哪里？",
            "看商品，这几处细节别跳过。",
            "把细节放大，依据也放在旁边。",
        ],
        "electronics": [
            "先看整体，再把细节拉近。",
            "这个设计，你会先注意哪里？",
            "日常挑选，先看你在意的细节。",
            "你更在意外观，还是操作细节？",
            "别只看标题，把依据展开。",
            "这句介绍，配上画面怎么看？",
        ],
        "generic": [
            f"{subject}，先看整体，再看细节。",
            "先别急着下结论，看看细节。",
            "你会怎么选？先看这一点。",
            "想了解它，从眼前的细节开始。",
            "这句介绍，依据在哪里？",
            "把资料放在旁边，一起看清楚。",
        ],
    }
    group = ["product_showcase", "scenario_share", "detail_explain"].index(narrative)
    index = group * 2 + variant
    hook = groups[category][index]
    if narrative == "scenario_share" and "通勤" in audience and category == "clothes":
        hook = ["早上出门，外套你会先挑哪件？", "通勤和周末，你会怎么搭这一件？"][variant]
    if platform == "xiaohongshu":
        hook = (
            ["想选得明白，先看看这些细节。", "挑选之前，我想先把细节讲清楚。"][variant]
            if category == "generic"
            else hook
        )
    evidence = subject + " ".join(f["text"] for f in facts)
    if category == "clothes":
        if not all(word in evidence for word in ("口袋", "下摆")) and index == 4:
            hook = "挑衣服，这些细节得看清。"
        if not re.search("外套|软壳|夹克", evidence):
            hook = hook.replace("外套", "衣服")
    if category == "food" and not re.search("切开|切面|切片", evidence):
        hook = [
            "先看外观，再凑近看看。",
            "先别划走，看看这些细节。",
            "日常选吃的，你会先看什么？",
            "挑选之前，你在意哪些细节？",
            "挑食品，把资料和实物对照看。",
            "这处细节，值得凑近看看。",
        ][index]
    if category == "beauty" and "瓶" not in evidence:
        hook = hook.replace("瓶身之外", "整体之外")
    body = list(facts)
    if variant or narrative == "detail_explain":
        body = body[1:] + body[:1] if len(body) > 1 else body
    selected = (body * 2)[:2] if body else []
    rows = [{"text": hook, "claim_ids": ["topic"], "purpose": "hook"}]
    for i in range(2):
        if selected:
            f = selected[i]
            text = f["text"]
            prefix = PREFIXES[(i + variant + group) % len(PREFIXES)]
            if not PROTECTED.search(text) and len(prefix + text) <= 100:
                text = prefix + text
            validate_copy([{"text": text, "fact_ids": [f["id"]]}], facts)
            rows.append(
                {
                    "text": text,
                    "claim_ids": [f["id"]],
                    "purpose": "evidence" if narrative == "detail_explain" else "detail",
                }
            )
        else:
            rows.append(
                {
                    "text": ["先看整体，再看局部。", "这里需要商品资料和对应画面。"][i],
                    "claim_ids": ["topic"],
                    "purpose": "detail",
                }
            )
    closing = [
        "你会先记住哪一处？",
        "想看清的细节，再留一眼。",
        "换成你的日常，你会怎么选？",
        "你想把它放进哪种日常？",
        "资料和画面，对得上才讲得清。",
        "还有哪处细节，你想再看看？",
    ][index]
    if platform == "xiaohongshu":
        closing = [
            "这些细节，你会先看哪里？",
            "还有哪处细节，你想记下来？",
            "放进你的日常，你会怎么搭？",
            "这份挑选笔记，你还想补充什么？",
            "把依据留在这里，挑选时再对照。",
            "哪里还没看清，可以再拉近看。",
        ][index]
    if category != "clothes":
        closing = closing.replace("怎么搭", "怎么选")
    rows.append({"text": closing, "claim_ids": ["topic"], "purpose": "closing"})
    return rows


def make_publication_copy(plan, platform):
    if platform not in ("douyin", "xiaohongshu"):
        raise ValueError("请选择抖音或小红书")
    subject = plan["subject"]
    facts = [c["text"] for c in plan["claims"] if c["id"] != "topic"]
    core = plan["positioning"]["core_selling_point"]
    text = core["text"] if core else "商品资料待补充"
    rule = plan["domestic_policy"]["platforms"][platform]
    if platform == "douyin":
        titles = [f"{subject}，细节拉近看", "这一处，你会先看吗？"]
        body = "先给你看清楚：\n" + "\n".join(facts) + "\n你最想多了解哪一点？"
    else:
        titles = [f"挑{subject}，我会先看这些", f"关于{subject}的细节笔记"]
        body = (
            "挑选时想弄明白的细节，整理在这里。\n\n"
            + "\n\n".join(facts)
            + "\n\n以上依据仍需核对，先看画面，再做选择。"
        )
    category = plan["positioning"]["category"]
    tags = {
        "clothes": ["外套细节", "日常穿搭"],
        "food": ["食物观察", "周末轻食"],
        "electronics": ["商品细节", "数码选择"],
        "beauty": ["商品观察", "日常选择"],
    }.get(category, ["商品细节", "选择参考"])
    return {
        "status": "draft",
        "platform": platform,
        "titles": titles,
        "body": body,
        "tags": tags,
        "cover_brief": {
            "text": subject,
            "supporting_text": text,
            "visual": "选清楚可见的商品帧，保留原色；短标题不代替完整条件",
            "status": "suggestion_only",
        },
        "source_refs": [
            {"id": c["id"], "text": c["text"], "source": c["source"]} for c in plan["claims"]
        ],
        "rule_refs": [
            {
                "url": rule["source_url"],
                "checked_at": rule["checked_at"],
                "scope": rule["scope"],
                "kind": "reference_not_approval",
            }
        ],
        "strategy": rule["strategy"],
        "note": "标题、字数和结构是创作建议，不代表平台审核或发布规范已全部通过",
    }
