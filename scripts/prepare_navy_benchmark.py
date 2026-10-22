"""Prepare A-direction script, listening mix and immutable render inputs, not approvals."""

import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path

from ecom_video.media import digest
from ecom_video.visual_finish import prepare_visuals


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def prepare(source, openings, voice, music, output):
    output.mkdir(parents=True, exist_ok=False)
    public = output / "public"
    public.mkdir()
    original = json.loads((source / "render-input.json").read_text())
    first = json.loads((openings / "render-input.json").read_text())
    old_manifest = json.loads((source / "manifest.json").read_text())
    specs = [s["props"] for s in original["shots"]]
    script, clips, shots, scenes = [], [], [], []
    sequence = [
        (4, 114, 16.5666666667),
        (2, 102, 8.9333333333),
        (1, 180, 2.9333333333),
        (3, 127, 12.3333333333),
        (4, 263, None),
        (5, 107, 25.3333333333),
    ]
    position = 0
    for i, (index, frames, voice_in) in enumerate(sequence):
        if i < 2:
            props = copy.deepcopy(first["shots"][i]["props"])
            src = Path(first["publicDir"]) / props["src"]
        else:
            props = copy.deepcopy(specs[index])
            src = Path(original["publicDir"]) / props["src"]
            props.update(
                clientPresentation=True,
                suppressTitle=True,
                preview=False,
                sample=False,
                frames=frames,
                transition="cut",
                exitTransition="cut",
                headline="",
            )
            props["brand"].update(subtitle_size=76, accent="#ffda73")
            if voice_in is None:
                props.update(
                    words=[],
                    voiceStart=0,
                    voiceEnd=0,
                    format="showcase",
                    captionNote="防泼水演示，非防水等级测试",
                )
            else:
                delta = old_manifest["scenes"][index]["start"] - voice_in
                for w in props["words"]:
                    w["start"] = round(w["start"] + delta, 4)
                    w["end"] = round(w["end"] + delta, 4)
                props["voiceStart"] += delta
                props["voiceEnd"] += delta
                props["headline"] = {1: "藏蓝", 3: "收紧", 5: "怎么搭"}[index]
            props.update(prepare_visuals(props))
        shutil.copyfile(src, public / src.name)
        key = f"shot-{i + 1:02}"
        shots.append({"key": key, "props": props})
        part = output / (key + ".wav")
        if voice_in is None:
            run(
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                frames / 30,
                part,
            )
        else:
            script.append(props["text"])
            run(
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                voice,
                "-af",
                f"atrim=start={voice_in}:end={voice_in + frames / 30},asetpts=PTS-STARTPTS,apad,atrim=duration={frames / 30}",
                "-ar",
                "48000",
                "-ac",
                "2",
                part,
            )
        clips.append(part)
        scenes.append(
            {
                "shot": key,
                "start": position / 30,
                "end": (position + frames) / 30,
                "original_scene": index + 1,
                "voice_source_in": voice_in,
                "visual": "完整原速泼水，留白观察" if voice_in is None else props["text"],
                "source_sha256": digest(src),
            }
        )
        position += frames
    listing = output / "voice-concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in clips))
    run(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        listing,
        "-c",
        "copy",
        output / "voice.wav",
    )
    mix = output / "listening.m4a"
    run(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        output / "voice.wav",
        "-stream_loop",
        "-1",
        "-i",
        music,
        "-filter_complex",
        f"[0:a]loudnorm=I=-17:TP=-2:LRA=7,asplit=2[v][key];[1:a]volume=0.07,afade=t=in:d=0.2,afade=t=out:st={position / 30 - 0.7}:d=0.7[m];[m][key]sidechaincompress=threshold=0.02:ratio=5:attack=15:release=200[b];[v][b]amix=inputs=2:normalize=0,alimiter=limit=0.94:level=false[a]",
        "-map",
        "[a]",
        "-t",
        position / 30,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        mix,
    )
    config = {"publicDir": str(public), "outputDir": str(output), "shots": shots}
    (output / "render-input.json").write_text(json.dumps(config, ensure_ascii=False))
    plan = {
        "version": 1,
        "title": "藏蓝软壳衣 · A动作先行标杆稿",
        "duration": position / 30,
        "script": script,
        "scenes": scenes,
        "source_film_sha256": digest(source / "output.mp4"),
        "voice_source_sha256": digest(voice),
        "listening_sha256": digest(mix),
        "approval": "pending_script_storyboard_and_listening",
        "cloud_calls": 0,
        "alignment_policy": "只平移复用原字锚点，估算状态保留；没有伪造ASR或听审记录",
    }
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["source", "openings", "voice", "music", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    prepare(**vars(p.parse_args()))
