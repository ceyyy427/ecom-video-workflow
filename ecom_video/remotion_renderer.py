"""Remotion scene rendering with content-addressed clips and one whole-film audio pass."""

import json
import math
import shutil
import wave
from pathlib import Path

from PIL import Image, ImageOps

from .creative import CATALOG, signature
from .delivery_plan import meta as asset_metadata
from .media import digest, font_path, input_options, inspect_media, probe, run_checked, safe_path
from .motion_treatment import review_sheet
from .renderer import stamp, write_json
from .shotcraft import effective_transitions, recipe_record, resolve_motion
from .source_framing import crop_filter, media_suffix
from .storyboard import validate_board
from .storyboard_renderer import narration_track
from .visual_finish import caption_record, prepare_visuals

PROJECT = Path(__file__).resolve().parent.parent
ENGINE = PROJECT / "render/remotion"


def frame_local_time(at, start):
    # JSON distinguishes -0.0 from 0.0, but a frame-local zero is the same time.
    return round(at - start, 4) or 0.0


def engine_hash():
    return signature(
        {
            str(p): digest(p)
            for p in [
                *sorted((ENGINE / "src").glob("*.tsx")),
                ENGINE / "render.mjs",
                ENGINE / "src/cleanup.mjs",
                ENGINE / "src/pause-pages.cjs",
                ENGINE / "package-lock.json",
                font_path(),
                PROJECT / "ecom_video/captions.py",
                PROJECT / "ecom_video/subtitle_layout.py",
                PROJECT / "ecom_video/visual_finish.py",
                PROJECT / "ecom_video/motion_treatment.py",
                PROJECT / "ecom_video/shotcraft.py",
                PROJECT / "ecom_video/source_framing.py",
                PROJECT / "ecom_video/prompt_catalog.py",
                PROJECT / "ecom_video/semantic_mix.py",
                PROJECT / "ecom_video/delivery_plan.py",
                PROJECT / "ecom_video/delivery_timeline.py",
                Path(__file__),
            ]
        }
    )


def prepare_source_video(source, target, scene, check):
    run_checked(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(scene["source_in"]),
            *input_options(source),
            "-i",
            str(source),
            "-an",
            "-vf",
            crop_filter(scene)
            + "fps=30,scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-frames:v",
            str(scene["frames"]),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            str(target),
        ],
        check,
    )


def prepare_cut_video(root, target, scene, assets, check):
    """Use FFmpeg's trim/setpts/concat; bounded, silent footage, no source looping."""
    parts = []
    for i, cut in enumerate(scene["source_cuts"]):
        check()
        asset = assets[cut["asset_id"]]
        source = safe_path(root, asset["path"])
        if digest(source) != asset["sha256"]:
            raise ValueError("分段素材内容变化，请重新准备")
        part = target.with_name(target.stem + f"-part-{i}.mp4")
        frames = round(cut["duration"] * 30)
        speed = cut["source_duration"] / cut["duration"]
        vf = (f"trim=duration={cut['source_duration']},setpts=(PTS-STARTPTS)/{speed},"
              + crop_filter(scene)
              + "scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,"
              + "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,")
        # Up to one final frame for sample/frame-grid rounding, never action-length padding.
        vf += "tpad=stop_mode=clone:stop_duration=0.034"
        run_checked(["ffmpeg", "-v", "error", "-y", "-ss", str(cut["source_in"]),
                     *input_options(source), "-i", str(source), "-an", "-vf", vf,
                     "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
                     "-threads", "2", "-pix_fmt", "yuv420p", str(part)], check)
        stream = next(s for s in probe(part)["streams"] if s["codec_type"] == "video")
        if int(stream.get("nb_frames", 0)) != frames:
            raise ValueError("实拍分段解码帧数不足；未循环或长冻结填充")
        parts.append(part)
    listing = target.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    run_checked(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i",
                 str(listing), "-c", "copy", str(target)], check)


