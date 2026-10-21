"""Local media validation and bounded subprocesses; no shell or remote sources."""

import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .host_os import process_options, stop_process

MAX_UPLOAD = 100 * 1024**2
EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".mov", ".webm"},
    "audio": {".wav", ".mp3", ".m4a"},
}
DEMUX = {
    ".mp4": "mov",
    ".mov": "mov",
    ".m4a": "mov",
    ".webm": "matroska",
    ".wav": "wav",
    ".mp3": "mp3",
}


def safe_path(root, relative):
    if Path(relative).is_absolute():
        raise ValueError("不允许绝对路径")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("文件路径超出工作目录")
    return path


def digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def font_path():
    paths = [
        os.getenv("ECOM_FONT", ""),
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in paths:
        if p and Path(p).is_file():
            return Path(p)
    raise ValueError("未找到中文字体，请设置 ECOM_FONT 为本地中文 TTF/TTC/OTF 字体路径")


def input_options(path):
    return ["-protocol_whitelist", "file,pipe", "-f", DEMUX[Path(path).suffix.lower()]]


def probe(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        *input_options(path),
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("媒体无法解析或处理超时，请重新导出标准媒体文件") from exc


def inspect_media(path, kind):
    path = Path(path)
    if kind not in EXTENSIONS or path.suffix.lower() not in EXTENSIONS[kind]:
        raise ValueError("不支持的文件格式")
    if not 0 < path.stat().st_size <= MAX_UPLOAD:
        raise ValueError("单文件须大于 0 且不超过 100 MiB")
    if kind == "image":
        try:
            with Image.open(path) as img:
                if img.format not in ("JPEG", "PNG", "WEBP") or img.width * img.height > 16_000_000:
                    raise ValueError("图片格式不支持或超过 1600 万像素")
                if getattr(img, "is_animated", False):
                    raise ValueError("暂不支持动图，请转为视频")
                img.load()
                return {"width": img.width, "height": img.height, "format": img.format}
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("图片内容无效，请重新导出 PNG/JPG/WebP") from exc
    data = probe(path)
    stream_type = "audio" if kind == "audio" else "video"
    stream = next((s for s in data["streams"] if s["codec_type"] == stream_type), None)
    duration = float(data.get("format", {}).get("duration", 0))
    if not stream or not math.isfinite(duration) or not 0 < duration <= 600:
        raise ValueError("媒体须有有效音视频流，时长不超过 600 秒")
    if kind == "audio" and duration > 120:
        raise ValueError("配音不得超过 120 秒")
    if kind == "video" and (stream.get("width", 0) * stream.get("height", 0) > 16_000_000):
        raise ValueError("视频分辨率超过 1600 万像素")
    if kind == "video":
        # Container duration may be extended by audio after the picture has ended.
        raw_duration = stream.get("duration")
        if raw_duration is None:
            tag = stream.get("tags", {}).get("DURATION")
            if tag:
                try:
                    hours, minutes, seconds = tag.split(":")
                    raw_duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                except (ValueError, TypeError):
                    raw_duration = None
        if raw_duration is None and not any(s["codec_type"] == "audio" for s in data["streams"]):
            raw_duration = duration
        try:
            visual_duration = float(raw_duration)
        except (ValueError, TypeError):
            raise ValueError("无法确认视频画面时长，请重新导出标准 MP4") from None
        if not math.isfinite(visual_duration) or not 0 < visual_duration <= 600:
            raise ValueError("视频画面流时长无效，请重新导出标准 MP4")
        duration = min(duration, visual_duration)
    return {
        "duration": duration,
        "codec": stream["codec_name"],
        "width": stream.get("width"),
        "height": stream.get("height"),
    }


def run_checked(cmd, check=lambda: None, timeout=300, capture=False):
    """Poll while FFmpeg runs, so cancellation terminates the actual process."""
    check()
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **process_options()
        )
        start = time.monotonic()
        try:
            while proc.poll() is None:
                check()
                if time.monotonic() - start > timeout:
                    raise RuntimeError("媒体处理超时，请缩短素材后重试")
                time.sleep(0.15)
            check()
            if proc.returncode:
                log.seek(0, 2)
                length = log.tell()
                log.seek(max(0, length - 2000))
                raise RuntimeError("FFmpeg 处理失败: " + log.read().decode(errors="replace"))
            if capture:
                log.seek(0, 2)
                if log.tell() > 512 * 1024:
                    raise ValueError("媒体诊断输出过长")
                log.seek(0)
                return log.read().decode(errors="replace")
        finally:
            if proc.poll() is None:
                stop_process(proc)
