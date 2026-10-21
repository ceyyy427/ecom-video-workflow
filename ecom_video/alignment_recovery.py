"""Bounded local retry and explicitly estimated timing for an owned TTS receipt."""

import json
import sys
from pathlib import Path

VERSION = "alignment-recovery-v1"


def estimated_tts(script, raw, duration):
    from .local_asr import letters

    if not raw or not 0 < duration <= 120:
        raise ValueError("未检测到人声，不能生成听核建议")
    from difflib import SequenceMatcher

    from .local_asr import key

    target = [key(c) for line in script.splitlines() for _, c in letters(line)]
    observed = [key(c) for word in raw for _, c in letters(word["text"])]
    matched = sum(
        block.size
        for block in SequenceMatcher(None, target, observed, autojunk=False).get_matching_blocks()
    )
    if len(observed) < 3 or matched / len(observed) < 0.8 or len(target) / duration > 12:
        raise ValueError("识别内容与文稿不同或证据不足，不能估算通过")
    start, end = max(0, raw[0]["start"]), min(duration, raw[-1]["end"])
    lines = script.splitlines()
    count = sum(len(letters(line)) for line in lines)
    if not count or end - start <= 0 or count / (end - start) > 12:
        raise ValueError("人声长度不足，请检查声音")
    step = (end - start) / count
    cursor = 0
    sentences = []
    for i, line in enumerate(lines):
        words = []
        for _, char in letters(line):
            words.append(
                {
                    "text": char,
                    "start": round(start + cursor * step, 4),
                    "end": round(start + (cursor + 1) * step, 4),
                    "anchored": False,
                }
            )
            cursor += 1
        if not words:
            raise ValueError("文稿没有可读文字")
        sentences.append(
            {
                "i": i,
                "text": line,
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "words": words,
                "match": 0.0,
                "ok": False,
            }
        )
    return {
        "sentences": sentences,
        "total": duration,
        "sr": 16000,
        "raw_words": raw,
        "recovery": {
            "version": VERSION,
            "method": "tts_receipt_estimate",
            "warning": "同稿TTS回执可核对，但这些时间为估算、不是识别锚点。必须逐句听核和校正。",
        },
    }


def retry(wav, script_path, model, output):
    import numpy as np
    import soundfile as sf

    from .local_asr import AlignmentMismatch, align, transcribe

    samples, sr = sf.read(wav, dtype="float32")
    duration = len(samples) / sr
    if not 0 < duration <= 120:
        raise ValueError("仅支持120秒以内的有界本机修复")
    words = []
    for cursor in range(0, len(samples), sr * 12):
        part = samples[cursor : cursor + sr * 12]
        peak = float(np.max(np.abs(part)))
        if peak > 0:
            part = part * min(8, 0.9 / peak)
        chunk = Path(output).with_name("retry-chunk.wav")
        sf.write(chunk, part, sr, subtype="PCM_16")
        rows, _ = transcribe(chunk, model)
        words += [
            {**w, "start": w["start"] + cursor / sr, "end": w["end"] + cursor / sr} for w in rows
        ]
    script = Path(script_path).read_text()
    try:
        result = align(script, words, duration)
    except AlignmentMismatch as exc:
        result = {"sentences": [], "total": duration, "sr": sr, "diagnostic": exc.diagnostic}
    result["raw_words"] = words
    Path(output).write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    retry(*sys.argv[1:])
