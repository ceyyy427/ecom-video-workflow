"""Finite, local editorial recipes. Prompts describe decisions; they are never executed."""

import math
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .prompt_catalog import MEDIA_RECIPES, PromptCardId, card_record


class ActionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0, le=15)
    end: float = Field(gt=0, le=15)
    basis: Literal["manual", "analysis", "voice_hint"] = "manual"

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("动作保护结束须晚于开始")
        return self


class MotionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[2] = 2
    prompt_card: PromptCardId | None = None
    visual_finish: Literal["legacy", "polished-v1"] = "legacy"
    strength: Literal["subtle", "balanced", "bold"] = "balanced"
    cue_offset: float = Field(default=0, ge=-0.5, le=1)
    protect_action: bool = True
    windows: list[ActionWindow] = Field(default_factory=list, max_length=8)
    repeat_limit: int = Field(default=2, ge=1, le=4)
    intent: Literal["auto", "hook", "detail", "action", "context", "outro"] = "auto"


RecipeId = Literal[
    "product-detail-bracket",
    "product-fact-row",
    "product-hero-stage",
    "product-explain-relay",
    "product-brand-snap",
    "product-type-mask",
    "same-frame-panels",
    "media-punch-in",
    "detail-dual-window",
    "product-shape-reveal",
    "none",
    "crash-zoom-punch",
    "marker-underline-title",
    "blur-slide",
    "scanline-annotate-focus",
    "product-card-progressive-assemble",
]
COMMIT = "43bd349a136651865ecfa6ea1cf012f6e957d304"
VERSION = "shotcraft-adaptation-1"
RECIPES = {
    "product-detail-bracket": ("文稿细节括号", "人工焦点依次落角，持续实拍，不模拟检测。", None),
    "product-fact-row": ("完整原文信息行", "完整引用短句，原样静态数值，不补造图表。", None),
    "product-hero-stage": (
        "商品主角登场",
        "实拍窗口有界靠近并回位，外部舞台聚焦；不改变商品光色。",
        None,
    ),
    "product-explain-relay": ("讲解摘句接力", "实拍持续播放，已确认摘句按人声字锚点接力。", None),
    "product-brand-snap": ("品牌画框落位", "品牌色框长出包裹实拍，落定后回到全幅；不闪白。", None),
    "product-type-mask": (
        "字形商品开场",
        "真实画面透过已确认摘句后展开；独立字幕，动作避让。",
        None,
    ),
    "same-frame-panels": (
        "同帧分区解释",
        "同帧整体与侧边局部分区再合拢，不冒充多机位或前后对比。",
        None,
    ),
    "media-punch-in": (
        "商品局部急推",
        "商品整体到焦点的短促推近并回到整体；不变速、不震屏，动作避让。",
        None,
    ),
    "detail-dual-window": (
        "整体与细节同步双窗",
        "同源同帧的整体与细节双窗，不冒充前后效果比较。",
        None,
    ),
    "product-shape-reveal": (
        "商品形状展开",
        "保留同帧底层，用有界形状窗口展开完整商品，不生成角度或轮廓。",
        None,
    ),
    "none": ("静止留看", "收尾保留观看时间，不追加图形动作。", None),
    "crash-zoom-punch": (
        "关键词冲击",
        "已确认标题在六帧内急推落位并轻微回收；实拍不裁切、不震屏。",
        "camera",
    ),
    "marker-underline-title": (
        "手绘划线",
        "标题在人声词锚点落定后延迟六帧，十帧内完成一次手绘划线。",
        "typography",
    ),
    "blur-slide": ("词组浮现", "已确认标题按词组逐次上移清晰，短句不逐字弹跳。", "typography"),
    "scanline-annotate-focus": (
        "细节聚焦",
        "扫描引导到用户设置的焦点框；只标注文稿摘句，不暗示自动测量或检测。",
        "effects",
    ),
    "product-card-progressive-assemble": (
        "分阶段展开",
        "商品完整实拍先出现，标题与进度标记随后落位；不生成价格、折扣或拆解部件。",
        "ui-entrance",
    ),
}


