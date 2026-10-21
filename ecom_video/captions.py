"""Preserve numeric punctuation and original words while chunking aligned captions."""

import re


def phrases(text, words, start=0, end=0):
    positions = [i for i, c in enumerate(text) if c.isalnum()]
    if not positions:
        return []
    if words and len(words) != len(positions):
        raise ValueError("字幕文字与字级锚点数量不一致")
    result = []
    offset = 0
    while offset < len(positions):
        stop = min(offset + 14, len(positions))
        if stop < len(positions):
            # Prefer a real phrase boundary; avoid a final one-character subtitle card.
            candidates = [
                i
                for i in range(offset + 3, stop + 1)
                if re.search(r"[，。！？；：、,;!?]", text[positions[i - 1] + 1 : positions[i]])
            ]
            if candidates:
                stop = candidates[-1]
            elif len(positions) - stop < 4:
                stop = (offset + len(positions)) // 2
        # Keep an ASCII token (including decimal points and percentages) intact.
        while stop < len(positions):
            left, right = positions[stop - 1], positions[stop]
            fragment = text[left : right + 1]
            if not all(c.isascii() and (c.isalnum() or c in ".%+-/") for c in fragment):
                break
            stop += 1
        a = positions[offset]
        b = positions[stop] if stop < len(positions) else len(text)
        caption = re.sub(r"[，。！？；：、]", "", text[a:b]).strip()
        result.append(
            {
                "text": caption,
                "start": words[offset]["start"]
                if words
                else start + (end - start) * offset / len(positions),
                "end": words[stop - 1]["end"]
                if words
                else start + (end - start) * stop / len(positions),
            }
        )
        offset = stop
    return result
