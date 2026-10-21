"""Project-owned alignment adapter. ASR tokens are evidence; unmatched text is flagged.

Uses sherpa-onnx public OfflineRecognizer API and a standard edit-distance alignment.
No code from video-talkcraft is used. Does not claim phonetic forced alignment.
"""

import unicodedata
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from pypinyin import lazy_pinyin
from zhconv import convert


def letters(text):
    return [(i, c) for i, c in enumerate(text) if c.isalnum()]


def key(char):
    char = convert(unicodedata.normalize("NFKC", char).lower(), "zh-cn")
    return "".join(lazy_pinyin(char))


class AlignmentMismatch(ValueError):
    def __init__(self, message, script, raw, duration, coverage=0, code="script_mismatch"):
        super().__init__(message)
        self.diagnostic = {
            "code": code,
            "message": message,
            "transcript": "".join(w["text"] for w in raw),
            "script": script,
            "script_coverage": round(coverage, 3),
            "duration": duration,
        }


def transcribe(wav, model):
    model = Path(model)
    recognizer = sherpa_onnx.OfflineRecognizer.from_fire_red_asr_ctc(
        model=str(model / "model.int8.onnx"), tokens=str(model / "tokens.txt"), num_threads=4
    )
    samples, sr = sf.read(wav, dtype="float32")
    words = []
    # Bounded 40-second windows. Prefer a low-energy boundary in the final 5 seconds.
    cursor = 0
    while cursor < len(samples):
        stop = min(len(samples), cursor + sr * 40)
        if stop < len(samples):
            candidates = range(max(cursor + sr * 30, stop - sr * 5), stop, int(sr * 0.1))
            stop = min(
                candidates, key=lambda x: float(np.mean(samples[x : x + int(sr * 0.08)] ** 2))
            )
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, np.ascontiguousarray(samples[cursor:stop]))
        recognizer.decode_stream(stream)
        tokens = stream.result.tokens
        times = list(stream.result.timestamps)
        for i, token in enumerate(tokens):
            text = token.replace("▁", "").strip()
            if not text:
                continue
            at = cursor / sr + times[i]
            end = min(
                cursor / sr + (times[i + 1] if i + 1 < len(times) else times[i] + 0.18),
                at + 0.45,
                stop / sr,
            )
            if end > at:
                words.append({"text": text, "start": at, "end": end})
        cursor = stop
    return words, len(samples) / sr


def align(script, raw, duration):
    target = [(si, c) for si, line in enumerate(script.splitlines()) for _, c in letters(line)]
    observed = []
    for word in raw:
        chars = letters(word["text"])
        for i, (_, char) in enumerate(chars):
            width = (word["end"] - word["start"]) / len(chars)
            observed.append((char, word["start"] + width * i, word["start"] + width * (i + 1)))
    if not target or not observed:
        raise AlignmentMismatch("配音中没有可对齐的人声", script, raw, duration, code="no_speech")
    # Minimum edit distance; substitutions remain unanchored, matching homophones are anchors.
    a = [key(c) for _, c in target]
    b = [key(c) for c, _, _ in observed]
    n, m = len(a), len(b)
    cost = np.zeros((n + 1, m + 1), dtype=np.int32)
    cost[:, 0] = np.arange(n + 1)
    cost[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i, j] = min(
                cost[i - 1, j] + 1,
                cost[i, j - 1] + 1,
                cost[i - 1, j - 1] + (0 if a[i - 1] == b[j - 1] else 2),
            )
    mapping = {}
    i, j = n, m
    while i and j:
        if cost[i, j] == cost[i - 1, j - 1] + (0 if a[i - 1] == b[j - 1] else 2):
            if a[i - 1] == b[j - 1]:
                mapping[i - 1] = observed[j - 1][1:]
            i -= 1
            j -= 1
        elif cost[i, j] == cost[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    if len(mapping) / n < 0.35:
        raise AlignmentMismatch(
            "配音与稿件匹配不足，请使用对应原稿或更换配音；下方可查看识别内容和历史文稿建议。",
            script,
            raw,
            duration,
            len(mapping) / n,
        )
    timings = [None] * n
    for i, t in mapping.items():
        timings[i] = t
    repairs = []
    i = 0
    while i < n:
        if timings[i] is not None:
            i += 1
            continue
        start = i
        while i < n and timings[i] is None:
            i += 1
        left = timings[start - 1][1] if start else 0
        right = timings[i][0] if i < n else duration
        step = (right - left) / (i - start)
        if (
            step <= 0.001
            and not repairs
            and len(mapping) / n >= 0.9
            and i - start <= 2
            and start > 0
            and i < n
            and start - 1 in mapping
            and i in mapping
            and target[start - 1][0] == target[start][0] == target[i][0]
            and -0.005 <= right - left <= 0.002
        ):
            # CTC can omit a short character without leaving silence between adjacent tokens.
            # Borrow at most 80ms/40% from each neighbour; all three timings become estimates.
            a0, a1 = timings[start - 1]
            b0, b1 = timings[i]
            left = a1 - min(0.08, (a1 - a0) * 0.4)
            right = b0 + min(0.08, (b1 - b0) * 0.4)
            step = (right - left) / (i - start)
            if step >= 0.02:
                timings[start - 1] = (a0, left)
                timings[i] = (right, b1)
                mapping.pop(start - 1)
                mapping.pop(i)
                repairs.append(
                    {
                        "reason": "adjacent_ctc_gap",
                        "sentence": target[start][0],
                        "characters": "".join(target[k][1] for k in range(start, i)),
                        "estimated_neighbours": 2,
                        "requires_listening": True,
                    }
                )
            else:
                step = 0
        if step <= 0.001:
            raise AlignmentMismatch(
                "缺失文字无法插值，请检查稿件与配音",
                script,
                raw,
                duration,
                len(mapping) / n,
                code="timing_gap",
            )
        for k in range(start, i):
            timings[k] = (left + step * (k - start), left + step * (k - start + 1))
    sentences = []
    cursor = 0
    for si, text in enumerate(script.splitlines()):
        rows = []
        anchors = 0
        for _, c in letters(text):
            start, end = timings[cursor]
            anchored = cursor in mapping
            anchors += anchored
            rows.append(
                {"text": c, "start": round(start, 4), "end": round(end, 4), "anchored": anchored}
            )
            cursor += 1
        if not rows:
            raise ValueError("每个语义拍至少需要一个可读文字")
        coverage = anchors / len(rows)
        sentences.append(
            {
                "i": si,
                "text": text,
                "start": rows[0]["start"],
                "end": rows[-1]["end"],
                "words": rows,
                "match": round(coverage, 3),
                "ok": coverage >= 0.9,
            }
        )
    return {"sentences": sentences, "total": duration, "sr": 16000, "timing_repairs": repairs}


if __name__ == "__main__":
    import json
    import sys

    wav, script_path, model, output = sys.argv[1:]
    words, duration = transcribe(wav, model)
    try:
        result = align(Path(script_path).read_text(), words, duration)
    except AlignmentMismatch as exc:
        result = {"sentences": [], "total": duration, "sr": 16000, "diagnostic": exc.diagnostic}
    result["raw_words"] = words
    Path(output).write_text(json.dumps(result, ensure_ascii=False))