def palette(style):
    if style in ("kinetic", "bauhaus"):
        ids, transition = (
            ["crash-zoom-punch", "product-card-progressive-assemble", "scanline-annotate-focus"],
            "push-stack",
        )
    elif style in ("evidence", "lab"):
        ids, transition = (
            [
                "scanline-annotate-focus",
                "product-card-progressive-assemble",
                "marker-underline-title",
            ],
            "line-carry",
        )
    elif style in ("social", "collage"):
        ids, transition = (
            ["blur-slide", "marker-underline-title", "product-card-progressive-assemble"],
            "push-stack",
        )
    else:
        ids, transition = (
            ["marker-underline-title", "blur-slide", "scanline-annotate-focus"],
            "line-carry",
        )
    return {
        "version": VERSION,
        "recipes": ids,
        "transition": transition,
        "description": " → ".join(RECIPES[r][0] for r in ids)
        + ("；底边推叠衔接" if transition == "push-stack" else "；一次线条接力衔接"),
        "choices": [
            {
                "id": k,
                "name": v[0],
                "prompt": v[1],
                "source_url": f"https://vincentwei1021.github.io/video-shotcraft/source/{k}.md"
                if v[2]
                else None,
            }
            for k, v in RECIPES.items()
        ],
    }


def choreography(lines, style, durations, *, repeat_limit=2):
    """Script intent selects presentation only. It never selects an unverified source range."""
    chosen = palette(style)
    result = []
    counts = Counter()
    for i, (line, duration) in enumerate(zip(lines, durations, strict=True)):
        intent = "context"
        if i == len(lines) - 1:
            intent = "outro"
            recipe, reason = "none", "收尾停留，留时间看清商品"
        elif i == 0:
            intent = "hook"
            recipe, reason = chosen["recipes"][0], "开场提取已确认文稿关键词"
        elif re.search(
            "折叠|打开|开盖|合上|旋开|提起|转动|靠拢|收起|倒入|倒水|放入|放进|滴入|取出|佩戴|戴上",
            line,
        ):
            intent = "action"
            recipe, reason = (
                "product-card-progressive-assemble",
                "操作语句分阶段展开，原素材动作保持连续",
            )
        elif re.search("细节|颜色|材质|接口|纹理|表面|盖|瓶|耳罩|做工|杯口|杯壁|杯底", line):
            intent = "detail"
            recipe, reason = (
                "scanline-annotate-focus",
                "文稿指向可见细节，使用焦点引导，须人工核对焦点",
            )
        else:
            recipe, reason = chosen["recipes"][min(i, 1)], "辅助语义阅读，避免连续重复主动作"
        if duration < 2.5 and recipe == "crash-zoom-punch":
            recipe, reason = "blur-slide", "镜头不足急推前后留看时长，改为简短标题浮现"
        if duration < 2 and recipe in (
            "scanline-annotate-focus",
            "product-card-progressive-assemble",
        ):
            recipe, reason = "marker-underline-title", "短镜采用单次轻量强调"
        if recipe != "none" and counts[recipe] >= repeat_limit:
            recipe = next((r for r in chosen["recipes"] if counts[r] < repeat_limit), "none")
            reason += "；同配方达到本次规划上限，换用轻量对照或留看"
        counts[recipe] += 1
        transition = "cut"
        if duration >= 2 and i and i < len(lines) - 1:
            if chosen["transition"] == "push-stack" and i <= 2:
                transition = "push-stack"
            elif chosen["transition"] == "line-carry" and i == 1:
                transition = "line-carry"
        plan = MotionPlan(
            strength="subtle"
            if style in ("cinema", "editorial", "quiet")
            else "bold"
            if style in ("social", "kinetic", "bauhaus")
            else "balanced",
            repeat_limit=repeat_limit,
            intent=intent,
        ).model_dump()
        result.append(
            {"shot_recipe": recipe, "transition": transition, "reason": reason, "motion_plan": plan}
        )
    return result


