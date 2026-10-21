"""Offline measured subtitles adapted from MoneyPrinterTurbo's wrap_text.

Copyright (c) 2024 Harry. MIT; see docs/third-party/MoneyPrinterTurbo-LICENSE.
Only the text layout algorithm is adapted. No upstream services are imported.
"""

import base64
import io
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from .media import font_path


def wrap_text(text, max_width, font, fontsize=60):
    """Measure actual glyph widths, preserving hard breaks and attached marks."""
    if "\n" in text:
        wrapped = [wrap_text(line, max_width, font, fontsize) for line in text.split("\n")]
        return "\n".join(line for line, _ in wrapped), sum(height for _, height in wrapped)
    face = ImageFont.truetype(font, fontsize)
    line_height = max(1, sum(face.getmetrics()))

    def width(value):
        left, _, right, _ = face.getbbox(value.strip())
        return right - left

    if width(text) <= max_width:
        return text, line_height

    def units(token):
        attached = []
        for char in token:
            if attached and unicodedata.category(char).startswith("M"):
                attached[-1] += char
            else:
                attached.append(char)
        return attached

    def split_token(token):
        lines, current = [], ""
        for char in units(token):
            candidate = current + char
            if width(candidate) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)
        return lines

    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip() if current else word
        if width(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if width(word) <= max_width:
            current = word
        else:
            lines.extend(split_token(word))
            current = ""
    if current:
        lines.append(current)
    punctuation = "，。！？；：、,.!?;:)]}）】》」』”’"
    for index in range(1, len(lines)):
        if not lines[index] or lines[index][0] not in punctuation:
            continue
        previous = units(lines[index - 1])
        if len(previous) > 1 and width(previous[-1] + lines[index]) <= max_width:
            lines[index] = previous[-1] + lines[index]
            lines[index - 1] = lines[index - 1][: -len(previous[-1])]
    result = "\n".join(line.strip() for line in lines if line.strip()).strip()
    return result, (result.count("\n") + 1) * line_height


def layout_captions(captions, font_size, color, max_width=912, *, font=None):
    """Rasterize <=2 lines at >=40px, retaining phrase text and timing unchanged.

    Raster pixels use the same font as measurement. They stay inside the existing
    subtitle containers (narrowest 912px); no browser fallback font can overflow.
    """
    source = str(font or font_path())
    result = []
    padding = 4
    for caption in captions:
        for size in range(int(font_size), 39, -1):
            wrapped, _ = wrap_text(caption["text"], max_width - 2 * padding, source, size)
            lines = wrapped.split("\n")
            if len(lines) <= 2:
                break
        else:
            raise ValueError("字幕过长，无法在可读字号下排成两行，请缩短该段文稿")
        face = ImageFont.truetype(source, size)
        boxes = [face.getbbox(line) for line in lines]
        widths = [box[2] - box[0] for box in boxes]
        if max(widths, default=0) > max_width - 2 * padding:
            raise ValueError("字幕无法在安全宽度内排成两行，请检查文字")
        line_height = max(sum(face.getmetrics()), round(size * 1.45))
        width = max(1, max(widths, default=0)) + 2 * padding
        height = len(lines) * line_height + 2 * padding
        image = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(image)
        for index, (line, box, line_width) in enumerate(zip(lines, boxes, widths, strict=True)):
            y = padding + index * line_height + (line_height - (box[3] - box[1])) / 2 - box[1]
            draw.text(((width - line_width) / 2 - box[0], y), line, font=face, fill=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result.append(
            {
                **caption,
                "lines": lines,
                "font_size": size,
                "width": width,
                "height": height,
                "image": "data:image/png;base64,"
                + base64.b64encode(buffer.getvalue()).decode("ascii"),
            }
        )
    return result


def prepare_captions(props):
    """Shared film/preview entry point; upstream does not change phrase timing."""
    from .captions import phrases

    color = (
        props["brand"]["paper"]
        if props.get("motionPlan", {}).get("version") == 2
        and props["style"] in ("lab", "evidence", "bauhaus")
        else "#ffffff"
        if props.get("motionPlan", {}).get("version") == 2
        and props["style"] in ("cinema", "quiet", "social", "collage", "kinetic")
        else props["brand"]["ink"]
        if props.get("shotRecipe") is not None
        or props.get("transition") in ("push-stack", "line-carry")
        or props.get("exitTransition") in ("push-stack", "line-carry")
        else props["brand"]["paper"]
        if props.get("treatment") == "footage" and props["style"] in ("lab", "evidence", "bauhaus")
        else "#ffffff"
        if props["style"] in ("cinema", "quiet") or props.get("treatment") == "footage"
        else props["brand"]["ink"]
    )
    return layout_captions(
        phrases(props["text"], props["words"], props["voiceStart"], props["voiceEnd"]),
        props["brand"]["subtitle_size"],
        color,
    )
