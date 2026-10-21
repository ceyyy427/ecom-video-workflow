"""P4 edit-decision renderer. Only validated numeric choices reach FFmpeg."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .media import digest, font_path, input_options, inspect_media, probe, run_checked, safe_path
from .renderer import stamp, write_json
from .source_framing import crop_filter
from .storyboard import validate_board

STYLES = {
    "premium": ("质感展示", "#302a23", "#a77f4f"),
    "demo": ("细节演示", "#193a47", "#337485"),
    "lifestyle": ("日常场景", "#253d31", "#607453"),
}


def caption_lines(text, draw, font):
    lines, current = [], ""
    for ch in text:
        if current and draw.textlength(current + ch, font=font) > 864:
            # Chinese closing punctuation must travel with preceding characters.
            if ch in "，。！？；：、,.!?;:%）】”’" and len(current) > 2:
                lines.append(current[:-2])
                current = current[-2:] + ch
            else:
                lines.append(current)
                current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines


def overlay(text, path, style, index, count, sample=False):
    """Typeset real script only, without model-generated marketing claims."""
    im = Image.new("RGBA", (1080, 1920))
    d = ImageDraw.Draw(im)
    label, ink, accent = STYLES[style]
    font = ImageFont.truetype(str(font_path()), 64 if style == "premium" else 58)
    small = ImageFont.truetype(str(font_path()), 27)
    lines = caption_lines(text, d, font)
    if len(lines) > 5:
        raise ValueError("当前字幕超过五行，请拆分长句后重试")
    if style == "premium":
        d.rounded_rectangle((64, 112, 1016, 256 + len(lines) * 82), 24, fill=(249, 245, 237, 223))
        d.text((104, 150), f"{label}  /  {index:02d}", font=small, fill=accent)
        top = 218
    elif style == "demo":
        d.rounded_rectangle((64, 128, 400, 196), 14, fill=ink)
        d.text((88, 144), f"{label}  {index:02d}/{count:02d}", font=small, fill="white")
        top = 1480 - len(lines) * 78
        d.rounded_rectangle((64, top - 34, 1016, 1524), 20, fill=(246, 249, 249, 242))
        d.rectangle((64, top - 14, 74, 1498), fill=accent)
    else:
        d.rounded_rectangle((64, 128, 360, 192), 32, fill=(247, 246, 234, 230))
        d.text((92, 144), label, font=small, fill=ink)
        top = 1470 - len(lines) * 80
        d.rounded_rectangle((64, top - 32, 1016, 1520), 28, fill=(245, 244, 230, 240))
    for n, line in enumerate(lines):
        d.text((104, top + n * 80), line, font=font, fill=ink)
    for n in range(count):
        width = 864 / count
        d.rounded_rectangle(
            (104 + n * width, 1614, 104 + (n + 1) * width - 12, 1620),
            3,
            fill=accent if n < index else (255, 255, 255, 160),
        )
    if sample:
        d.rounded_rectangle((104, 1640, 750, 1698), 12, fill=(245, 242, 233, 230))
        d.text((120, 1654), "虚构商品 · AI 示例画面 · 非实拍", font=small, fill="#514c43")
    im.save(path)


def visual_filter(shot, is_image, frames):
    # First respect display aspect ratio, including anamorphic source video.
    base = "scale=w='max(2,trunc(iw*sar/2)*2)':h=ih,setsar=1,"
    if not is_image:
        base += crop_filter(shot)
    if shot["fit"] == "cover":
        base += (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920:(iw-1080)*{shot['focus_x']}:(ih-1920)*{shot['focus_y']},"
        )
    else:
        base += "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0xe9e5dc,"
    if is_image and shot["motion"] != "static":
        p = f"(on/{max(1, frames - 1)})"
        ease = f"({p}*{p}*(3-2*{p}))"
        z = {
            "push": f"1+0.12*{ease}",
            "pull": f"1.12-0.12*{ease}",
            "pan_left": "1.12",
            "pan_right": "1.12",
        }[shot["motion"]]
        x = f"(iw-iw/zoom)*{shot['focus_x']}"
        if shot["motion"] == "pan_left":
            x = f"(iw-iw/zoom)*(1-{ease})"
        if shot["motion"] == "pan_right":
            x = f"(iw-iw/zoom)*{ease}"
        base += f"scale=2160:3840,zoompan=z='{z}':x='{x}':y='(ih-ih/zoom)*{shot['focus_y']}':d=1:s=1080x1920:fps=30,"
    return base + "fps=30,setpts=PTS-STARTPTS"


def narration_track(board, scenes, assets, root, directory, check):
    voice = board["narration"]
    out = directory / "narration.wav"
    total = scenes[-1]["end"]
    if voice["mode"] == "local":
        for i, scene in enumerate(scenes):
            text = directory / f"voice-{i:03d}.txt"
            text.write_text(scene["text"], encoding="utf-8")
            aiff = directory / f"voice-{i:03d}.aiff"
            raw = directory / f"voice-{i:03d}-raw.wav"
            run_checked(
                [
                    "say",
                    "-v",
                    "Tingting",
                    "-r",
                    str(voice["rate"]),
                    "-f",
                    str(text),
                    "-o",
                    str(aiff),
                ],
                check,
            )
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(aiff),
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(raw),
                ],
                check,
            )
            duration = float(probe(raw)["format"]["duration"])
            if duration + 0.25 > scene["end"] - scene["start"]:
                raise ValueError(
                    f"第 {i + 1} 镜配音需至少 {duration + 0.25:.2f} 秒，请延长镜头或缩短脚本"
                )
            scene["voice_start"] = scene["start"] + 0.18
            scene["voice_end"] = scene["voice_start"] + duration
            segment = directory / f"voice-{i:03d}.wav"
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(raw),
                    "-af",
                    "highpass=f=80,loudnorm=I=-18:TP=-2:LRA=7,adelay=180|180,apad",
                    "-t",
                    str(scene["end"] - scene["start"]),
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    str(segment),
                ],
                check,
            )
        listing = directory / "voices.txt"
        listing.write_text("".join(f"file 'voice-{i:03d}.wav'\n" for i in range(len(scenes))))
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
                str(listing),
                "-c:a",
                "pcm_s16le",
                str(out),
            ],
            check,
        )
    elif voice["mode"] == "uploaded":
        source = safe_path(root, assets[voice["asset_id"]]["path"])
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                *input_options(source),
                "-i",
                str(source),
                "-af",
                "highpass=f=80,loudnorm=I=-18:TP=-2:LRA=7,apad",
                "-t",
                str(total),
                "-ar",
                "48000",
                "-ac",
                "2",
                str(out),
            ],
            check,
        )
    else:
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                str(total),
                str(out),
            ],
            check,
        )
    return out


def render_storyboard(job, root, directory, check):
    if job["snapshot"]["storyboard"].get("creative"):
        from .remotion_renderer import render_remotion

        return render_remotion(job, root, directory, check)
    root, directory = Path(root), Path(directory)
    snap = job["snapshot"]
    # Re-probe immutable files: pre-P4 metadata used container duration for video.
    inspected = [
        {**a, "metadata": inspect_media(safe_path(root, a["path"]), a["kind"])}
        for a in snap["assets"]
    ]
    board = validate_board({**snap, "assets": inspected}, snap["storyboard"])
    assets = {a["id"]: a for a in inspected}
    scenes = []
    position = 0
    for i, (text, shot) in enumerate(zip(snap["script"].splitlines(), board["shots"], strict=True)):
        frames = round(shot["duration"] * 30)
        scene = {
            **shot,
            "index": i + 1,
            "text": text,
            "frames": frames,
            "start": position / 30,
            "end": (position + frames) / 30,
            "asset_sha256": assets[shot["asset_id"]]["sha256"],
            "media_policy": "explicit_selection;original_audio_muted",
        }
        scenes.append(scene)
        position += frames
    voice = narration_track(board, scenes, assets, root, directory, check)
    for i, scene in enumerate(scenes):
        check()
        asset = assets[scene["asset_id"]]
        source = safe_path(root, asset["path"])
        cap = directory / f"caption-{i:03d}.png"
        overlay(scene["text"], cap, board["style"], i + 1, len(scenes), board["sample"])
        if asset["kind"] == "image":
            normalized = directory / f"source-{i:03d}.png"
            with Image.open(source) as im:
                ImageOps.exif_transpose(im).convert("RGB").save(normalized)
            inputs = ["-loop", "1", "-framerate", "30", "-i", str(normalized)]
        else:
            inputs = ["-ss", str(scene["source_in"]), *input_options(source), "-i", str(source)]
        filters = f"[0:v]{visual_filter(scene, asset['kind'] == 'image', scene['frames'])}[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        run_checked(
            [
                "ffmpeg",
                "-v",
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
                "20",
                "-threads",
                "2",
                str(directory / f"scene-{i:03d}.mp4"),
            ],
            check,
        )
        rendered = probe(directory / f"scene-{i:03d}.mp4")
        stream = next(s for s in rendered["streams"] if s["codec_type"] == "video")
        if int(stream.get("nb_frames", 0)) != scene["frames"]:
            raise ValueError(f"第 {i + 1} 镜画面帧数不足，请重新选段或导出素材")
    total = position / 30
    listing = directory / "concat.txt"
    listing.write_text("".join(f"file 'scene-{i:03d}.mp4'\n" for i in range(len(scenes))))
    base = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        str(listing),
        "-i",
        str(voice),
    ]
    output = directory / "output.mp4"
    ending = [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        str(total),
        "-movflags",
        "+faststart",
    ]
    gain = board["narration"]["gain_db"]
    run_checked(
        [
            *base,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-af",
            f"volume={gain}dB,alimiter=limit=0.95:level=false",
            *ending,
            str(directory / "voice-only.mp4" if board["music_id"] else output),
        ],
        check,
    )
    if board["music_id"]:
        music = safe_path(root, assets[board["music_id"]]["path"])
        # The same narration track drives the compressor and remains audible in the mix.
        graph = (
            f"[1:a]volume={gain}dB,asplit=2[vo][key];"
            f"[2:a]loudnorm=I=-18:TP=-2:LRA=7,volume={board['music_db'] + 18}dB,"
            f"afade=t=in:d=0.6,afade=t=out:st={max(0, total - 1)}:d=1[bed];"
            "[bed][key]sidechaincompress=threshold=0.025:ratio=6:attack=20:release=250[duck];"
            "[vo][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[a]"
        )
        run_checked(
            [
                *base,
                "-stream_loop",
                "-1",
                *input_options(music),
                "-i",
                str(music),
                "-filter_complex_threads",
                "1",
                "-filter_complex",
                graph,
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                *ending,
                str(output),
            ],
            check,
        )
    srt = (
        "\n\n".join(
            f"{s['index']}\n{stamp(s.get('voice_start', s['start']))} --> {stamp(s.get('voice_end', s['end']))}\n{s['text']}"
            for s in scenes
        )
        + "\n"
    )
    (directory / "subtitles.srt").write_text(srt, encoding="utf-8")
    write_json(
        directory / "manifest.json",
        {
            "schema_version": 3,
            "job_id": job["id"],
            "attempt": job["attempts"],
            "script": snap["script"],
            "script_hash": job["script_hash"],
            "title": snap["title"],
            "provenance": snap.get("provenance"),
            "storyboard": board,
            "storyboard_revision": snap["storyboard_revision"],
            "duration": total,
            "scenes": scenes,
            "assets": snap["assets"],
            "timing": "local_tts_measured_per_scene"
            if board["narration"]["mode"] == "local"
            else "explicit_scene_timeline",
            "subtitle_alignment_verified": False,
            "audio": board["narration"]["mode"],
            "music_ducked": bool(board["music_id"]),
            "narration_sha256": digest(voice),
            "render": {
                "engine": "ffmpeg",
                "size": [1080, 1920],
                "fps": 30,
                "caption_font": str(font_path()),
            },
        },
    )
    return output, total
