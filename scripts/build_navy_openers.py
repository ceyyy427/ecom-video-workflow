"""Private, reproducible opening comparisons from an existing render receipt.

No project/DB writes, cloud requests or approval records. Outputs remain proposals.
"""

import argparse
import copy
import json
import subprocess
from pathlib import Path

from ecom_video.media import digest, probe
from ecom_video.remotion_renderer import ENGINE
from ecom_video.visual_finish import prepare_visuals


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def build(source, voice, music, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((source / "render-input.json").read_text())
    public = Path(original["publicDir"])
    specs = [s["props"] for s in original["shots"]]
    assert len(specs) == 6, "需要已核对的藏蓝六镜渲染记录"
    before = digest(source / "output.mp4")
    designs = [
        (
            "A",
            "先看动作，再看细节",
            [(4, 3.8, 16.5666666667, "泼上去"), (2, 3.4, 8.9333333333, "拉链口袋")],
        ),
        (
            "B",
            "穿搭问题，接上可见细节",
            [(0, 3.1333333333, 0, "上班"), (3, 4.2333333333, 12.3333333333, "收紧")],
        ),
    ]
    pending, records = [], []
    manifest = json.loads((source / "manifest.json").read_text())
    for code, name, shots in designs:
        directory = output / code
        directory.mkdir()
        for n, (index, seconds, voice_in, keyword) in enumerate(shots):
            p = copy.deepcopy(specs[index])
            frames = round(seconds * 30)
            delta = manifest["scenes"][index]["start"] - voice_in
            p.update(
                frames=frames,
                clientPresentation=True,
                suppressTitle=True,
                headline=keyword,
                captionNote="防泼水实拍片段" if index == 4 else "",
                preview=False,
                sample=False,
                transition="cut",
                exitTransition="cut",
            )
            p["brand"].update(subtitle_size=76, accent="#ffda73")
            if index == 4:
                # Explicit hook excerpt, not a complete-action evidence clip.
                # Do not change source speed or the original full-film action.
                hook_source = output / "A-water-hook.mp4"
                run(
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    "2.7",
                    "-i",
                    public / p["src"],
                    "-an",
                    "-frames:v",
                    frames,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    hook_source,
                )
                # The bundle exposes the original public folder; use an existing
                # verified public-directory source location without editing it.
                p["src"] = "navy-water-hook.mp4"
            p.pop("typography", None)
            p.pop("titleLayout", None)
            for w in p["words"]:
                w["start"] = round(w["start"] + delta, 4)
                w["end"] = round(w["end"] + delta, 4)
            p["voiceStart"] += delta
            p["voiceEnd"] += delta
            p.update(prepare_visuals(p))
            key = code + str(n)
            pending.append({"key": key, "props": p})
            wav = output / (key + ".wav")
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
                wav,
            )
        records.append(
            {
                "id": code,
                "name": name,
                "seconds": sum(round(s[1] * 30) for s in shots) / 30,
                "script": [specs[s[0]]["text"] for s in shots],
                "approval": "pending_opening_choice_and_listening",
                "source_scene_indices": [s[0] for s in shots],
                "water": "仅开头预告，不作为完整演示；全片仍须保留完整原速动作"
                if code == "A"
                else "本开头不展示泼水",
            }
        )
    import shutil

    isolated_public = output / "public"
    isolated_public.mkdir()
    for item in pending:
        name = item["props"]["src"]
        src = output / "A-water-hook.mp4" if name == "navy-water-hook.mp4" else public / name
        shutil.copyfile(src, isolated_public / name)
    config = {"publicDir": str(isolated_public), "outputDir": str(output), "shots": pending}
    (output / "render-input.json").write_text(json.dumps(config, ensure_ascii=False))
    run("node", ENGINE / "render.mjs", output / "render-input.json")
    for record in records:
        code = record["id"]
        for n in range(2):
            run(
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                output / f"{code}{n}.mp4",
                "-i",
                output / f"{code}{n}.wav",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "pcm_s16le",
                output / f"{code}{n}.mov",
            )
        listing = output / f"{code}-concat.txt"
        listing.write_text("".join(f"file '{code}{n}.mov'\n" for n in range(2)))
        common = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", str(listing)]
        if music:
            common += [
                "-stream_loop",
                "-1",
                "-i",
                str(music),
                "-filter_complex",
                f"[0:a]loudnorm=I=-17:TP=-2:LRA=7,asplit=2[v][key];[1:a]volume=0.07,afade=t=in:d=0.2,afade=t=out:st={record['seconds'] - 0.5}:d=0.5[m];[m][key]sidechaincompress=threshold=0.02:ratio=5:attack=15:release=200[b];[v][b]amix=inputs=2:normalize=0,alimiter=limit=0.94:level=false[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
            ]
        else:
            common += ["-map", "0:v:0", "-map", "0:a:0", "-af", "loudnorm=I=-17:TP=-2:LRA=7"]
        film = output / code / "opening.mp4"
        run(
            *common,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            record["seconds"],
            "-movflags",
            "+faststart",
            film,
        )
        run(
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-i",
            film,
            "-f",
            "null",
            "-",
        )
        video = next(s for s in probe(film)["streams"] if s["codec_type"] == "video")
        assert int(video["nb_frames"]) == round(record["seconds"] * 30)
        assert (video["width"], video["height"]) == (1080, 1920)
        record.update(sha256=digest(film), frames=int(video["nb_frames"]), path=str(film))
    assert digest(source / "output.mp4") == before
    receipt = {
        "source_film_sha256": before,
        "voice_sha256": digest(voice),
        "cloud_calls": 0,
        "original_unchanged": True,
        "approvals_written": 0,
        "openings": records,
    }
    (output / "acceptance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--approved-render", type=Path, required=True)
    p.add_argument("--voice", type=Path, required=True)
    p.add_argument("--music", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    build(a.approved_render, a.voice, a.music, a.output)