def resolve_motion(scene, words):
    """Resolve a visual cue; speech, footage, captions and saved input stay immutable."""
    raw = scene.get("motion_plan")
    if raw is None or scene.get("shot_recipe") is None:
        return None
    plan = MotionPlan.model_validate(raw).model_dump()
    prefix = scene["text"][: max(0, scene["text"].find(scene["headline"]))]
    index = sum(c.isalnum() for c in prefix)
    anchor = (
        words[index]["start"]
        if index < len(words)
        else scene.get("voice_start", scene.get("start", 0)) - scene.get("start", 0)
    )
    requested = min(scene["frames"] - 1, max(0, round((anchor + plan["cue_offset"]) * 30)))
    cue, recipe, outcome = requested, scene["shot_recipe"], "unchanged"
    prompt = None
    if recipe in MEDIA_RECIPES:
        default = {
            "product-detail-bracket": "detail-bracket-soft-v1",
            "product-fact-row": "fact-row-soft-v1",
            "product-hero-stage": "hero-soft-v1",
            "product-explain-relay": "relay-soft-v1",
            "product-brand-snap": "brand-soft-v1",
            "product-type-mask": "type-mask-clean-v1",
            "same-frame-panels": "comic-panels-soft-v1",
            "media-punch-in": "tech-punch-v1",
            "detail-dual-window": "precision-dual-v1",
            "product-shape-reveal": "quiet-portal-v1",
        }[recipe]
        prompt = card_record(plan["prompt_card"] or default)
        if prompt["recipe"] != recipe:
            recipe, outcome = "none", "prompt_recipe_mismatch"
        plan["prompt_card"] = prompt["id"]
    beats = []
    boundaries = r"[^。！？.!?]+" if recipe == "product-explain-relay" else r"[^，。！？；,;.!?]+"
    for match in list(re.finditer(boundaries, scene["text"]))[:2]:
        # Do not turn a qualified claim into a claim by truncating its tail.
        # Preserve old render contracts; the new relay uses whole short clauses.
        if recipe == "product-explain-relay" and len(match.group().strip()) > 24:
            continue
        position = sum(c.isalnum() for c in scene["text"][: match.start()])
        at = words[position]["start"] if position < len(words) else requested / 30
        beats.append(
            {
                "text": match.group().strip()
                if recipe == "product-explain-relay"
                else match.group().strip()[:12],
                "frame": min(scene["frames"] - 1, max(0, round(at * 30))),
            }
        )

    if recipe == "product-explain-relay" and not beats:
        recipe, outcome = "none", "no_safe_excerpt"

    def events(start):
        if prompt:
            travel = prompt["presentation"]["travel_frames"]
            end = (
                start + travel + 44
                if recipe == "product-detail-bracket"
                else scene["frames"]
                if recipe == "product-fact-row"
                else max(
                    start + 2 * travel + 30, max((b["frame"] + 24 for b in beats), default=start)
                )
                if recipe == "product-explain-relay"
                else start + 2 * travel + 30
                if recipe in ("product-hero-stage", "product-brand-snap")
                else start + travel
                if recipe == "product-type-mask"
                else start + 2 * travel + 24
                if recipe == "same-frame-panels"
                else max(start + travel + 24, scene["frames"])
                if recipe == "detail-dual-window"
                else start + travel + 54
                if recipe == "media-punch-in"
                else start + travel
            )
            return [(start, end)]
        end = start + (
            50
            if recipe == "scanline-annotate-focus"
            else 28
            if recipe == "marker-underline-title"
            else 20 + 4 * max(0, len(scene["headline"]) - 1)
            if recipe == "blur-slide"
            else 12
        )
        spans = [(start, end)]
        if recipe == "product-card-progressive-assemble":
            spans += [
                (max(start + i * 8, b["frame"]), max(start + i * 8, b["frame"]) + 12)
                for i, b in enumerate(beats)
            ]
        return spans

    if plan["protect_action"] and recipe != "none":
        windows = sorted(
            (max(0, math.floor(w["start"] * 30)), min(scene["frames"], math.ceil(w["end"] * 30)))
            for w in plan["windows"]
        )
        # Later word-triggered cards belong to the same guarded event group.
        for _ in range(len(windows) + 1):
            collision = next(
                (
                    (a, b)
                    for a, b in windows
                    if any(start < b and end > a for start, end in events(cue))
                ),
                None,
            )
            if collision is None:
                break
            cue = max(cue, collision[1] + 4)
            outcome = "deferred"
        tail = 0 if recipe in ("detail-dual-window", "product-fact-row") else 12
        if max(end for _, end in events(cue)) + tail > scene["frames"]:
            recipe, cue, outcome = (
                "none",
                requested,
                "static_during_action" if windows else "insufficient_tail",
            )
    return {
        **plan,
        "recipe": recipe,
        "requested_recipe": scene["shot_recipe"],
        "cue_frame": cue,
        "requested_cue_frame": requested,
        "amount": {"subtle": 0.55, "balanced": 1, "bold": 1.3}[plan["strength"]],
        "guard_outcome": outcome,
        "version": 2,
        "beats": beats,
        **({"presentation": prompt["presentation"]} if prompt else {}),
    }


