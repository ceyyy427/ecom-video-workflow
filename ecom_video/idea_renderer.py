"""Silent real MP4 previews, using the existing pinned Remotion/FFmpeg engine."""

import re
import shutil
import time
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import Field

from .content_plan import ADAPTERS, Datum
from .creative import CATALOG, Strict, signature
from .idea_media import check_materials, source_windows
from .media import digest, font_path, input_options, probe, run_checked, safe_path
from .remotion_renderer import ENGINE, engine_hash
from .renderer import write_json
from .shotcraft import MotionPlan, resolve_motion
from .visual_finish import prepare_visuals


class CodeVisual(Strict):
    kind: Literal[
        "swiss-motion", "blueprint", "dataviz", "paper-popup", "dark-keynote", "kino-montage"
    ]
    subject: str = Field(max_length=60)
    labels: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=3
    )
    data: list[Datum] = Field(default_factory=list, max_length=6)
    schematic: Literal[True] = True
    tone: str = Field(default="", max_length=120)


def engine_key():
    return signature(
        {
            "engine": engine_hash(),
            "plan": digest(Path(__file__).with_name("content_plan.py")),
            "renderer": digest(Path(__file__)),
            "source_checks": digest(Path(__file__).with_name("idea_media.py")),
        }
    )


def visual_spec(plan, option, scene):
    if option["diagram"] not in ADAPTERS:
        raise ValueError("未适配的代码图示")
    return CodeVisual(
        kind=option["diagram"],
        subject=plan["subject"],
        labels=[scene["text"]],
        data=plan["data"] if option["id"] == "dataviz" else [],
        tone=plan["brief"]["tone"],
    ).model_dump()


def visual_poster(path, spec):
    # A real static fallback for the asset library; rendering uses the structured diagram.
    image = Image.new("RGB", (1080, 1920), "#f5f2e9")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path()), 54)
    words = "\n".join(spec["labels"])
    lines = []
    for paragraph in words.splitlines():
        lines.extend(paragraph[i : i + 15] for i in range(0, len(paragraph), 15))
    draw.multiline_text((90, 620), "\n".join(lines), font=font, fill="#202923", spacing=32)
    draw.text((90, 1700), "代码图示 · 非实拍", font=font, fill="#557861")
    image.save(path)


def preview_props(plan, option, scene, seconds, index, src="", kind="image", windows=None):
    style = next(s for s in CATALOG if s["id"] == option["native_style"])
    paper, ink, accent = style["colors"]
    if option["id"] == "blueprint":
        paper, ink, accent = "#12394b", "#e2f4ff", "#6ec7eb"
    if option["id"] == "dark-keynote":
        paper, ink, accent = "#121919", "#fbf5e8", "#d5b681"
    props = {
        "frames": round(seconds * 30),
        "text": scene["text"],
        "headline": scene.get("headline", ""),
        "src": src,
        "kind": kind,
        "style": option["native_style"],
        "format": "narrated",
        "brand": option.get("brand")
        or {"name": "", "ink": ink, "paper": paper, "accent": accent, "subtitle_size": 52},
        "motion": "static",
        "fit": "contain",
        "focus_x": 0.5,
        "focus_y": 0.5,
        "sample": False,
        "preview": False,
        "words": [],
        "voiceStart": 0,
        "voiceEnd": seconds,
        "index": index + 1,
        "count": 2,
        "role": "product",
        "treatment": "auto",
        "transition": scene["transition"] if index else "cut",
        "exitTransition": "cut",
        "cleanPresentation": True,
        "shotRecipe": scene["recipe"],
    }
    motion = MotionPlan(
        intent="hook" if index == 0 else "detail",
        windows=windows or [],
        visual_finish="polished-v1",
        strength="subtle" if "克制" in plan["brief"]["tone"] else "balanced",
    ).model_dump()
    raw = {
        "text": scene["text"],
        "headline": props["headline"],
        "frames": props["frames"],
        "shot_recipe": scene["recipe"],
        "motion_plan": motion,
        "start": 0,
    }
    props["motionPlan"] = resolve_motion(raw, [])
    # A silent typographic preview has a scene clock, never forged ASR word timestamps.
    props["captions"] = [{"text": scene["text"], "start": 0, "end": seconds}]
    if not src:
        props["codeVisual"] = visual_spec(plan, option, scene)
        props["captions"] = []  # The entire sentence lives inside the diagram.
    if props.get("codeVisual"):
        props["headline"] = plan["subject"] if len(plan["subject"]) <= 8 else ""
    props.update(prepare_visuals(props))
    if props.get("codeVisual"):
        props["captions"] = []
    return props


