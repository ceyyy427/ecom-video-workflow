"""Bounded offline final-film OCR and ASR. Optional checks never silently pass."""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .media import digest, input_options, run_checked

ROOT = Path(__file__).resolve().parents[1]


def scan_ocr(paths, check=lambda: None, reserve=lambda: None):
    if sys.platform != "darwin" or not shutil.which("swift"):
        return {"status": "not_checked", "reason": "此机器没有macOS Vision/Swift本机OCR"}
    script = ROOT / "scripts/local_ocr.swift"
    for _ in paths[:12]:
        reserve()
    with tempfile.TemporaryDirectory(prefix="ecom-ocr-") as temp:
        output = Path(temp) / "result.json"
        run_checked(["swift", str(script), str(output), *map(str, paths[:12])], check, timeout=90)
        value = json.loads(output.read_text())
    if len(value.get("frames", [])) != len(paths[:12]):
        raise ValueError("OCR输出帧数不一致")
    return {
        "status": "sampled",
        "engine": "Apple Vision VNRecognizeTextRequest",
        "adapter_sha256": digest(script),
        "frames": value["frames"],
    }


class _Interrupted(BaseException):
    def __init__(self, cause):
        self.cause = cause


def collect(output, directory, script, scenes, has_voice, check=lambda: None):
    def guarded():
        try:
            check()
        except Exception as exc:
            raise _Interrupted(exc) from exc

    def reserve():
        from .agent_guard import reserve_call

        try:
            reserve_call()
        except Exception as exc:
            raise _Interrupted(exc) from exc

    try:
        guarded()
        return _collect(output, directory, script, scenes, has_voice, guarded, reserve)
    except _Interrupted as exc:
        raise exc.cause from None


def _collect(output, directory, script, scenes, has_voice, check, reserve):
    disabled = {"status": "not_checked", "reason": "本机成片OCR/ASR未启用（ECOM_MEDIA_AUDIT=1）"}
    if os.getenv("ECOM_MEDIA_AUDIT") != "1":
        return {"ocr": dict(disabled), "asr": dict(disabled)}
    directory = Path(directory) / "media-audit"
    directory.mkdir(exist_ok=True)
    times = [round((s["start"] + s["end"]) / 2, 3) for s in scenes[:12]]
    paths = []
    try:
        for i, time in enumerate(times):
            path = directory / f"frame-{i:02d}.jpg"
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(time),
                    *input_options(output),
                    "-i",
                    str(output),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=720:-2",
                    str(path),
                ],
                check,
                timeout=20,
            )
            paths.append(path)
        ocr = scan_ocr(paths, check, reserve)
        for time, frame in zip(times, ocr.get("frames", []), strict=False):
            frame["time"] = time
        if any("error" in f for f in ocr.get("frames", [])):
            ocr["status"] = "partial"
        ocr["scope"] = "每镜中点一帧，最多12帧；非全帧审核"
    except Exception as exc:
        from .db import Conflict

        if isinstance(exc, Conflict):
            raise
        ocr = {"status": "error", "reason": "本机OCR检查失败，需人工核对画面文字"}
    if not has_voice:
        return {
            "ocr": ocr,
            "asr": {
                "status": "not_applicable",
                "reason": "本版未声明口播；未对音乐等音轨做语义识别",
            },
        }
    from .alignment import MODEL

    if not (MODEL / "model.int8.onnx").is_file():
        return {"ocr": ocr, "asr": {"status": "not_checked", "reason": "本机ASR模型未就绪"}}
    try:
        wav, text, out = directory / "final.wav", directory / "script.txt", directory / "asr.json"
        text.write_text(script)
        reserve()
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                *input_options(output),
                "-i",
                str(output),
                "-t",
                "120",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav),
            ],
            check,
            timeout=30,
        )
        run_checked(
            [
                sys.executable,
                "-m",
                "ecom_video.local_asr",
                str(wav),
                str(text),
                str(MODEL),
                str(out),
            ],
            check,
            timeout=120,
        )
        value = json.loads(out.read_text())
        asr = {
            "status": "checked",
            "engine": "firered-ctc-int8",
            "adapter_sha256": digest(ROOT / "ecom_video/local_asr.py"),
            "words": value["raw_words"],
            "duration": value["total"],
            "scope": "成片单声道16kHz实际音轨，最多120秒；识别不是事实或合规认证",
        }
    except Exception as exc:
        from .db import Conflict

        if isinstance(exc, Conflict):
            raise
        asr = {"status": "error", "reason": "成片口播识别失败，需人工听核"}
    return {"ocr": ocr, "asr": asr}


def normalized(text):
    import unicodedata

    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", text).lower())
