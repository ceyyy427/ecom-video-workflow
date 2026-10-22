"""Bounded spoken editing: neutral connective + complete confirmed source text.

Humanizer-zh's information-preservation method, not an LLM equivalence claim.
"""

import re

HOOKS = {
    "generic": ("先看一眼，再看细节。", "选东西，你会先看哪里？", "别光看整体，细节放近看。"),
    "clothes": (
        "这件外套，先看它的样子。",
        "通勤挑外套，你会先看哪里？",
        "选外套，细节得放近点看。",
    ),
    "food": ("先看外观，再凑近看看。", "挑吃的，你会先看哪里？", "先别急着选，细节放近看。"),
}
CLOSINGS = ("看清楚，再挑适合自己的。", "你更在意哪一处？", "这些细节，留给你自己判断。")
NEUTRAL = {s for group in HOOKS.values() for s in group} | set(CLOSINGS)
PREFIXES = ("你看，", "还有，", "先看，", "再看，")
PROTECTED = re.compile(
    r"\d|[一二三四五六七八九十]+(?:元|克|毫升|秒)|不|非|仅|限|须|条件|优惠|包邮|折扣|认证|测试|等级|超过|至少|可能|据称"
)
KINDS = ("overview", "scene", "details")


def bounded(text, original):
    return not PROTECTED.search(original) and text in {p + original for p in PREFIXES}


def validate_copy(rows, facts):
    by_id = {f["id"]: f["text"] for f in facts}
    for row in rows:
        ids, text = row["fact_ids"], row["text"]
        if not ids:
            if text not in NEUTRAL:
                raise ValueError("口语连接须为受控中性句")
            continue
        if len(ids) != 1 or ids[0] not in by_id:
            raise ValueError("口语稿须绑定单条完整事实原文")
        original = by_id[ids[0]]
        allowed = (
            {original}
            if PROTECTED.search(original)
            else {original, *(p + original for p in PREFIXES)}
        )
        if text not in allowed:
            raise ValueError("口语稿改变了完整原文或超出受控连接词，请人工编辑并重新核对")
    return rows


def speak(facts, brief, kind):
    index = KINDS.index(kind)
    category = brief.get("category", "")
    group = (
        "clothes"
        if re.search("外套|软壳", category)
        and any(re.search("外套|软壳", f["text"]) for f in facts)
        and "通勤" in brief.get("audience", "")
        else "food"
        if re.search("食品|水果|鲜橙", category)
        else "generic"
    )
    rows = [{"text": HOOKS[group][index], "fact_ids": [], "intent": "hook"}]
    for i, f in enumerate(facts):
        prefix = (
            ""
            if PROTECTED.search(f["text"])
            else PREFIXES[(index + i) % len(PREFIXES)]
            if i or kind == "details"
            else ""
        )
        if len(prefix + f["text"]) > 100:
            prefix = ""
        rows.append({"text": prefix + f["text"], "fact_ids": [f["id"]]})
    rows.append({"text": CLOSINGS[index], "fact_ids": [], "intent": "closing"})
    return validate_copy(rows, facts)
