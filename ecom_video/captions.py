"""Preserve numeric punctuation and original words while chunking aligned captions."""

import re


def pause_phrases(text, words, start=0, end=0):
    """Split existing phrases at upstream pause boundaries; keep original text/times."""
    import json
    import subprocess
    from pathlib import Path

    original = phrases(text, words, start, end)
    if not words or not any(
        b["start"] - a["end"] >= 0.6 for a, b in zip(words, words[1:], strict=False)
    ):
        return original
    groups, offset = [], 0
    for phrase in original:
        count = sum(c.isalnum() for c in phrase["text"])
        groups.append(words[offset : offset + count])
        offset += count
    bridge = Path(__file__).resolve().parents[1] / "render/remotion/src/pause-pages.cjs"
    result = subprocess.run(
        ["node", str(bridge)], input=json.dumps(groups), capture_output=True, text=True, timeout=15
    )
    if result.returncode:
        raise ValueError("停顿字幕组件不可用，请按锁文件安装Remotion依赖；原文稿未修改")
    pages, output = json.loads(result.stdout), []
    for phrase, anchors, sizes in zip(original, groups, pages, strict=True):
        positions = [i for i, c in enumerate(phrase["text"]) if c.isalnum()]
        offset = 0
        for count in sizes:
            stop = offset + count
            a = positions[offset] if offset else 0
            b = positions[stop] if stop < len(positions) else len(phrase["text"])
            output.append(
                {
                    "text": phrase["text"][a:b],
                    "start": anchors[offset]["start"],
                    "end": anchors[stop - 1]["end"],
                }
            )
            offset = stop
        if offset != len(anchors):
            raise ValueError("停顿字幕字锚点不完整；未修改原稿")
    if "".join(p["text"] for p in output) != "".join(p["text"] for p in original):
        raise ValueError("停顿字幕不得改写原稿")
    return output


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
