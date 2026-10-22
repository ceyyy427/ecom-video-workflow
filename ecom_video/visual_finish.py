"""Project-owned local presentation rules. Upstream skills are read-only references.

Never rewrite narration, invent word timings, execute prompts, or load remote assets.
"""

import base64
import io
import os
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .media import font_path
from .subtitle_layout import layout_captions, prepare_captions, wrap_text

VERSION = "polished-v1"


def enabled(props):
    plan = props.get("motionPlan") or {}
    return plan.get("version") == 2 and plan.get("visual_finish") == VERSION


def title_layout(props):
    text = props["headline"]
    if not text:
        return None
    film = props["style"] in ("cinema", "quiet")
    color = (
        "#ffffff"
        if props.get("clientPresentation")
        else "#f5eddf"
        if film
        else props["brand"]["ink"]
    )
    candidates = (
        [
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simsun.ttc",
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        ]
        if film
        else []
    )
    source = str(next((path for path in candidates if path.is_file()), font_path()))
    maximum = 82 if props["style"] == "quiet" else 110 if film else 112
    # Renderer reserves the measured title height before cards/footage.
    for size in range(maximum, 57, -1):
        text_lines, _ = wrap_text(text, 856, source, size)
        face = ImageFont.truetype(source, size)
        height = len(text_lines.split("\n")) * max(sum(face.getmetrics()), round(size * 1.45)) + 8
        if len(text_lines.split("\n")) <= 2 and height <= 224:
            result = layout_captions([{"text": text}], size, color, 864, font=source)[0]
            result["font_family"] = Path(source).stem
            return result
    raise ValueError("标题无法在安全区域内保持可读字号，请缩短本镜标题；原文稿未修改")


def encode(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def emphasize(props, captions):
    text, headline, words = props["text"], props["headline"], props["words"]
    # No guessing for repeated, missing, very long or estimated anchors.
    count = sum(c.isalnum() for c in headline)
    if not 2 <= count <= 12 or text.count(headline) != 1:
        return captions
    offset = sum(c.isalnum() for c in text[: text.index(headline)])
    anchors = words[offset : offset + count]
    if len(anchors) != count or not all(w.get("anchored") is True for w in anchors):
        return captions
    normalized = "".join(c for c in headline if c.isalnum())
    normalized_text = "".join(c for c in text if c.isalnum())
    folded_text, folded_headline = normalized_text.casefold(), normalized.casefold()
    if folded_text.find(folded_headline) != folded_text.rfind(folded_headline):
        return captions
    if "".join(w["text"] for w in anchors).casefold() != normalized.casefold():
        return captions
    start, end = anchors[0]["start"], anchors[-1]["end"]
    if end - start < 0.2:
        return captions
    clean = headline.translate(str.maketrans("", "", "，。！？；：、"))
    for caption in captions:
        if not caption["start"] <= start < end <= caption["end"]:
            continue
        for index, line in enumerate(caption["lines"]):
            if clean not in line:
                continue
            image = Image.open(
                io.BytesIO(base64.b64decode(caption["image"].split(",", 1)[1]))
            ).convert("RGBA")
            face = ImageFont.truetype(str(font_path()), caption["font_size"])
            box = face.getbbox(line)
            line_width = box[2] - box[0]
            line_height = max(sum(face.getmetrics()), round(caption["font_size"] * 1.45))
            left = (caption["width"] - line_width) / 2 - box[0]
            y = 4 + index * line_height + (line_height - (box[3] - box[1])) / 2 - box[1]
            x = left + face.getlength(line[: line.index(clean)])
            right = min(image.width - 1, x + face.getlength(clean) + 3)
            top = max(0, y + box[1] - 3)
            bottom = min(image.height - 1, y + box[3] + 3)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (max(0, x - 3), top, right, bottom),
                radius=5,
                fill=(*ImageColor.getrgb(props["brand"]["accent"]), 65),
            )
            draw.text((x, y), clean, font=face, fill=caption_color(props))
            caption["emphasis"] = {
                "text": headline,
                "start": start,
                "end": end,
                "basis": "anchored_words",
                "image": encode(image),
            }
            break
    return captions


def caption_color(props):
    if props.get("clientPresentation"):
        return "#ffffff"
    style = props["style"]
    return (
        props["brand"]["paper"]
        if style in ("lab", "evidence", "bauhaus")
        else "#ffffff"
        if style in ("cinema", "quiet", "social", "collage", "kinetic")
        else props["brand"]["ink"]
    )


def prepare_visuals(props):
    captions = prepare_captions(props)
    if props.get("clientPresentation"):
        from .client_finish import client_captions, protect_labels

        captions = protect_labels(props, client_captions(props) or captions)
    if not enabled(props):
        return {"captions": captions}
    result = {"captions": emphasize(props, captions)}
    title = title_layout(props)
    if title:
        result["titleLayout"] = title
    return result


def caption_record(caption):
    result = {k: v for k, v in caption.items() if k not in ("image", "emphasis")}
    if caption.get("emphasis"):
        result["emphasis"] = {k: v for k, v in caption["emphasis"].items() if k != "image"}
    return result