def voice_guard(line, words, duration):
    """Conservative speech-word guard. Never presented as observed action evidence."""
    result = []
    for match in re.finditer(
        "倒入|倒水|倒一杯|拿起|提起|放下|放回|旋开|打开|合上|折叠|转动|佩戴|戴上", line
    ):
        prefix = sum(c.isalnum() for c in line[: match.start()])
        count = sum(c.isalnum() for c in match.group())
        if prefix + count > len(words):
            continue
        start, end = (
            max(0, words[prefix]["start"] - 0.15),
            min(duration, words[prefix + count - 1]["end"] + 0.3),
        )
        if end > start:
            result.append({"start": round(start, 4), "end": round(end, 4), "basis": "voice_hint"})
    return result[:8]


def effective_transitions(scenes):
    """One decision per boundary; both scene halves consume the same result."""
    result = [s["transition"] for s in scenes]
    entrances = {
        "cut": 0,
        "wipe": 12,
        "iris": 24,
        "push-stack": 14,
        "line-carry": 15,
        "media-pass": 14,
    }
    exits = {"cut": 0, "wipe": 12, "iris": 12, "push-stack": 14, "line-carry": 15, "media-pass": 14}
    for i in range(len(scenes)):
        kind = result[i]
        checks = [(scenes[i], 0, entrances[kind] / 30)]
        if i:
            checks.append(
                (
                    scenes[i - 1],
                    max(0, scenes[i - 1]["frames"] - exits[kind]) / 30,
                    scenes[i - 1]["frames"] / 30,
                )
            )
        for scene, start, end in checks:
            plan = scene.get("motion_plan")
            if (
                end > start
                and plan
                and plan.get("protect_action", True)
                and any(w["start"] < end and w["end"] > start for w in plan.get("windows", []))
            ):
                result[i] = "cut"
    return result


def recipe_record(recipe, text, headline, style, prompt_card=None):
    if recipe not in RECIPES:
        raise ValueError("不支持的镜头配方")
    if headline and headline not in text:
        raise ValueError("动效字卡必须摘自已确认文稿")
    name, prompt, group = RECIPES[recipe]
    source = None
    if group:
        # The older, separately pinned blur/scan references remain under vendor/p6.
        old = recipe in ("blur-slide", "scanline-annotate-focus")
        source = {
            "card": recipe,
            "license": "Apache-2.0",
            "commit": COMMIT if not old else "5ddbf521038b0a7accfb6dc1e0a9eb29c67277ab",
            "url": f"https://vincentwei1021.github.io/video-shotcraft/source/{recipe}.md",
        }
    return {
        "version": VERSION,
        "id": recipe,
        "name": name,
        "approved_text": text,
        "headline": headline,
        "prompt": prompt,
        "source": source,
        "reason": f"{style} 的{name}；只改变画面呈现，不增加商品事实",
        "adaptation": "本项目重写的竖屏人声锚定配方；不是上游完整演示代码或生成模型调用",
        **({"prompt_match": card_record(prompt_card)} if prompt_card else {}),
    }
