"""Phrase captions on proven edges; uncertain records keep their existing paging."""

import re

from .subtitle_layout import layout_captions


def client_captions(props):
    words = props["words"]

    def clean(s):
        return "".join(c for c in s if c.isalnum()).casefold()

    if not words or clean(props["text"]) != clean("".join(w["text"] for w in words)):
        return None
    rows, offset = [], 0
    for part in re.findall(r"[^，。！？；!?]+", props["text"]):
        count = len(clean(part))
        if not count:
            continue
        span = words[offset : offset + count]
        if len(span) != count or any(len(clean(w["text"])) != 1 for w in span):
            return None
        if not span[0].get("anchored") or not span[-1].get("anchored"):
            return None
        start, end = max(0, span[0]["start"]), min(props["frames"] / 30, span[-1]["end"])
        if end <= start:
            return None
        rows.append(
            {
                "text": part.strip(),
                "start": round(start, 4),
                "end": round(end, 4),
                "basis": "verified_phrase_boundaries",
            }
        )
        offset += count
    if offset != len(words):
        return None
    try:
        return layout_captions(
            rows, max(72, props["brand"]["subtitle_size"]), "#ffffff", max_width=880
        )
    except ValueError:
        # A valid long clause still has safe pages in the existing captioner.
        return None


def protect_labels(props, captions):
    """Break before a confirmed SKU, never between its name and model suffix.

    Only raster layout changes. Phrase text, uncertain anchors and timing remain
    intact. Unrecognized/long labels retain the normal measured fallback.
    """
    for caption in captions:
        for term in props.get("protectedTerms", []):
            if not term or len(term) > 12 or term not in caption["text"]:
                continue
            before, after = caption["text"].split(term, 1)
            display = before + ("\n" if before else "") + term + after
            try:
                replacement = layout_captions(
                    [{"text": display}],
                    max(72, props["brand"]["subtitle_size"]),
                    "#ffffff",
                    max_width=880,
                )[0]
            except ValueError:
                continue
            if any(term in line for line in replacement["lines"]):
                for key in ("lines", "font_size", "width", "height", "image"):
                    caption[key] = replacement[key]
            break
    return captions