def cached(root, record, basis, engine):
    if not record or record.get("basis") != basis or record.get("engine") != engine:
        return False
    try:
        for kind in ("video", "poster"):
            path = safe_path(root, record[kind]["path"])
            if not path.is_file() or digest(path) != record[kind]["sha256"]:
                return False
        return True
    except (ValueError, KeyError):
        return False


def render_option(plan, option, root, directory, check=lambda: None):
    if plan["engine"] != engine_key():
        raise ValueError("渲染引擎已更新，请重新生成六个方案；旧预览保留，不混用版本")
    check()
    check_materials(root, plan["materials"])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    public = directory / "public"
    out = directory / "clips"
    public.mkdir()
    out.mkdir()
    assets = {a["id"]: a for a in plan["materials"]}
    shots = []
    started = time.monotonic()
    ranges = []
    for index, (scene, seconds) in enumerate(
        zip(option["scenes"][:2], option["preview_scene_seconds"], strict=True)
    ):
        windows = []
        asset = assets.get(scene["material_id"])
        src = ""
        kind = "image"
        if asset:
            source = safe_path(root, asset["path"])
            kind = asset["kind"]
            src = f"source-{index}{source.suffix}"
            if kind == "image":
                shutil.copyfile(source, public / src)
            else:
                start = asset["source_in"]
                duration = asset["metadata"]["duration"]
                # Distinct consecutive ranges where possible; never loop or freeze.
                candidate = start + (option["preview_scene_seconds"][0] if index else 0)
                if candidate + seconds <= duration + 0.001:
                    start = candidate
                if start + seconds > duration + 0.001:
                    raise ValueError("实拍长度不足，不能靠循环或冻结凑预览")
                windows = source_windows(asset, start, seconds)
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        *input_options(source),
                        "-ss",
                        str(start),
                        "-i",
                        str(source),
                        "-t",
                        str(seconds),
                        "-map",
                        "0:v:0",
                        "-an",
                        "-vf",
                        "fps=30,setsar=1",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "fast",
                        "-crf",
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        "-threads",
                        "2",
                        str(public / src),
                    ],
                    check=check,
                )
                ranges.append(
                    {
                        "scene": scene["id"],
                        "asset_id": asset["id"],
                        "source_in": start,
                        "duration": seconds,
                        "sha256": asset["sha256"],
                    }
                )
        props = preview_props(plan, option, scene, seconds, index, src, kind, windows)
        shots.append({"key": f"scene-{index + 1}", "props": props})
    config = directory / "render.json"
    write_json(
        config, {"publicDir": str(public), "outputDir": str(out), "shots": shots, "mode": "preview"}
    )
    run_checked(["node", str(ENGINE / "render.mjs"), str(config)], check=check, timeout=900)
    video = join_preview_clips(directory, shots, check)
    poster = directory / "poster.png"
    shutil.copyfile(out / "scene-1.png", poster)
    info = probe(video)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    if int(stream.get("nb_frames", 0)) != 210 or abs(float(info["format"]["duration"]) - 7) > 0.06:
        raise ValueError("预览时长或帧数异常")
    run_checked(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], check=check)
    return {
        "basis": plan["basis"],
        "engine": plan["engine"],
        "seconds": 7,
        "width": stream["width"],
        "height": stream["height"],
        "silent": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "ranges": ranges,
        "video": {"path": video.relative_to(root).as_posix(), "sha256": digest(video)},
        "poster": {"path": poster.relative_to(root).as_posix(), "sha256": digest(poster)},
    }


def join_preview_clips(directory, shots, check=lambda: None):
    directory = Path(directory)
    if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", s["key"]) for s in shots):
        raise ValueError("预览片段标识不合法")
    # FFmpeg resolves relative paths against the list file, including quoted roots.
    concat = directory / "concat.txt"
    concat.write_text("\n".join(f"file 'clips/{s['key']}.mp4'" for s in shots))
    video = directory / "preview.mp4"
    run_checked(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=check,
    )
    return video
