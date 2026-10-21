"""Three real-footage, unapproved client discussion previews. Never writes business DB/reviews."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.creative import Brief, recommend, signature  # noqa: E402
from ecom_video.local_asr import align, transcribe  # noqa: E402
from ecom_video.media import digest, inspect_media  # noqa: E402
from ecom_video.remotion_renderer import render_remotion  # noqa: E402
from ecom_video.storyboard import default_board  # noqa: E402
from ecom_video.voice_profiles import PROFILES as CLOUD_PROFILES  # noqa: E402
from ecom_video.volc_voice import read_config, synthesize  # noqa: E402

OUT = ROOT / "examples/client-demo"
WORK = OUT / "work"
SOURCES = {
    "pour": ROOT / "examples/p9-real/originals/6177761.mp4",
    "cup": OUT / "sources/6177758.mp4",
    "desk": OUT / "sources/6177756.mp4",
}
SPECS = [
    {
        "style": "cinema",
        "title": "一杯的空白",
        "description": "克制展示＋配音 · 动作开场、全幅近景、宋体短标题与留白",
        "hook": "忙了一天，先给自己倒一杯。",
        "lines": [
            "忙了一天，先给自己倒一杯。",
            "咖啡落下，深浅都看得见。",
            "一只透明杯，把日常留在眼前。",
            "拿起它，给思绪一点空白。",
            "不必摆满，让桌边简单一点。",
            "喜欢这样的日常，再靠近看一看。",
        ],
        "headlines": ["倒一杯", "看得见", "透明杯", "一点空白", "简单一点", "靠近看一看"],
        "durations": [4, 3.8, 4.4, 3.8, 4.8, 5.2],
        "clips": [
            ("pour", 1, [500, 500, 110, 780]),
            ("pour", 4.7, [600, 600, 70, 680]),
            ("cup", 0.2, [760, 760, 160, 1050]),
            ("cup", 8, [880, 880, 90, 940]),
            ("desk", 0.2, [1080, 1080, 0, 720]),
            ("desk", 2.8, [1080, 1080, 0, 720]),
        ],
    },
    {
        "style": "social",
        "title": "把日常接上",
        "description": "生活种草 · 日常打断、暖色大字、拿杯与工作动作接力",
        "hook": "屏幕先等等，先喝一口。",
        "lines": [
            "屏幕先等等，先喝一口。",
            "电脑还开着，咖啡先倒好。",
            "透明杯里，能看见咖啡的深浅。",
            "一只杯子，放进正在过的日常。",
            "拿起喝一口，再继续手上的事。",
            "杯子放回桌边，日常就接上了。",
            "你喜欢的桌面，也有这样一杯吗？",
        ],
        "headlines": [
            "屏幕先等等",
            "咖啡先倒好",
            "咖啡的深浅",
            "正在过的日常",
            "拿起喝一口",
            "日常就接上了",
            "这样一杯",
        ],
        "durations": [3.5, 3.5, 4, 4, 4, 4, 4],
        "clips": [
            ("cup", 0.2, [760, 760, 150, 1050]),
            ("pour", 1.2, [600, 600, 70, 680]),
            ("pour", 4.4, [500, 500, 110, 780]),
            ("desk", 0, [1080, 1080, 0, 720]),
            ("cup", 8.2, [900, 900, 90, 930]),
            ("cup", 2.4, [760, 760, 150, 1050]),
            ("desk", 4, [1080, 1080, 0, 720]),
        ],
    },
    {
        "style": "lab",
        "title": "先把外观看清",
        "description": "细节解说 · 杯口、杯壁、倒入与手持，分章观察，不冒充性能测评",
        "hook": "选杯子，先别只看一张图。",
        "lines": [
            "选杯子，先别只看一张图。",
            "先看杯口，沿着边缘看一圈。",
            "再看杯壁，透明轮廓一眼能见。",
            "倒入咖啡，看看它装满后的样子。",
            "拿起，放下，观察实际的使用动作。",
            "最后拉远，看看它和桌面的搭配。",
            "外观看清楚，再按商品说明挑选。",
        ],
        "headlines": [
            "别只看一张图",
            "先看杯口",
            "再看杯壁",
            "倒入咖啡",
            "拿起",
            "和桌面的搭配",
            "外观看清楚",
        ],
        "durations": [3.5, 3.8, 3.8, 4.2, 4.3, 4.2, 4.2],
        "clips": [
            ("cup", 0, [760, 760, 150, 1050]),
            ("cup", 2.1, [600, 600, 220, 1140]),
            ("cup", 4, [700, 700, 180, 1100]),
            ("pour", 2.6, [500, 500, 110, 780]),
            ("cup", 8, [880, 880, 100, 960]),
            ("desk", 0, [1080, 1080, 0, 720]),
            ("desk", 3.8, [1080, 1080, 0, 720]),
        ],
    },
]

# Brief action passages stay on the product rather than following it off-screen.
# Each tuple is (source, source_in, on-screen seconds, crop [w,h,x,y]).
SPECS[0]["montages"] = {
    3: [("cup", 7.4, 1, [880, 880, 90, 940]), ("cup", 0.2, 2.8, [760, 760, 160, 1050])]
}
SPECS[1]["montages"] = {
    4: [("cup", 7.1, 1.4, [900, 900, 90, 930]), ("desk", 0.7, 2.6, [1080, 1080, 0, 720])]
}
SPECS[2]["montages"] = {
    4: [
        ("cup", 7.5, 1, [880, 880, 100, 960]),
        ("cup", 0.2, 1.6, [760, 760, 150, 1050]),
        ("desk", 0.5, 1.7, [1080, 1080, 0, 720]),
    ]
}


def command(args):
    subprocess.run(args, check=True, timeout=240)


def asset(path, kind, role=""):
    return {
        "id": signature(str(path))[:32],
        "name": path.name,
        "path": str(path.relative_to(WORK)),
        "kind": kind,
        "sha256": digest(path),
        "size": path.stat().st_size,
        "metadata": inspect_media(path, kind) | {"customer_role": role},
    }


def music(path, total, style):
    rate = 48000
    t = np.arange(round(total * rate)) / rate
    track = np.zeros_like(t)
    # Original deterministic electric-key pattern and soft percussion; no stock music resale.
    notes = {
        "cinema": [130.81, 196, 164.81, 246.94],
        "social": [174.61, 220, 261.63, 329.63],
        "lab": [146.83, 220, 185, 293.66],
    }[style]
    step = {"cinema": 0.8, "social": 0.45, "lab": 0.6}[style]
    for i, at in enumerate(np.arange(0, total, step)):
        u = np.maximum(0, t - at)
        env = (t >= at) * (1 - np.exp(-u / 0.006)) * np.exp(-u / 1.1)
        freq = notes[i % 4] * (2 if i % 8 == 7 else 1)
        track += (
            0.08 * env * (np.sin(2 * np.pi * freq * u) + 0.25 * np.sin(2 * np.pi * 2 * freq * u))
        )
        if style == "social" and i % 4 in (0, 2):
            track += (
                0.07
                * (t >= at)
                * np.sin(2 * np.pi * (55 * u + 15 * (1 - np.exp(-20 * u))))
                * np.exp(-u * 28)
            )
    track *= np.minimum(1, t / 0.35) * np.minimum(1, np.maximum(0, total - t) / 1.1)
    sf.write(path, np.column_stack((track, np.roll(track, 100))), rate, subtype="PCM_16")


def make_voice(spec, folder, allow_cloud, local=False):
    text = "\n".join(spec["lines"])
    voice = folder / "voice.mp3"
    receipt = folder / "voice-source.json"
    local_name = {
        "cinema": "Tingting",
        "social": "Tingting",
        "lab": "Tingting",
    }[spec["style"]]
    local_rate = 190 if spec["style"] == "cinema" else 205
    profile = CLOUD_PROFILES[spec["style"]]
    request_hash = signature(
        {
            "text": text,
            "speaker": local_name if local else profile["speaker"],
            "provider": "macos" if local else "volcengine-seed-tts-2.0",
            "rate": local_rate if local else profile["speech_rate"],
        }
        | ({} if local else {"direction": profile["direction"]})
    )
    if not (
        voice.exists()
        and receipt.exists()
        and json.loads(receipt.read_text())["request_hash"] == request_hash
    ):
        if local:
            draft = folder / "voice-text.txt"
            draft.write_text(text)
            command(
                [
                    "say",
                    "-v",
                    local_name,
                    "-r",
                    str(local_rate),
                    "-f",
                    str(draft),
                    "-o",
                    str(folder / "voice.aiff"),
                ]
            )
            command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(folder / "voice.aiff"),
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(voice),
                ]
            )
        else:
            if not allow_cloud:
                raise RuntimeError(
                    "Missing cached voice; choose --generate-voices or explicit --local-voices"
                )
            key, _ = read_config()
            audio = synthesize(
                text,
                profile["speaker"],
                key,
                direction=profile["direction"],
                speech_rate=profile["speech_rate"],
            )
            voice.write_bytes(audio)
        receipt.write_text(
            json.dumps(
                {
                    "request_hash": request_hash,
                    "provider": "macos" if local else "volcengine",
                    "resource": "installed_system_voice" if local else "seed-tts-2.0",
                    "speaker": local_name if local else profile["speaker"],
                    "synthetic_voice": True,
                    "rate": local_rate if local else profile["speech_rate"],
                    "direction": None if local else profile["direction"],
                    "human_listening": "pending",
                    "sha256": digest(voice),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    raw = folder / "voice-16k.wav"
    command(["ffmpeg", "-v", "error", "-y", "-i", str(voice), "-ar", "16000", "-ac", "1", str(raw)])
    transcript, duration = transcribe(raw, ROOT / "var/models/firered")
    aligned = align(text, transcript, duration)
    (folder / "raw-alignment.json").write_text(json.dumps(aligned, ensure_ascii=False, indent=2))
    if min(s["match"] for s in aligned["sentences"]) < 0.75:
        raise RuntimeError("Low ASR coverage; check the preview text/audio before rendering")
    full_rate = folder / "voice-full.wav"
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(voice),
            "-ar",
            "48000",
            "-ac",
            "1",
            str(full_rate),
        ]
    )
    samples, rate = sf.read(full_rate)
    total = sum(spec["durations"])
    result = np.zeros(round(total * rate))
    offset = 0
    sentences = []
    for i, (sent, slot) in enumerate(zip(aligned["sentences"], spec["durations"], strict=True)):
        left = max(0, sent["start"] - 0.07)
        right = min(duration, sent["end"] + 0.08)
        if i:
            left = max(left, (aligned["sentences"][i - 1]["end"] + sent["start"]) / 2)
        if i + 1 < len(aligned["sentences"]):
            right = min(right, (sent["end"] + aligned["sentences"][i + 1]["start"]) / 2)
        lead = 0.18 if spec["style"] != "cinema" else 0.28
        piece = samples[round(left * rate) : round(right * rate)]
        speed = max(1, len(piece) / rate / (slot - lead - 0.12))
        if speed > 1.18:
            raise RuntimeError(f"{spec['style']} line {i + 1} too dense: {speed:.2f}; shorten copy")
        if speed > 1:
            source = folder / f"voice-{i}-source.wav"
            target = folder / f"voice-{i}-timed.wav"
            sf.write(source, piece, rate)
            command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-af",
                    f"atempo={speed}",
                    "-ar",
                    str(rate),
                    str(target),
                ]
            )
            piece, _ = sf.read(target)
        start = round((offset + lead) * rate)
        end = start + len(piece)
        if end > round((offset + slot) * rate):
            raise RuntimeError("Voice crosses the scene")
        result[start:end] = piece
        words = [
            dict(
                w,
                start=round(offset + lead + (w["start"] - left) / speed, 4),
                end=round(offset + lead + (w["end"] - left) / speed, 4),
            )
            for w in sent["words"]
        ]
        sentences.append(dict(sent, start=words[0]["start"], end=words[-1]["end"], words=words))
        offset += slot
    sf.write(folder / "narration.wav", result, rate, subtype="PCM_16")
    return {
        "sentences": sentences,
        "engine": "firered-local-ctc",
        "review_state": "needs_review",
        "human_reviewer": None,
        "timing_policy": "actual ASR anchors, measured sentence cuts and inserted breath; mild speed <=1.18; not human confirmation",
    }


def prepare(spec, allow_cloud, local=False):
    style = spec["style"]
    folder = WORK / style
    folder.mkdir(parents=True, exist_ok=True)
    alignment = make_voice(spec, folder, allow_cloud, local)
    assets = []
    provenance = []
    for i, ((source, start, crop), duration) in enumerate(
        zip(spec["clips"], spec["durations"], strict=True)
    ):
        parts = spec.get("montages", {}).get(i, [(source, start, duration, crop)])
        if sum(round(part[2] * 30) for part in parts) != round(duration * 30):
            raise ValueError("Montage must fill its measured scene exactly")
        clip = folder / f"visual-{i}.mp4"
        cuts = []
        picture_at = 0
        for n, (key, at, length, framing) in enumerate(parts):
            source_path = SOURCES[key]
            meta = inspect_media(source_path, "video")
            if at + length > meta["duration"] + 0.001:
                raise RuntimeError(f"{style} source overrun {i + 1}")
            w, h, x, y = framing
            part = clip if len(parts) == 1 else folder / f"visual-{i}-part-{n}.mp4"
            command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(at),
                    "-i",
                    str(source_path),
                    "-an",
                    "-vf",
                    f"crop={w}:{h}:{x}:{y},scale=1080:1080,fps=30",
                    "-frames:v",
                    str(round(length * 30)),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    str(part),
                ]
            )
            cuts.append(
                {
                    "source": str(source_path.relative_to(ROOT)),
                    "source_sha256": digest(source_path),
                    "source_in": at,
                    "source_out": at + length,
                    "scene_in": picture_at,
                    "scene_out": picture_at + length,
                    "crop_xywh": [x, y, w, h],
                }
            )
            picture_at += length
        if len(parts) > 1:
            listing = folder / f"visual-{i}-concat.txt"
            listing.write_text(
                "".join(f"file 'visual-{i}-part-{n}.mp4'\n" for n in range(len(parts)))
            )
            command(
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
                    "-c",
                    "copy",
                    str(clip),
                ]
            )
        assets.append(asset(clip, "video"))
        provenance.append(
            {
                "shot": i + 1,
                "cuts": cuts,
                "derivation": "live cuts at source speed; no still, no loop, no reversed action",
                "identity_review": "same shoot/visible glass; SKU unknown",
            }
        )
    voice = asset(folder / "narration.wav", "audio", "voice")
    assets.append(voice)
    bgm = folder / "music-original.wav"
    music(bgm, sum(spec["durations"]), style)
    track = asset(bgm, "audio", "music")
    assets.append(track)
    job = {
        "id": "preview-" + style,
        "title": spec["title"],
        "script": "\n".join(spec["lines"]),
        "seconds": 4,
        "assets": assets,
    }
    rec = recommend(
        job,
        Brief(
            format="recommendation" if style == "social" else "narrated",
            category="透明咖啡杯",
            audience="桌边日常",
            tone="真实自然",
        ),
    )
    choice = next(s for s in rec["options"] if s["id"] == style)
    board = default_board(job)
    board["style"] = choice["family"]
    board["sample"] = False
    board["creative"] = {
        "brief": rec["brief"],
        "fingerprint": rec["fingerprint"],
        "style_id": style,
        "brand": {
            "name": "一杯 / 桌边日常",
            "paper": choice["colors"][0],
            "ink": choice["colors"][1],
            "accent": choice["colors"][2],
            "subtitle_size": 58,
        },
        "sfx": False,
        "alignment_id": None,
    }
    board["narration"].update(mode="uploaded", asset_id=voice["id"])
    board["music_id"] = track["id"]
    board["music_db"] = -27 if style == "cinema" else -29
    for i, shot in enumerate(board["shots"]):
        shot.update(
            shot_id=f"{style}-{i + 1}",
            asset_id=assets[i]["id"],
            duration=spec["durations"][i],
            source_in=0,
            motion="static",
            fit="cover",
            focus_x=0.1 if spec["clips"][i][0] == "desk" else 0.5,
            focus_y=0.5,
            headline=spec["headlines"][i],
            treatment="footage",
            transition="wipe" if style == "cinema" and i in [2, 5] else "cut",
            role="detail" if style == "lab" else "lifestyle",
        )
    snapshot = job | {
        "preview_only": True,
        "storyboard": board,
        "alignment": alignment,
        "provenance": {
            "purpose": "unapproved client discussion preview",
            "review_required": ["facts", "script", "style", "listening", "film"],
            "approvals": [],
            "voice_source": json.loads((folder / "voice-source.json").read_text())
            | {"narration_sha256": digest(folder / "narration.wav")},
            "claims": "visible exterior and dramatized daily scene only; no performance or purchase claims",
            "source_edits": provenance,
        },
    }
    (folder / "preview-job.json").write_text(
        json.dumps({"id": job["id"], "snapshot": snapshot}, ensure_ascii=False, indent=2)
    )
    (folder / "script.txt").write_text(job["script"])
    return folder


def render(spec):
    folder = WORK / spec["style"]
    job = json.loads((folder / "preview-job.json").read_text())
    directory = folder / "render"
    directory.mkdir(exist_ok=True)
    deadline = time.monotonic() + 1800

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Preview render exceeded 30 minutes")

    video, duration = render_remotion(job, WORK, directory, check)
    target = OUT / spec["style"]
    target.mkdir(exist_ok=True)
    for name in ["output.mp4", "subtitles.srt", "shotbook.json", "manifest.json"]:
        shutil.copy2(directory / name, target / name)
    for name in ["narration.wav", "voice-source.json", "script.txt", "preview-job.json"]:
        shutil.copy2(folder / name, target / name)
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "1.5",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(target / "poster.jpg"),
        ]
    )
    row = {k: spec[k] for k in ["style", "title", "description", "hook"]}
    voice_provider = json.loads((folder / "voice-source.json").read_text())["provider"]
    row["description"] += " · 本机合成配音" if voice_provider == "macos" else " · 火山合成配音"
    row.update(
        duration=duration,
        status="needs_review",
        video_sha256=digest(video),
        review_required=["facts", "script", "style", "listening", "film"],
    )
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def verify_sources(fetch=False):
    import httpx

    rows = json.loads((OUT / "sources.json").read_text())["sources"]
    for row in rows:
        path = ROOT / row["path"]
        if not path.is_file() and fetch:
            if not row["download_url"].startswith("https://videos.pexels.com/video-files/"):
                raise ValueError("Unexpected source origin")
            path.parent.mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=40, trust_env=False, follow_redirects=False) as client:
                response = client.get(
                    row["download_url"],
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pexels.com/"},
                )
                response.raise_for_status()
                if len(response.content) > 40 * 1024**2:
                    raise ValueError("Source too large")
                from hashlib import sha256

                if sha256(response.content).hexdigest() != row["sha256"]:
                    raise ValueError("Source changed; recheck licensing and cup identity")
                path.write_bytes(response.content)
        if not path.is_file() or digest(path) != row["sha256"]:
            raise ValueError(
                "Missing/changed source; use --fetch-sources or review source provenance"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-voices", action="store_true")
    parser.add_argument("--local-voices", action="store_true")
    parser.add_argument("--fetch-sources", action="store_true")
    parser.add_argument("--style", choices=["cinema", "social", "lab"])
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    verify_sources(args.fetch_sources)
    selected_specs = [s for s in SPECS if not args.style or s["style"] == args.style]
    if not args.render_only:
        for spec in selected_specs:
            prepare(spec, args.generate_voices, args.local_voices)
            print("PREPARED " + spec["style"], flush=True)
    if not args.prepare_only:
        library_path = OUT / "library.json"
        old = json.loads(library_path.read_text())["samples"] if library_path.exists() else []
        selected_styles = {s["style"] for s in selected_specs}
        updated = [row for row in old if row["style"] not in selected_styles]
        for spec in selected_specs:
            updated.append(render(spec))
        rows = sorted(updated, key=lambda row: ["cinema", "social", "lab"].index(row["style"]))
        (OUT / "library.json").write_text(
            json.dumps(
                {"schema": "client-preview-v1", "samples": rows}, ensure_ascii=False, indent=2
            )
        )


if __name__ == "__main__":
    main()
