"""Versioned, data-only creative plans shared by previews and customer production."""

import copy
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .creative import CATALOG, Strict, signature
from .film_styles import catalog, recommend

VERSION = "creative-plan-v1"
ADAPTERS = {
    "swiss-motion": (
        "关键词冲击",
        "kinetic",
        ["crash-zoom-punch", "media-punch-in", "marker-underline-title", "product-brand-snap"],
    ),
    "blueprint": (
        "结构拆解",
        "lab",
        [
            "scanline-annotate-focus",
            "detail-dual-window",
            "product-detail-bracket",
            "product-explain-relay",
        ],
    ),
    "dataviz": (
        "资料说明",
        "evidence",
        [
            "product-card-progressive-assemble",
            "product-fact-row",
            "detail-dual-window",
            "marker-underline-title",
        ],
    ),
    "paper-popup": (
        "纸张叙事",
        "collage",
        ["product-shape-reveal", "blur-slide", "product-explain-relay", "product-shape-reveal"],
    ),
    "dark-keynote": (
        "聚光发布",
        "cinema",
        ["product-type-mask", "product-hero-stage", "product-detail-bracket", "product-brand-snap"],
    ),
    "kino-montage": (
        "节奏剪辑",
        "social",
        ["media-punch-in", "same-frame-panels", "crash-zoom-punch", "product-explain-relay"],
    ),
}


def plain_text(value):
    if not isinstance(value, str):
        raise ValueError("需要填写文字")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in value):
        raise ValueError("输入不能包含控制字符")
    return value.strip()


class Claim(Strict):
    text: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("text", "source", mode="before")
    @classmethod
    def single_unit(cls, value):
        value = plain_text(value)
        if "\n" in value or "\r" in value:
            raise ValueError("每条事实与来源请分别写在一行，保留完整语境")
        return value


class Datum(Strict):
    label: str = Field(min_length=1, max_length=24)
    value: float = Field(ge=-1e9, le=1e9)
    unit: str = Field(default="", max_length=16)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("label", "unit", "source", mode="before")
    @classmethod
    def readable_data(cls, value):
        value = plain_text(value)
        if "\n" in value or "\r" in value:
            raise ValueError("数据名称、单位和来源分别填写一行")
        return value


class MaterialRef(Strict):
    origin: Literal["upload", "customer"]
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    source_in: float = Field(default=0, ge=0, le=600)


class ContentBrief(Strict):
    idea: str = Field(min_length=2, max_length=1000)
    subject: str = Field(default="", max_length=60)
    audience: str = Field(default="", max_length=120)
    tone: str = Field(default="", max_length=120)
    mode: Literal["code", "footage"] = "code"
    facts: list[Claim] = Field(default_factory=list, max_length=8)
    data: list[Datum] = Field(default_factory=list, max_length=6)
    materials: list[MaterialRef] = Field(default_factory=list, max_length=8)
    preferred: str | None = Field(default=None, max_length=80)
    target_seconds: Literal[24] = 24

    @field_validator("idea", "subject", "audience", "tone", mode="before")
    @classmethod
    def readable(cls, value):
        return plain_text(value)

    @model_validator(mode="after")
    def coherent(self):
        if any(
            "\n" in value or "\r" in value for value in (self.subject, self.audience, self.tone)
        ):
            raise ValueError("主题、人群和气质请分别写在一行")
        refs = [(a.origin, a.project_id, a.id) for a in self.materials]
        if len(set(refs)) != len(refs):
            raise ValueError("同一份素材只需选择一次，可直接调整入点")
        return self


def subject_for(brief):
    return brief.subject or next(
        (s.strip()[:40] for s in re.split(r"[。！？\n]", brief.idea) if s.strip()), "这个想法"
    )


