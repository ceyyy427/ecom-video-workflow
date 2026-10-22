"""Versioned local direction shared by recommendations, range allocation and shot planning.

v1 is additive: saved boards opt in explicitly; observed relevance always outranks taste.
"""

import re

from .shotcraft import choreography
from .voice_profiles import PROFILES

VERSION = "narrative-v1"
ACTION = re.compile(
    "折叠|打开|开盖|合上|旋开|提起|拿起|放下|放回|转动|收起|倒入|倒水|倒一杯|滴入|取出|佩戴|戴上|走动|背上包|泼水|水花|水滴"
)
DETAIL = re.compile(
    "细节|杯口|杯壁|杯底|杯盖|耳罩|头梁|接口|纹理|瓶口|瓶身|表面|做工|颜色|材质|结构|连帽|领口|袖口|衣面"
)


def direction_for(style):
    archetype = (
        "social"
        if style in ("social", "collage", "kinetic")
        else "lab"
        if style in ("lab", "evidence", "bauhaus")
        else "cinema"
    )
    footage, rhythm, structure = {
        "cinema": (
            "完整商品与局部细节交替，实拍持续留看，不用文字盖住关键动作",
            "轻声与留白；标题轻落，动作段少动效，声音决定实际镜长",
            "商品先出现 → 一处细节/动作 → 完整收尾",
        ),
        "social": (
            "清楚商品与生活场景接力；动作保持连续，相关性同分才优先场景",
            "首句提问或提醒；大字短促，换章推叠，停顿留给动作",
            "吸引注意 → 使用情境/动作 → 回到商品",
        ),
        "lab": (
            "整体 → 实拍细节 → 实际动作；焦点须核对，不把场景当作功能证据",
            "清楚分章；逐点讲解，动作词优先，线条提示换章",
            "提出观察点 → 细节和动作 → 看清整体",
        ),
    }[archetype]
    from .motion_treatment import profile

    return {
        "treatment": profile(style),
        "finish": "标题按实际字形测量；有可靠字锚点才轻强调关键词，字幕置于转场上方；可逐镜关闭",
        "version": VERSION,
        "archetype": archetype,
        "footage": footage,
        "rhythm": rhythm,
        "structure": structure,
        "voice": dict(PROFILES[style]),
    }


def framing_for(style, line, index, count):
    if DETAIL.search(line):
        return "detail"
    if index in (0, count - 1):
        return "whole"
    return "context" if direction_for(style)["archetype"] == "social" else "whole"


def footage_priority(candidate, style, line, index, count):
    """Only a tie-break after model relevance, reservation and reuse safety."""
    observed = candidate.get("observation", {})
    return int(observed.get("framing") == framing_for(style, line, index, count))


def folding_action(line):
    return bool(
        re.search(
            r"(?:向内|向里)(?:转动|折叠)|(?:把|将|双手).*(?:向内转|折叠|靠拢|收拢|收起)|耳罩.*向内(?:折|转)",
            line,
        )
    )


def supports_action(candidate, line):
    if not folding_action(line):
        return True
    if candidate["kind"] != "video":
        return False
    from .clip_grounding import NEGATIVE, UNCERTAIN

    # Only explicit performed-action tags, not capability or completed-result descriptions.
    performed = re.compile(
        r"(?:双手|用手|手指|手部|正在|缓慢|慢慢|逐渐)(?:正在|缓慢|慢慢|逐渐)?"
        r"(?:向内|向里)?(?:转动|折叠|收拢|收起)|"
        r"(?:向内|向里)(?:转动|折叠)(?:两侧)?耳罩|"
        r"(?:两侧)?耳罩(?:正在|缓慢|慢慢|逐渐|向内|向里)(?:转动|折叠|靠拢)|"
        r"^(?:折叠|收拢|收起)(?:两侧)?(?:耳罩|耳机)$"
    )
    return any(
        performed.search(action)
        and re.search("耳罩|耳机", action)
        and not re.search("可|能|支持|已|后|状态|折叠式|折叠结构|折叠功能", action)
        and not NEGATIVE.search(action)
        and not UNCERTAIN.search(action)
        for action in candidate.get("observation", {}).get("actions", [])
    )


def closing_reminder(line, index, count):
    # Full finite sentence templates only; unknown clauses stay with model/manual review.
    text = re.sub(r"[，,。.!！\s]", "", line)
    return index == count - 1 and bool(
        re.fullmatch(
            r"(?:(?:外观|包装|细节)看清(?:之后|后)|挑选前看清包装)?"
            r"(?:再|请|记得|建议|还需)核对(?:产品)?(?:说明|参数)"
            r"(?:和(?:自己|个人)(?:的)?(?:使用)?(?:需要|需求))?(?:再(?:挑选|选择))?",
            text,
        )
    )


def outro_candidate(candidate, lines, index, *, allow_image=False):
    if (
        not closing_reminder(lines[index], index, len(lines))
        or candidate["kind"] not in (("image", "video") if allow_image else ("video",))
        or candidate.get("observation", {}).get("framing") != "whole"
    ):
        return False
    from .clip_grounding import VOCABULARY, assess, requirements

    products = {"cup", "headphone", "bottle", "computer", "book", "bag", "plant"} & set(
        requirements("\n".join(lines))["required"]
    )
    return len(products) == 1 and assess(VOCABULARY[next(iter(products))][0], candidate)["eligible"]


def choreography_for(lines, style, durations, *, repeat_limit=2):
    rows = choreography(lines, style, durations, repeat_limit=repeat_limit)
    archetype = direction_for(style)["archetype"]
    chapter_count = 0
    for index, (line, row) in enumerate(zip(lines, rows, strict=True)):
        row["motion_plan"]["visual_finish"] = "polished-v1"
        row["transition"] = "cut"
        if index == 0 and archetype in ("social", "lab") and durations[index] >= 2.5:
            row["shot_recipe"] = "crash-zoom-punch"
        elif 0 < index < len(lines) - 1 and ACTION.search(line):
            row.update(shot_recipe="none", reason="动作语句优先看连续实拍，保留原声字幕")
            row["motion_plan"]["intent"] = "action"
        elif 0 < index < len(lines) - 1 and DETAIL.search(line) and archetype == "lab":
            row["shot_recipe"] = "scanline-annotate-focus"
            row["motion_plan"]["intent"] = "detail"
        if (
            index
            and not ACTION.search(line)
            and re.search("再看|接着|最后|回到|然后", line)
            and chapter_count < (2 if archetype == "social" else 1)
        ):
            row["transition"] = "push-stack" if archetype == "social" else "line-carry"
            chapter_count += 1
        row["reason"] += (
            f"；{ {'cinema': '克制质感', 'social': '生活种草', 'lab': '细节解说'}[archetype] }叙事建议，最终镜长跟随已听核配音"
        )
    # Re-check the cap after semantic overrides. Manual per-shot overrides remain unrestricted.
    used = {}
    for row in rows:
        recipe = row["shot_recipe"]
        if recipe != "none" and used.get(recipe, 0) >= repeat_limit:
            row["shot_recipe"] = "none"
            row["reason"] += "；重复达到上限，静态留看"
        used[row["shot_recipe"]] = used.get(row["shot_recipe"], 0) + 1
    from .motion_treatment import shape_rhythm

    return shape_rhythm(rows, style)
