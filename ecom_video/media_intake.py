"""Bounded local FFmpeg working copies; never modifies an uploaded original."""

import shutil
import threading
import time
from fractions import Fraction
from pathlib import Path

from .db import Conflict
from .media import MAX_UPLOAD, digest, input_options, inspect_media, probe, run_checked

MAX_VIDEO_SOURCE = 512 * 1024**2
VERSION = "video-intake-v1"
_transcode = threading.Lock()


def rotation_of(stream):
    rotation = next(
        (s["rotation"] for s in stream.get("side_data_list", []) if "rotation" in s),
        stream.get("tags", {}).get("rotate", 0),
    )
    try:
        angle = float(rotation)
        if angle % 90:
            raise ValueError("仅自动处理直角旋转，请先导出标准竖版或横版视频")
        return int(angle) % 360
    except (TypeError, OverflowError):
        raise ValueError("视频旋转信息无效，请重新导出") from None


def intake_video(source, target):
    source, target = Path(source), Path(target)
    original = inspect_media(source, "video", max_bytes=MAX_VIDEO_SOURCE)
    stream = next(s for s in probe(source)["streams"] if s["codec_type"] == "video")
    rotation = rotation_of(stream)
    raw_sar = stream.get("sample_aspect_ratio", "1:1")
    try:
        sar = Fraction(raw_sar.replace(":", "/")) if raw_sar != "N/A" else Fraction(1)
        if not 0 < sar <= 100:
            raise ValueError("视频像素比例超出支持范围，请先导出方形像素视频")
    except (ValueError, ZeroDivisionError):
        raise ValueError("视频像素比例无效，请先导出方形像素视频") from None
    w, h = round(original["width"] * sar), original["height"]
    if rotation in (90, 270):
        w, h = h, w
    box = (1080, 1920) if h > w else (1920, 1080)
    dar = Fraction(original["width"], original["height"]) * sar
    if rotation in (90, 270):
        dar = 1 / dar
    if not Fraction(2, box[1]) <= dar <= Fraction(box[0], 2):
        raise ValueError("视频显示比例过于极端，无法在全高清尺寸内保持比例，请重新导出")
    transcode = bool(
        rotation
        or original["codec"] != "h264"
        or w > box[0]
        or h > box[1]
        or source.stat().st_size > MAX_UPLOAD
        or stream.get("pix_fmt") != "yuv420p"
        or stream.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A")
    )
    if target.exists() or source.resolve() == target.resolve():
        raise ValueError("工作副本已经存在，不允许覆盖")
    if not _transcode.acquire(blocking=False):
        raise Conflict("另一份视频正在预检，请完成后重试；本次没有替换已有素材")
    started = time.monotonic()
    try:
        if shutil.disk_usage(source.parent).free < source.stat().st_size + 2 * MAX_UPLOAD:
            raise ValueError("可用磁盘不足，请至少留出原件大小加200MiB空间")
        if transcode:
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-n",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    "-filter_threads",
                    "1",
                    *input_options(source),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-sn",
                    "-dn",
                    "-vf",
                    # DAR already reflects FFmpeg autorotation. Bounded square-pixel dimensions
                    # use long-supported expressions, including on FFmpeg before reset_sar.
                    f"scale=w='max(2,trunc(min({box[0]},min(iw*sar,{box[1]}*dar))/2)*2)':h='max(2,trunc(ow/dar/2)*2)',setsar=1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-threads",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                    "-fps_mode",
                    "passthrough",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-map_metadata",
                    "-1",
                    "-metadata:s:v:0",
                    "rotate=0",
                    "-movflags",
                    "+faststart",
                    "-fs",
                    str(MAX_UPLOAD + 1),
                    str(target),
                ],
                timeout=600,
            )
        else:
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    *input_options(source),
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-threads",
                    "2",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=600,
            )
            shutil.copyfile(source, target)
        working = inspect_media(target, "video")
        out = next(s for s in probe(target)["streams"] if s["codec_type"] == "video")
        if not (0 < working["width"] <= box[0] and 0 < working["height"] <= box[1]):
            raise ValueError("工作副本尺寸超出全高清边界，未采用，请重新导出")
        if rotation_of(out) or abs(working["duration"] - original["duration"]) > 0.1:
            raise ValueError("工作副本旋转或时长与原片不一致，未采用，请重新导出后上传")
        working["intake"] = {
            "version": VERSION,
            "transcoded": transcode,
            "original_sha256": digest(source),
            "original_bytes": source.stat().st_size,
            "original_codec": original["codec"],
            "coded_width": original["width"],
            "coded_height": original["height"],
            "original_rotation": rotation,
            "display_width": w,
            "display_height": h,
            "source_fps": stream.get("avg_frame_rate"),
            "source_sar": raw_sar,
            "decode_policy": "strict-xerror-explode",
            "working_profile": {
                "codec": "libx264",
                "crf": 18,
                "preset": "fast",
                "threads": 2,
                "bounds": list(box),
                "frame_timing": "passthrough",
                "audio": "aac-192k",
            }
            if transcode
            else {"mode": "byte_copy"},
            "working_sha256": digest(target),
            "working_bytes": target.stat().st_size,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "policy": "自动转正，等比缩至全高清以内，保留来源时间线；无裁切、补帧、慢放或动作推断",
            "human_review_required": True,
        }
        return working
    except RuntimeError as exc:
        target.unlink(missing_ok=True)
        raise ValueError(
            "视频解码或转码未通过，请重新导出标准H.264视频后上传；未采用损坏或超时副本"
        ) from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        _transcode.release()