def build_plan(brief: ContentBrief, materials: list, *, engine="preview-v1"):
    if brief.preferred and brief.preferred not in ADAPTERS:
        raise ValueError("该风格目前仅供参考，请从首批六个可执行方向中选择")
    subject = subject_for(brief)
    claims = [{"id": "topic", "text": subject, "source": "用户输入的创作主题，作为待核对设定"}]
    claims += [{"id": f"fact-{i}", **f.model_dump()} for i, f in enumerate(brief.facts)]
    claims += [
        {"id": f"data-{i}", "text": f"{d.label}：{d.value}{d.unit}", "source": d.source}
        for i, d in enumerate(brief.data)
    ]
    first = claims[1] if len(claims) > 1 else claims[0]
    second = claims[2] if len(claims) > 2 else first
    rows = {r["id"]: r for r in catalog()}
    proposed = recommend(brief.idea, brief.audience, brief.tone, brief.mode, brief.preferred)
    order = [r["id"] for r in proposed["options"] if r["id"] in ADAPTERS]
    order += [key for key in ADAPTERS if key not in order]
    calm = bool(re.search("安静|克制|慢|沉静|柔和", brief.tone))
    audience = brief.audience[:30] or "想了解它的人"
    hooks = {
        "swiss-motion": f"{subject}，先抓住这个重点。",
        "blueprint": f"{subject}，拆开看会怎样？",
        "dataviz": "只看结论？先把依据摆出来。",
        "paper-popup": f"讲给{audience}听，从{subject}开始。",
        "dark-keynote": f"把目光留给{subject}。",
        "kino-montage": f"{subject}，换个角度看。",
    }
    closings = [
        "你会先记住哪一点？",
        "顺着这条线，再回头看整体。",
        "依据和条件，放在一起看。",
        "这一页，你想接着了解什么？",
        "细节看清，答案留给你。",
        "你更想停在哪个画面？",
    ]
    options = []
    for key in order:
        index = list(ADAPTERS).index(key)
        name, style, recipes = ADAPTERS[key]
        colors = next(s["colors"] for s in CATALOG if s["id"] == style)
        paper, ink, accent = colors
        if key == "blueprint":
            paper, ink, accent = "#12394b", "#e2f4ff", "#6ec7eb"
        if key == "dark-keynote":
            paper, ink, accent = "#121919", "#fbf5e8", "#d5b681"
        brand = {"name": "", "paper": paper, "ink": ink, "accent": accent, "subtitle_size": 52}
        body = [second, first] if index in (2, 5) else [first, second]
        texts = [hooks[key], body[0]["text"], body[1]["text"], closings[index]]
        scenes = []
        for i, text in enumerate(texts):
            # The whole fact stays intact, including units and qualifications.
            scenes.append(
                {
                    "id": f"scene-{i + 1:02d}",
                    "text": text,
                    "headline": (
                        subject
                        if subject in text and len(subject) <= 8
                        else next(
                            (
                                part.strip()
                                for part in re.split(r"[，。！？；：]", text)
                                if 0 < len(part.strip()) <= 8
                            ),
                            "",
                        )
                    ),
                    "claim_ids": list(
                        dict.fromkeys(
                            ([body[i - 1]["id"]] if i in (1, 2) else ["topic"])
                            + (
                                [c["id"] for c in claims if c["id"].startswith("data-")]
                                if key == "dataviz"
                                else []
                            )
                        )
                    ),
                    "seconds": 6,
                    "purpose": ["hook", "detail", "evidence", "closing"][i],
                    "recipe": recipes[i],
                    "transition": "cut"
                    if i == 0
                    else "wipe"
                    if index in (0, 3)
                    else "line-carry"
                    if index in (1, 2)
                    else "media-pass"
                    if index == 5
                    else "iris",
                    "material_id": materials[(i + index) % len(materials)]["id"]
                    if materials
                    else None,
                    "visual_reason": f"{name}：本句的完整文本与来源保留，{'使用选定实拍，主体和动作待核对' if materials else '用明确标识的代码图示表达，非实拍'}",
                }
            )
        options.append(
            {
                "id": key,
                "name": name,
                "native_style": style,
                "brand": brand,
                "source": rows[key]["source"],
                "reference_name": rows[key]["name"],
                "status": "adapted",
                "scenes": scenes,
                "script": "\n".join(texts),
                "preview_scene_seconds": [4, 3] if calm else [3, 4],
                "reason": f"围绕“{subject}”，面向{audience}，以{brief.tone or '清楚自然'}组织{name}。"
                + ("现有素材参与取景与画面策略。" if materials else "当前采用代码图示。"),
                "voice_suggestion": {
                    "tone": "平稳、有停顿" if calm else "自然、重点清楚",
                    "speed": 0.95 if calm else 1.05,
                },
                "diagram": key,
            }
        )
    missing = []
    if not materials:
        missing.append("未提供实拍，本版使用代码图示；不能作为商品外观或动作证据")
    if not brief.facts:
        missing.append("未提供额外事实，仅按创作主题作待确认编排")
    if not brief.data:
        missing.append("未提供数值，资料说明方向使用文字依据卡，不生成虚构数据")
    if materials:
        missing.append("画面与文稿、同款/配色和完整动作仍须人工核对，预览不代表审核通过")
    payload = {
        "version": VERSION,
        "brief": brief.model_dump(),
        "subject": subject,
        "claims": claims,
        "data": [d.model_dump() for d in brief.data],
        "materials": copy.deepcopy(materials),
        "options": options,
        "missing": missing,
        "preview_seconds": 7,
        "approvals": [],
        "engine": engine,
    }
    return {**payload, "basis": signature(payload)}