def render_remotion(job, root, directory, check):
    root, directory = Path(root), Path(directory)
    snap = job["snapshot"]
    assets = {
        a["id"]: {**a, "metadata": {**asset_metadata(a), **inspect_media(safe_path(root, a["path"]), a["kind"])}}
        for a in snap["assets"]
    }
    board = validate_board({**snap, "assets": list(assets.values())}, snap["storyboard"])
    creative = board["creative"]
    style = next(s for s in CATALOG if s["id"] == creative["style_id"])
    if not (ENGINE / "node_modules/remotion").is_dir():
        raise ValueError("Remotion 依赖未安装，请运行 npm ci --prefix render/remotion")
    public = directory / "public"
    public.mkdir(exist_ok=True)
    cache = root / "cache/remotion"
    cache.mkdir(parents=True, exist_ok=True)
    scenes = []
    position = 0
    for i, (line, shot) in enumerate(zip(snap["script"].splitlines(), board["shots"], strict=True)):
        frames = round(shot["duration"] * 30)
        scenes.append(
            {
                **shot,
                "index": i + 1,
                "text": line,
                "frames": frames,
                "start": position / 30,
                "end": (position + frames) / 30,
            }
        )
        position += frames
    voice = narration_track(board, scenes, assets, root, directory, check)
    alignment = snap.get("alignment")
    transitions = effective_transitions(scenes)
    pending = []
    hits = 0
    engine = engine_hash()
    for i, scene in enumerate(scenes):
        check()
        asset = assets[scene["asset_id"]]
        source = safe_path(root, asset["path"])
        words = []
        if alignment:
            sentence = alignment["sentences"][i]
            words = [
                {
                    **w,
                    "start": frame_local_time(w["start"], scene["start"]),
                    "end": frame_local_time(w["end"], scene["start"]),
                }
                for w in sentence["words"]
            ]
            scene["voice_start"] = sentence["start"]
            scene["voice_end"] = sentence["end"]
        src = asset["sha256"] + (
            ".png"
            if asset["kind"] == "image"
            else f"-{scene['source_in']}-{scene['frames']}{media_suffix(scene)}.mp4"
        )
        if scene.get("source_cuts"):
            from .delivery_timeline import cut_records

            record = cut_records(scene, assets)
            src = signature({"cuts": [{k: v for k, v in c.items() if k not in ("asset_id", "source_name", "reason")}
                                      for c in record], "framing": media_suffix(scene)}) + ".mp4"
        props = {
            k: scene[k]
            for k in [
                "frames",
                "text",
                "motion",
                "fit",
                "focus_x",
                "focus_y",
                "index",
                "role",
                "treatment",
                "transition",
            ]
        }
        props.update(
            src=src,
            kind=asset["kind"],
            headline=scene["headline"],
            style=creative["style_id"],
            format=creative["brief"].get("format", "auto"),
            brand=creative["brand"],
            sample=board["sample"],
            preview=snap.get("preview_only") is True,
            words=words,
            voiceStart=frame_local_time(scene.get("voice_start", scene["start"]), scene["start"]),
            voiceEnd=frame_local_time(scene.get("voice_end", scene["end"]), scene["start"]),
            count=len(scenes),
            transition=transitions[i],
            exitTransition=transitions[i + 1] if i + 1 < len(scenes) else "cut",
        )
        if scene.get("caption_note"):
            props["captionNote"] = scene["caption_note"]
        if board.get("delivery"):
            props["captionPolicy"] = board["delivery"]["caption_policy"]
        if scene.get("shot_recipe") is not None:
            props["shotRecipe"] = scene["shot_recipe"]
        decision = resolve_motion(scene, words)
        from .creative import fingerprint
        from .semantic_mix import guard_decision, strategy

        mixed = creative["fingerprint"] == fingerprint(snap, creative["brief"], policy=5)
        if mixed or scene.get("shot_recipe") == "product-fact-row":
            guarded = guard_decision(
                snap, i, decision or {"recipe": "none", "guard_outcome": "no_motion"}
            )
            if decision is not None:
                decision = guarded
            if guarded.get("suppress_headline"):
                scene["requested_headline"] = scene["headline"]
                scene["headline"] = props["headline"] = ""
        if (
            mixed
            or scene.get("shot_recipe") in ("product-detail-bracket", "product-fact-row")
            or scene["transition"] == "media-pass"
        ):
            scene["content_strategy"] = strategy(snap, i, asset)
        if decision:
            from .prompt_catalog import MEDIA_RECIPES, usable_media

            if decision["recipe"] in MEDIA_RECIPES and not usable_media(asset):
                decision.update(recipe="none", guard_outcome="insufficient_media_resolution")
        if decision is not None:
            props.update(motionPlan=decision, shotRecipe=decision["recipe"])
            scene["motion_decision"] = decision
        scene["effective_transition"] = transitions[i]
        props.update(prepare_visuals(props))
        if props.get("titleLayout"):
            scene["visual_finish"] = {
                "version": "polished-v1",
                "title": {k: v for k, v in props["titleLayout"].items() if k != "image"},
                "caption_above_transitions": True,
            }
        key = signature({"engine": engine, "props": props, "source_sha256": asset["sha256"]})
        scene.update(
            cache_key=key,
            recipe=style["recipe"],
            asset_sha256=asset["sha256"],
            word_anchors=words,
            caption_layout=[caption_record(c) for c in props["captions"]],
            layers=["product_media", "brand_title", "plain_phrase_subtitles", "progress"],
            source_policy="user supplied; original video audio muted",
        )
        if scene.get("shot_recipe") is not None:
            scene["motion_recipe"] = recipe_record(
                scene["shot_recipe"],
                scene["text"],
                scene["headline"],
                creative["style_id"],
                (decision or {}).get("prompt_card"),
            )
            if decision is not None:
                scene["motion_recipe"]["applied"] = recipe_record(
                    decision["recipe"],
                    scene["text"],
                    scene["headline"],
                    creative["style_id"],
                    decision.get("prompt_card"),
                )
        if decision and decision.get("prompt_card"):
            from .prompt_catalog import evidence_for

            scene["prompt_match"] = evidence_for(decision["prompt_card"], snap, creative["brief"])
            scene["prompt_match"]["applied_recipe"] = decision["recipe"]
            scene["prompt_match"]["guard_outcome"] = decision["guard_outcome"]
        valid = False
        if (cache / (key + ".mp4")).is_file() and (cache / (key + ".json")).is_file():
            meta = json.loads((cache / (key + ".json")).read_text())
            valid = meta.get("sha256") == digest(cache / (key + ".mp4"))
        if valid:
            hits += 1
        else:
            target = public / src
            if not target.exists():
                if asset["kind"] == "image":
                    with Image.open(source) as im:
                        ImageOps.exif_transpose(im).convert("RGB").save(target)
                else:
                    if scene.get("source_cuts"):
                        prepare_cut_video(root, target, scene, assets, check)
                    else:
                        prepare_source_video(source, target, scene, check)
            pending.append({"key": key, "props": props})
        scene["cache_hit"] = valid
    # Unique keys: a repeated shot should only render once.
    pending = list({s["key"]: s for s in pending}.values())
    if pending:
        config = {
            "publicDir": str(public.resolve()),
            "outputDir": str(directory.resolve()),
            "shots": pending,
        }
        write_json(directory / "render-input.json", config)
        run_checked(
            ["node", str(ENGINE / "render.mjs"), str((directory / "render-input.json").resolve())],
            check,
        )
        for item in pending:
            key = item["key"]
            source = directory / (key + ".mp4")
            stream = next(s for s in probe(source)["streams"] if s["codec_type"] == "video")
            if int(stream.get("nb_frames", 0)) != item["props"]["frames"]:
                raise ValueError("Remotion 镜头帧数不足")
            shutil.copyfile(source, cache / (key + ".mp4"))
            shutil.copyfile(directory / (key + ".png"), cache / (key + ".png"))
            write_json(cache / (key + ".json"), {"sha256": digest(source), "engine": engine})
    for i, scene in enumerate(scenes):
        shutil.copyfile(cache / (scene["cache_key"] + ".mp4"), directory / f"scene-{i:03d}.mp4")
    total = position / 30
    (directory / "concat.txt").write_text(
        "".join(f"file 'scene-{i:03d}.mp4'\n" for i in range(len(scenes)))
    )
    # Optional original soft Foley cues, anchored to each first spoken word. No random/noise layer.
    import numpy as np

    sample_rate = 48000
    fx = np.zeros(round(total * sample_rate), dtype=np.float32)
    cues = []
    if creative["sfx"]:
        for s in scenes:
            at = s.get("voice_start", s["start"])
            if at == 0:
                at = 0.15
            t = np.arange(int(0.12 * sample_rate)) / sample_rate
            sound = (
                0.035
                * np.sin(2 * math.pi * (420 * t + 220 * t * t))
                * np.exp(-45 * t)
                * np.minimum(1, t / 0.008)
            )
            offset = round(at * sample_rate)
            length = min(len(sound), len(fx) - offset)
            fx[offset : offset + length] += sound[:length]
            cues.append({"at": at, "kind": "original_soft_tick", "gain_peak": 0.035})
    if creative["sfx"] and creative["style_id"] in ("cinema", "social", "lab"):
        from .production_audio import make_cues

        fx, cues = make_cues(scenes, creative["style_id"], total, directory, check)
    with wave.open(str(directory / "sfx.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((fx * 32767).astype("<i2").tobytes())
    inputs = ["-i", str(voice), "-i", str(directory / "sfx.wav")]
    gain = board["narration"]["gain_db"]
    graph = (
        f"[0:a]volume={gain}dB[voice];[voice][1:a]amix=inputs=2:duration=first:normalize=0[clean]"
    )
    run_checked(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[clean]",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(directory / "clean.wav"),
        ],
        check,
    )
    mixed = directory / "clean.wav"
    if board["music_id"]:
        music = safe_path(root, assets[board["music_id"]]["path"])
        mixed = directory / "mixed.wav"
        graph = f"[0:a]asplit=2[vo][key];[1:a]loudnorm=I=-18:TP=-2:LRA=7,volume={board['music_db'] + 18}dB,afade=t=in:d=0.6,afade=t=out:st={max(0, total - 1)}:d=1[bed];[bed][key]sidechaincompress=threshold=0.025:ratio=6:attack=20:release=250[duck];[vo][duck]amix=inputs=2:duration=first:normalize=0[a]"
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(directory / "clean.wav"),
                "-stream_loop",
                "-1",
                *input_options(music),
                "-i",
                str(music),
                "-filter_complex",
                graph,
                "-map",
                "[a]",
                "-t",
                str(total),
                str(mixed),
            ],
            check,
        )
    # Two-pass loudness, preserving the single full narration timeline (no AAC priming per cut).
    import re
    import subprocess

    def mux(audio, output):
        target = (
            -23
            if board["narration"]["mode"] == "silent" and audio == directory / "clean.wav"
            else -16
        )
        measured = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(audio),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        check()
        match = re.findall(r"\{[^{}]+\}", measured.stderr)
        metrics = json.loads(match[-1]) if match else {}
        if metrics.get("input_i") not in (None, "-inf"):
            filt = f"loudnorm=I={target}:TP=-1.5:LRA=7:linear=true:" + ":".join(
                f"{a}={metrics[b]}"
                for a, b in [
                    ("measured_I", "input_i"),
                    ("measured_TP", "input_tp"),
                    ("measured_LRA", "input_lra"),
                    ("measured_thresh", "input_thresh"),
                    ("offset", "target_offset"),
                ]
            )
        else:
            filt = "anull"
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
                str(directory / "concat.txt"),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-af",
                filt,
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
                str(output),
            ],
            check,
        )
        return metrics

    loudness = mux(mixed, directory / "output.mp4")
    if board["music_id"]:
        mux(directory / "clean.wav", directory / "voice-only.mp4")
    subtitle_rows = [
        {"text": c["text"], "start": s["start"] + c["start"], "end": s["start"] + c["end"]}
        for s in scenes for c in s.get("caption_layout", [])
    ] if board.get("delivery") else [
        {"text": s["text"], "start": s.get("voice_start", s["start"]),
         "end": s.get("voice_end", s["end"])} for s in scenes
    ]
    (directory / "subtitles.srt").write_text(
        "\n\n".join(
            f"{i + 1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}"
            for i, s in enumerate(subtitle_rows)
        )
        + "\n"
    )
    manifest = {
        "schema_version": 4,
        "motion_treatment": review_sheet(scenes, creative["style_id"]),
        "job_id": job["id"],
        "script": snap["script"],
        "title": snap["title"],
        "provenance": snap.get("provenance"),
        "storyboard": board,
        "scenes": scenes,
        "duration": total,
        "render": {
            "engine": "remotion",
            "version": "4.0.519",
            "engine_hash": engine,
            "fps": 30,
            "size": [1080, 1920],
        },
        "cache": {"hits": hits, "rendered": len(pending), "total": len(scenes)},
        "alignment": alignment,
        "subtitle_alignment_verified": False,
        "audio": {
            "two_pass_normalization": loudness,
            "sfx_cues": cues,
            "music_ducked": bool(board["music_id"]),
        },
        "style_source": style,
        "assets": snap["assets"],
    }
    if board.get("delivery"):
        from .delivery_timeline import timeline_record

        manifest["delivery_timeline"] = timeline_record(snap, board, scenes, alignment)
    write_json(directory / "manifest.json", manifest)
    write_json(
        directory / "shotbook.json",
        {
            **({"clock": manifest["delivery_timeline"], "delivery_reviews": snap.get("delivery_reviews")}
               if board.get("delivery") else {}),
            "style": style,
            "motion_treatment": manifest["motion_treatment"],
            "brand": creative["brand"],
            "script_source": snap.get("provenance"),
            "shots": scenes,
            "audio_cues": cues,
            "alignment": alignment,
            "missing_assets": [],
            "approval": "final film still requires human review",
        },
    )
    return directory / "output.mp4", total


