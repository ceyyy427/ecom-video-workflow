"""Bounded, locally measured type. Anime.js clip/stagger concept, Remotion frame clock.
No remote scripts, fabricated word anchors or changes to the approved narration.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .media import font_path
from .subtitle_layout import layout_captions


class Typography(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["impact", "reveal", "contrast"]
    keyword: str = Field(default="", max_length=8)


def validate_typography(value, headline, text):
    if not value:
        return
    if not headline or headline not in text:
        raise ValueError("文字动效的字卡必须摘自本镜文稿")
    keyword = value.get("keyword") or headline
    if not any(c.isalnum() for c in keyword) or keyword not in headline:
        raise ValueError("着重关键词必须摘自本镜字卡")


def prepare_typography(props, shot):
    value = props.get("typography")
    if not value or not props.get("headline"):
        return None
    headline, text = props["headline"], props["text"]
    validate_typography(value, headline, text)
    keyword = value.get("keyword") or headline

    def clean(s):
        return "".join(c for c in s if c.isalnum())

    offset = len(clean(text[: text.index(headline)]))
    anchors = props["words"][offset : offset + len(clean(headline))]
    verified = (
        text.count(headline) == 1
        and bool(anchors)
        and all(w.get("anchored") is True for w in anchors)
        and "".join(w["text"] for w in anchors).casefold() == clean(headline).casefold()
    )
    start = max(0, anchors[0]["start"] if verified else props["voiceStart"])
    end = min(props["frames"] / 30, max(start + 0.7, props["voiceEnd"]))
    plan = shot.get("motion_plan") or {}
    protected = plan.get("protect_action", True) and any(
        w["start"] < end and w["end"] > start for w in plan.get("windows", [])
    )
    protected = protected or any(c.get("complete_action") for c in shot.get("source_cuts") or [])
    # With uncertain word times, use a steady sentence-level title, never fake karaoke.
    editorial = props.get("format") == "showcase" and not props["words"]
    static = not (verified or editorial) or bool(protected)
    parts = [s for s in re.split("(" + re.escape(keyword) + ")", headline, maxsplit=1) if s]
    if value["mode"] == "reveal" and len(parts) == 1:
        # Two semantic halves, not a distracting per-character cascade.
        mid = max(1, len(headline) // 2)
        parts = [headline[:mid], headline[mid:]] if len(headline) > 1 else [headline]
    from PIL import ImageFont

    font = str(font_path())
    sizes = [154 if s == keyword else 88 for s in parts]
    if value["mode"] == "contrast":
        sizes = [160 if s == keyword else 60 for s in parts]

    def measure(s, n):
        return ImageFont.truetype(font, n).getlength(s)

    if value["mode"] != "contrast":
        width = sum(measure(s, n) for s, n in zip(parts, sizes, strict=True)) + 28 * len(parts)
        scale = min(1, 840 / width)
        sizes = [int(n * scale) for n in sizes]
    else:
        sizes = [
            min(n, int(n * 820 / max(1, measure(s, n)))) for s, n in zip(parts, sizes, strict=True)
        ]
    segments = []
    cursor = offset
    for part, size in zip(parts, sizes, strict=True):
        image = layout_captions([{"text": part}], size, "#ffffff", 856, font=font)[0]
        at = props["words"][cursor]["start"] if verified and cursor < len(props["words"]) else start
        if editorial:
            at = min(end - 0.3, start + len(segments) * 0.22)
        segments.append(
            {k: image[k] for k in ("text", "image", "width", "height")}
            | {
                "keyword": part == keyword,
                "start": max(start, min(end - 0.3, at)),
            }
        )
        cursor += len(clean(part))
    raw_height = (
        sum(s["height"] + 12 for s in segments)
        if value["mode"] == "contrast"
        else max(s["height"] + 12 for s in segments)
    )
    raw_width = (
        max(s["width"] + 20 for s in segments)
        if value["mode"] == "contrast"
        else sum(s["width"] + 20 for s in segments) + 8 * (len(segments) - 1)
    )
    # Match RenderContent's actual branch, including pre-v2 saved layouts.
    recipe_layout = (
        props.get("shotRecipe") is not None
        or props.get("transition") in ("push-stack", "line-carry")
        or props.get("exitTransition") in ("push-stack", "line-carry")
    )
    direction_layout = not recipe_layout and (
        props.get("treatment") == "footage" or props["style"] in ("cinema", "social", "lab")
    )
    top, available_height = 165, 224
    if direction_layout and props.get("treatment") != "footage":
        if props["style"] == "social":
            top = 280  # below the existing social label, above media at550
        elif props["style"] == "lab":
            top, available_height = 230, 175  # between label and evidence line
    elif not recipe_layout and not direction_layout:
        available_height = {"evidence": 150, "collage": 190}.get(props["style"], 224)
    scale = min(1, available_height / raw_height, 880 / raw_width)
    return {
        "top": top,
        "scale": scale,
        "height": raw_height * scale,
        "width": raw_width * scale,
        "mode": value["mode"],
        "keyword": keyword,
        "segments": segments,
        "start": start,
        "end": end,
        "static": static,
        "basis": "anchored_words"
        if verified
        else "silent_editorial"
        if editorial
        else "sentence_fallback",
        "guard": "action_protected" if protected else "unchanged",
        "version": "type-v1",
    }
