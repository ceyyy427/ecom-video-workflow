"""Deterministic shot assembly with inspectable captions and timeline evidence."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .media import digest, font_path, input_options, probe, run_checked, safe_path


def timeline(script, seconds, audio_duration=None):
    lines = [x.strip() for x in script.splitlines() if x.strip()]
    total = float(audio_duration if audio_duration is not None else len(lines) * seconds)
    if not lines or total > 120 or total < len(lines):
        raise ValueError("配音/成片时长须在镜头数至 120 秒之间，保证每镜至少 1 秒")
    # Allocate integer video frames, avoiding accumulated rounding at 30 fps.
    frames = round(total * 30)
    reserve = len(lines) * 30
    weights = [len(x) for x in lines]
    available = frames - reserve
    cumulative, position, scenes = 0, 0, []
    for i, line in enumerate(lines):
        cumulative += weights[i]
        end = (
            (i + 1) * 30 + round(available * cumulative / sum(weights))
            if audio_duration is not None
            else round((i + 1) * seconds * 30)
        )
        scenes.append(
            {
                "index": i + 1,
                "text": line,
                "start": position / 30,
                "end": end / 30,
                "frames": end - position,
            }
        )
        position = end
    return scenes


def stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def caption(text, path):
    canvas = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path()), 52)
    lines, current = [], ""
    for char in text:
        if current and draw.textlength(current + char, font=font) > 900:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    if len(lines) > 7:
        raise ValueError("字幕超过安全区域，请将长句拆成更多镜头")
    height = len(lines) * 72 + 48
    top = 1570 - height
    draw.rounded_rectangle((58, top, 1022, 1570), radius=20, fill=(13, 25, 42, 220))
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text(
            ((1080 - width) / 2, top + 24 + i * 72), line, font=font, fill="white", stroke_width=1
        )
    canvas.save(path)


def render(job, root, directory, check):
    root, directory = Path(root), Path(directory)
    snap = job["snapshot"]
    if snap.get("storyboard"):
        from .storyboard_renderer import render_storyboard

        return render_storyboard(job, root, directory, check)
    assets = snap["assets"]
    visual = [a for a in assets if a["kind"] != "audio"]
    audio = next((a for a in assets if a["kind"] == "audio"), None)
    metadata = json.loads(audio["metadata"]) if audio else None
    scenes = timeline(snap["script"], snap["seconds"], metadata["duration"] if audio else None)
    for i, scene in enumerate(scenes):
        check()
        asset = visual[i % len(visual)]
        source = safe_path(root, asset["path"])
        cap = directory / f"caption-{i:03d}.png"
        caption(scene["text"], cap)
        if asset["kind"] == "image":
            # Normalize orientation and decode untrusted stills before handing them to FFmpeg.
            normalized = directory / f"source-{i:03d}.png"
            with Image.open(source) as im:
                ImageOps.exif_transpose(im).convert("RGB").save(normalized)
            inputs = ["-loop", "1", "-framerate", "30", "-i", str(normalized)]
        else:
            inputs = ["-stream_loop", "-1", *input_options(source), "-i", str(source)]
        out = directory / f"scene-{i:03d}.mp4"
        filters = "[0:v]scale=w='max(2,trunc(min(1080,1920*dar)/2)*2)':h='max(2,trunc(min(1920,1080/dar)/2)*2)',setsar=1,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x152339,fps=30[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        run_checked(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *inputs,
                "-i",
                str(cap),
                "-filter_complex_threads",
                "1",
                "-filter_complex",
                filters,
                "-map",
                "[v]",
                "-frames:v",
                str(scene["frames"]),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-threads",
                "2",
                str(out),
            ],
            check,
        )
        scene["asset_id"] = asset["id"]
        scene["asset_sha256"] = asset["sha256"]
        scene["media_policy"] = "fit_with_padding; loop_or_trim; original_audio_muted"
    concat = directory / "concat.txt"
    concat.write_text("".join(f"file 'scene-{i:03d}.mp4'\n" for i in range(len(scenes))))
    total = scenes[-1]["end"]
    voice = (
        [*input_options(safe_path(root, audio["path"])), "-i", str(safe_path(root, audio["path"]))]
        if audio
        else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    )
    output = directory / "output.mp4"
    run_checked(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            *voice,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-af",
            "apad",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            str(total),
            "-movflags",
            "+faststart",
            str(output),
        ],
        check,
    )
    subtitles = (
        "\n\n".join(
            f"{s['index']}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for s in scenes
        )
        + "\n"
    )
    (directory / "subtitles.srt").write_text(subtitles, encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "provenance": job["snapshot"].get("provenance"),
        "job_id": job["id"],
        "attempt": job["attempts"],
        "script": snap["script"],
        "script_hash": job["script_hash"],
        "title": snap["title"],
        "timing": "estimated_by_text_weight" if audio else "fixed_scene_duration",
        "subtitle_alignment_verified": False,
        "audio": "uploaded_narration" if audio else "silent",
        "scenes": scenes,
        "assets": assets,
        "duration": total,
        "render": {
            "engine": "ffmpeg",
            "size": [1080, 1920],
            "fps": 30,
            "caption_font": str(font_path()),
        },
    }
    write_json(directory / "manifest.json", manifest)
    return output, total


def verify_output(path, expected_duration, check):
    data = probe(path)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
    duration = float(data["format"].get("duration", 0))
    result = {
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "duration": duration,
        "video_duration": float(video.get("duration", 0)),
        "video_frames": int(video.get("nb_frames", 0)),
        "expected_duration": expected_duration,
        "frame_rate": video.get("avg_frame_rate"),
        "visual_quality_reviewed": False,
        "subtitle_alignment_verified": False,
    }
    valid = (
        result["width"] == 1080
        and result["height"] == 1920
        and result["video_codec"] == "h264"
        and result["audio_codec"] == "aac"
        and abs(result["video_duration"] - expected_duration) <= 1 / 30 + 0.001
        and result["video_frames"] == round(expected_duration * 30)
        and abs(duration - expected_duration) < 0.25
        and result["frame_rate"] == "30/1"
    )
    if not valid:
        raise ValueError("成片编码、尺寸或时长检查未通过")
    run_checked(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            *input_options(path),
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ],
        check,
    )
    result["full_decode_passed"] = True
    result["passed"] = True
    return result


def artifact(root, path, kind):
    return {
        "kind": kind,
        "path": str(Path(path).relative_to(root)),
        "sha256": digest(path),
        "size": Path(path).stat().st_size,
    }