def style_previews(job, root, recommendations):
    """Actual Remotion styleframes, using only a supplied product asset."""
    asset = next((a for a in job["assets"] if a["kind"] != "audio"), None)
    if not asset:
        raise ValueError("请先上传商品画面，再预览风格")
    source = safe_path(root, asset["path"])
    if digest(source) != asset["sha256"]:
        raise ValueError("素材内容已变化，请重新上传")
    key = signature({"input": recommendations["fingerprint"], "engine": engine_hash()})
    folder = Path(root) / "previews" / job["id"] / key
    folder.mkdir(parents=True, exist_ok=True)
    public = folder / "public"
    public.mkdir(exist_ok=True)
    target = public / "source.png"
    if not target.exists():
        if asset["kind"] == "image":
            with Image.open(source) as im:
                ImageOps.exif_transpose(im).convert("RGB").save(target)
        else:
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    *input_options(source),
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    str(target),
                ]
            )
    shots = []
    for style in recommendations["options"]:
        name = style["id"]
        if (folder / (name + ".png")).exists():
            continue
        props = {
            "src": "source.png",
            "kind": "image",
            "frames": 150,
            "text": job["script"].splitlines()[0],
            "headline": job["script"].splitlines()[0][:8],
            "style": name,
            "format": recommendations["brief"].get("format", "auto"),
            "treatment": "hero",
            "transition": "cut",
            "brand": {
                "name": job["title"][:24],
                "paper": style["colors"][0],
                "ink": style["colors"][1],
                "accent": style["colors"][2],
                "subtitle_size": 60,
            },
            "motion": "push",
            "fit": "contain",
            "focus_x": 0.5,
            "focus_y": 0.5,
            "sample": bool((job.get("storyboard") or {}).get("sample")),
            "words": [],
            "voiceStart": 0,
            "voiceEnd": 5,
            "index": 1,
            "count": len(job["script"].splitlines()),
            "role": "product",
        }
        if style.get("motion"):
            from .prompt_catalog import usable_media

            candidate = (style.get("prompt_direction") or {}).get("cards", [None])[0]
            prompt = candidate if candidate and usable_media(asset) else None
            props["shotRecipe"] = prompt["recipe"] if prompt else style["motion"]["recipes"][0]
            from .shotcraft import MotionPlan

            decision = resolve_motion(
                {
                    "frames": 150,
                    "text": props["text"],
                    "headline": props["headline"],
                    "shot_recipe": props["shotRecipe"],
                    "motion_plan": MotionPlan(
                        intent="hook",
                        visual_finish="polished-v1",
                        prompt_card=prompt["id"] if prompt else None,
                    ).model_dump(),
                },
                [],
            )
            props.update(motionPlan=decision, shotRecipe=decision["recipe"])
        props.update(prepare_visuals(props))
        shots.append({"key": name, "props": props})
    if shots:
        write_json(
            folder / "input.json",
            {
                "mode": "still",
                "publicDir": str(public.resolve()),
                "outputDir": str(folder.resolve()),
                "shots": shots,
            },
        )
        run_checked(
            ["node", str(ENGINE / "render.mjs"), str((folder / "input.json").resolve())],
            timeout=180,
        )
    return {
        s["id"]: f"/api/jobs/{job['id']}/creative/previews/{key}/{s['id']}"
        for s in recommendations["options"]
    }
