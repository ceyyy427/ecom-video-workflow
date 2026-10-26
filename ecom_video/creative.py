"""Product-aware, explainable creative selection. No model-authored product claims."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Brief(Strict):
    format: Literal["auto", "showcase", "recommendation", "review", "narrated"] = "auto"
    category: str = Field(default="", max_length=80)
    audience: str = Field(default="", max_length=120)
    tone: str = Field(default="", max_length=120)


class Brand(Strict):
    name: str = Field(default="", max_length=24)
    ink: str = Field(default="#282721", pattern=r"^#[0-9a-fA-F]{6}$")
    paper: str = Field(default="#f3efe6", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#876f50", pattern=r"^#[0-9a-fA-F]{6}$")
    subtitle_size: int = Field(default=64, ge=40, le=64)


StyleId = Literal[
    "editorial", "evidence", "collage", "bauhaus", "quiet", "kinetic", "cinema", "social", "lab"
]


class Creative(Strict):
    production: Literal["narrative-v1"] | None = None
    brief: Brief = Field(default_factory=Brief)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_id: StyleId
    brand: Brand = Field(default_factory=Brand)
    alignment_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    sfx: bool = False
    review_context: str = Field(default="", max_length=1000)


CATALOG = [
    {
        "id": "editorial",
        "name": "质感杂志",
        "family": "premium",
        "keywords": "家居 美妆 香水 珠宝 杯 高级 精致",
        "description": "大幅商品、克制留白、缓推特写；字卡短促入场后留出观看时间。",
        "recipe": "project/slow-camera + title-reveal",
        "colors": ["#f3efe6", "#282721", "#876f50"],
    },
    {
        "id": "evidence",
        "name": "细节解说",
        "family": "demo",
        "keywords": "数码 功能 细节 工具 科技 讲解",
        "description": "真实素材做主角；按口播逐条展示细节，字幕整句出现。",
        "recipe": "project/slow-camera; shotcraft/aesthetic-rules",
        "colors": ["#eff2ef", "#193a47", "#337485"],
    },
    {
        "id": "collage",
        "name": "生活剪贴",
        "family": "lifestyle",
        "keywords": "食品 服装 日常 生活 年轻 活泼 场景",
        "description": "纸张白边与轻微倾角，真实场景素材接力，避免无意义漂浮。",
        "recipe": "mg-styles-15/collage-inspired; project/paper-entry",
        "colors": ["#f2eade", "#343e32", "#85644f"],
    },
    {
        "id": "bauhaus",
        "name": "几何陈列",
        "family": "demo",
        "keywords": "运动 设计 潮流 新品 文具",
        "description": "块面、圆与线组织版面，商品始终占主位；几何元素只承担引导。",
        "recipe": "mg-styles-15/geometric-bauhaus",
        "colors": ["#f3eee0", "#262b2e", "#bb4a31"],
    },
    {
        "id": "quiet",
        "name": "安静日常",
        "family": "lifestyle",
        "keywords": "安静 自然 家居 茶 咖啡 温暖 桌 办公",
        "description": "全幅生活画面与缓慢移镜，短标题、稳定素排字幕。",
        "recipe": "project/slow-camera",
        "colors": ["#e9eee8", "#26382d", "#627658"],
    },
    {
        "id": "kinetic",
        "name": "节奏字卡",
        "family": "premium",
        "keywords": "年轻 活动 潮流 简洁 运动",
        "description": "短关键词收拢与商品画面交替；保留人声，不用满屏花字。",
        "recipe": "project/title-reveal; shotcraft/aesthetic-rules",
        "colors": ["#f0eee8", "#25252a", "#704b64"],
    },
]


DIRECTIONS = [
    {
        "id": "cinema",
        "name": "形与留白",
        "family": "premium",
        "keywords": "高级 外观 设计 质感",
        "description": "字形露出、局部特写与完整陈列；安静的商品主角。",
        "recipe": "shotcraft/text-as-mask + project/cinema",
        "colors": ["#eee9de", "#252522", "#9c7953"],
    },
    {
        "id": "social",
        "name": "桌边的一刻",
        "family": "lifestyle",
        "keywords": "日常 生活 场景 温暖",
        "description": "场景开场、纸张错位归位、语义字卡，像一段有节奏的生活提案。",
        "recipe": "shotcraft/blur-slide + project/story-collage",
        "colors": ["#f0e6d6", "#303c30", "#a65d3b"],
    },
    {
        "id": "lab",
        "name": "先看细节",
        "family": "demo",
        "keywords": "功能 测评 细节 讲解",
        "description": "放大观察、扫描取景与证据标注，一镜回答一个问题。",
        "recipe": "shotcraft/scanline-annotate-focus + project/detail-window",
        "colors": ["#eef2ed", "#19382e", "#577a5b"],
    },
]
CATALOG += DIRECTIONS
FORMATS = {
    "showcase": "纯商品展示",
    "recommendation": "场景种草",
    "review": "测评视频",
    "narrated": "商品展示＋配音",
}


def signature(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def idea_selection(job):
    provenance = job.get("provenance") or {}
    if isinstance(provenance, str):
        provenance = json.loads(provenance)
    return provenance.get("idea_plan")


def fingerprint(job, brief, *, policy=1):
    return signature(
        {
            "version": policy,
            **(
                {"idea_plan": {k: idea_selection(job)[k] for k in ("basis", "option_id")}}
                if idea_selection(job)
                else {}
            ),
            "title": job["title"],
            "script": job["script"],
            "brief": {k: v for k, v in brief.items() if k != "format" or v != "auto"},
            "assets": sorted((a["sha256"], a["kind"]) for a in job["assets"]),
        }
    )


CONTEXT_WORDS = {
    "editorial": "精致 杂志 轻奢 质感 美妆 珠宝 香水 高级",
    "evidence": "理性 参数 说明 数码 接口 工具 清楚 功能 对比",
    "collage": "活泼 手作 穿搭 学生 旅行 纸张 朋友",
    "bauhaus": "几何 设计 撞色 文具 秩序 新品 建筑",
    "quiet": "安静 自然 温暖 办公 咖啡 茶 治愈 从容",
    "kinetic": "节奏 活泼 年轻 潮流 学生 运动 活动 快",
    "cinema": "电影 克制 留白 沉静 光影 外观",
    "social": "亲切 分享 日常 场景 生活 种草",
    "lab": "测评 观察 测试 细节 严谨 实验",
}
CONTEXT_WORDS_V2 = dict(CONTEXT_WORDS)
CONTEXT_WORDS = {**CONTEXT_WORDS, "quiet": CONTEXT_WORDS["quiet"] + " 温柔 柔和 慢叙 呼吸"}


def contextual(job, brief, policy=3):
    """Rank real layouts; user intent is editorial input, never evidence of a claim."""
    from .production_direction import direction_for
    from .shotcraft import palette
    from .voice_profiles import PROFILES

    fields = {
        "商品文稿": job["title"] + " " + job["script"],
        "类别": brief["category"],
        "人群": brief["audience"],
        "气质": brief["tone"],
    }
    weights = {"商品文稿": 5, "类别": 7, "人群": 9, "气质": 14}
    favored = {"showcase": "premium", "recommendation": "lifestyle", "review": "demo"}.get(
        brief["format"]
    )
    ranked = []
    visual = sum(a["kind"] != "audio" for a in job["assets"])
    video = any(a["kind"] == "video" for a in job["assets"])
    for index, style in enumerate(CATALOG):
        vocabulary = CONTEXT_WORDS_V2 if policy == 2 else CONTEXT_WORDS
        words = sorted(set((style["keywords"] + " " + vocabulary[style["id"]]).split()))
        matched = {label: [w for w in words if w in value] for label, value in fields.items()}
        score = sum(weights[k] * len(v) for k, v in matched.items())
        score += 12 if style["family"] == favored else 0
        reason = "；".join(k + "：" + "、".join(v) for k, v in matched.items() if v)
        missing = [] if visual else ["上传真实商品图片或视频"]
        if not video:
            missing.append("当前无实拍视频，图片运镜无法替代商品动作")
        if brief["format"] == "review":
            missing.append("测评须提供真实测试视频、条件和结论依据；外观观察不等于测评")
        ranked.append(
            (
                score,
                -index,
                {
                    **style,
                    "name": {"cinema": "克制质感", "social": "生活种草", "lab": "细节解说"}.get(
                        style["id"], style["name"]
                    ),
                    "matched_inputs": matched,
                    "reason": (reason or "没有命中专用词，作为另一种视觉对照")
                    + f"；{visual}份画面素材"
                    + ("，实拍优先" if video else "，需核对图片表现"),
                    "missing": missing,
                    "voice": dict(PROFILES[style["id"]]),
                    "production": direction_for(style["id"]),
                    "motion": palette(style["id"]),
                    "hook": job["script"].splitlines()[0][:32]
                    if job["script"].strip()
                    else "先确认文稿",
                },
            )
        )
    selected = idea_selection(job)
    if selected:
        favored_id = selected["option"]["native_style"]
        ranked = [
            (score + (100000 if option["id"] == favored_id else 0), tie, option)
            for score, tie, option in ranked
        ]
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
    chosen, families = [], set()
    for _, _, option in ranked:
        if option["family"] not in families:
            chosen.append(option)
            families.add(option["family"])
    return {
        "version": 2,
        "policy_version": policy,
        "brief": brief,
        "fingerprint": fingerprint(job, brief, policy=policy),
        "options": chosen[:3],
        "inputs": fields,
        "method": "本机可解释匹配：商品文稿、类别、目标人群和希望气质；每种视觉家族选一项。相同输入结果稳定，不推断功效、不按点击次数随机更换。",
    }


def _recommend(job, brief, *, legacy=False, policy=3):
    from .production_direction import direction_for
    from .shotcraft import palette

    brief = (
        Brief.model_validate(brief).model_dump() if isinstance(brief, dict) else brief.model_dump()
    )
    if (
        not legacy
        and brief["format"] != "auto"
        and any(brief[k].strip() for k in ("category", "audience", "tone"))
    ):
        return contextual(job, brief, policy)
    text = " ".join([job["title"], job["script"], *brief.values()])
    visual = sum(a["kind"] != "audio" for a in job["assets"])
    video = any(a["kind"] == "video" for a in job["assets"])
    ranked = []
    pool = DIRECTIONS if brief["format"] != "auto" else CATALOG[:-3]
    priority = {
        "showcase": "cinema",
        "recommendation": "social",
        "review": "lab",
        "narrated": "lab",
    }.get(brief["format"])
    for index, style in enumerate(pool):
        hits = [w for w in style["keywords"].split() if w in text]
        score = (
            (40 if style["id"] == priority else 0)
            + len(hits) * 10
            + (4 if style["id"] == "evidence" and video else 0)
            + (2 if style["id"] == "editorial" else 0)
        )
        missing = [] if visual else ["上传真实商品图片或视频"]
        if style["id"] in ("quiet", "collage") and visual < 2:
            missing.append("建议补充生活场景素材，当前只能使用已有画面")
        if brief["format"] == "review":
            missing.append("测评需真实测试视频、测试条件说明与证据镜头；外观解说不等于测评")
        ranked.append(
            (
                score,
                -index,
                {
                    **style,
                    "name": {"cinema": "克制质感", "social": "生活种草", "lab": "细节解说"}.get(
                        style["id"], style["name"]
                    ),
                    "reason": ("匹配：" + "、".join(hits) if hits else "适合作为可控的对照方案")
                    + f"；已有 {visual} 份画面素材"
                    + ("，可展示真实视频选段" if video else "，使用图片运镜"),
                    "missing": missing,
                    "motion": palette(style["id"]),
                    "production": direction_for(style["id"]),
                    "voice": direction_for(style["id"])["voice"],
                },
            )
        )
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return {
        "version": 1,
        "brief": brief,
        "fingerprint": fingerprint(job, brief),
        "options": [r[2] for r in ranked[:3]],
        "method": "本地可解释规则；不读取画面内容，不推断产品功效",
    }


def recommend(job, brief, *, legacy=False, policy=5):
    from .prompt_catalog import match_direction
    from .shot_library import INDEX_SHA256, suggest

    result = _recommend(job, brief, legacy=legacy, policy=policy)
    if policy >= 4 and not legacy and len({o["family"] for o in result["options"]}) < 3:
        result = contextual(job, result["brief"], policy=policy)
    for option in result["options"]:
        direction = match_direction(job, result["brief"], option["id"])
        primary = {
            "premium": "product-shape-reveal",
            "lifestyle": "media-punch-in",
            "demo": "detail-dual-window",
        }[option["family"]]
        direction["cards"].sort(key=lambda c: c["recipe"] != primary)
        option["prompt_direction"] = direction
        option["reference_matches"] = suggest(job, result["brief"], option["family"])
    if policy >= 4 and not legacy:
        from .prompt_catalog import select_product_directions

        result["policy_version"] = policy
        result["fingerprint"] = fingerprint(job, result["brief"], policy=policy)
        select_product_directions(job, result["brief"], result["options"])
    if policy >= 5 and not legacy:
        for option in result["options"]:
            option["prompt_direction"].update(
                mix_policy="semantic-mix-v1",
                method=option["prompt_direction"]["method"]
                + " 同片按逐句内容组合细节/完整原文/场景交接卡；动作完整留看，数据销售须完整来源。",
            )
    result["reference_library"] = {
        "stats": {"cards": 124, "styles": 150, "samples": 150},
        "sha256": INDEX_SHA256,
    }
    result["prompt_fingerprint"] = signature(
        {
            "input": result["fingerprint"],
            "cards": [
                [c["digest"] for c in s["prompt_direction"]["cards"]] for s in result["options"]
            ],
        }
    )
    return result


def validate_creative(job, data):
    c = Creative.model_validate(data).model_dump()
    expected = recommend(job, c["brief"])
    if c["fingerprint"] == fingerprint(job, c["brief"]):
        expected = recommend(job, c["brief"], legacy=True)
    elif c["fingerprint"] == fingerprint(job, c["brief"], policy=2):
        expected = recommend(job, c["brief"], policy=2)
    elif c["fingerprint"] == fingerprint(job, c["brief"], policy=3):
        expected = recommend(job, c["brief"], policy=3)
    elif c["fingerprint"] == fingerprint(job, c["brief"], policy=4):
        expected = recommend(job, c["brief"], policy=4)
    if c["fingerprint"] != expected["fingerprint"] or c["style_id"] not in {
        x["id"] for x in expected["options"]
    }:
        raise ValueError("商品、脚本或素材已改变，请重新推荐并选定风格")

    # Require readable body text; accents are decoration only.
    def luminance(s):
        vals = [int(s[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        vals = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
        return sum(a * b for a, b in zip(vals, [0.2126, 0.7152, 0.0722], strict=True))

    a, b = sorted([luminance(c["brand"]["ink"]), luminance(c["brand"]["paper"])])
    if (b + 0.05) / (a + 0.05) < 4.5:
        raise ValueError("品牌文字和底色对比度须达到 4.5，请使用更深文字或更浅底色")
    return c


def rebase_fingerprint(original, candidate, creative):
    """A local revision keeps its parent's selection policy and confirmed direction."""
    legacy = creative["fingerprint"] == fingerprint(original, creative["brief"])
    policy = next(
        (
            p
            for p in (2, 3, 4, 5)
            if creative["fingerprint"] == fingerprint(original, creative["brief"], policy=p)
        ),
        5,
    )
    return recommend(candidate, creative["brief"], legacy=legacy, policy=policy)["fingerprint"]


def recommend_saved(job, brief):
    """Preserve a frozen selection policy when re-planning the same brief."""
    saved = (job.get("storyboard") or {}).get("creative") or {}
    if saved and saved["brief"] == brief:
        if saved["fingerprint"] == fingerprint(job, brief):
            return recommend(job, brief, legacy=True)
        for policy in (2, 3, 4, 5):
            if saved["fingerprint"] == fingerprint(job, brief, policy=policy):
                return recommend(job, brief, policy=policy)
    return recommend(job, brief)
