"""Three 26/27/28s same-product films. Local copies only; no cloud, DB, approval or ad writes."""

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STYLES = ("cinema", "social", "lab")
RECIPES = {
    "cinema": [
        "marker-underline-title",
        "blur-slide",
        "marker-underline-title",
        "none",
        "product-card-progressive-assemble",
        "none",
    ],
    "social": [
        "crash-zoom-punch",
        "product-card-progressive-assemble",
        "marker-underline-title",
        "blur-slide",
        "none",
        "product-card-progressive-assemble",
        "none",
    ],
    "lab": [
        "crash-zoom-punch",
        "scanline-annotate-focus",
        "scanline-annotate-focus",
        "none",
        "none",
        "product-card-progressive-assemble",
        "marker-underline-title",
    ],
}
GUARDS = {
    "cinema": {0: [(1, 3.3)], 1: [(0, 2.6)], 3: [(0, 1.0)]},
    "social": {1: [(0, 2.4)], 4: [(0, 1.4)], 5: [(0.2, 1.5)]},
    "lab": {3: [(0, 3.4)], 4: [(0.1, 1.2), (1.2, 2.3)]},
}
# Recovered from the SAME original: cup returned visibly at ~10.6–11.8s, black starts ~13s.
RECUTS = {
    "social": {
        5: [("cup", 10.4, 2.0, [900, 900, 90, 930]), ("desk", 0.7, 2.0, [1080, 1080, 0, 720])]
    },
    "lab": {
        4: [
            ("cup", 7.25, 1.2, [880, 880, 100, 960]),
            ("cup", 10.6, 1.5, [880, 880, 100, 960]),
            ("desk", 0.5, 1.6, [1080, 1080, 0, 720]),
        ]
    },
}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def corrected_provenance(original, board, edits):
    """Replace the changed source cuts; retain the historical receipt without mutating it."""
    provenance = copy.deepcopy(original)
    if not edits:
        return provenance
    previous = copy.deepcopy(provenance.get("source_edits", []))
    provenance["previous_source_edits"] = previous
    updated = copy.deepcopy(previous)
    for index, shot in enumerate(board["shots"]):
        parts = [e for e in edits if e["shot_id"] == shot["shot_id"]]
        if not parts:
            continue
        cuts, position = [], 0
        for part in parts:
            w, h, x, y = part["crop"]
            end = round(position + part["seconds"], 6)
            cuts.append(
                {
                    "source": part["source"],
                    "source_sha256": part["source_sha256"],
                    "source_in": part["source_in"],
                    "source_out": round(part["source_in"] + part["seconds"], 6),
                    "scene_in": position,
                    "scene_out": end,
                    "crop_xywh": [x, y, w, h],
                }
            )
            position = end
        updated = [p for p in updated if p["shot"] != index + 1]
        updated.append(
            {
                "shot": index + 1,
                "cuts": cuts,
                "derivation": "live cuts at source speed; no still, no loop, no reversed action",
                "identity_review": "same shoot/visible glass; SKU unknown",
            }
        )
    provenance["source_edits"] = sorted(updated, key=lambda row: row["shot"])
    return provenance


def main():
    from ecom_video.creative import rebase_fingerprint
    from ecom_video.media import digest, inspect_media, safe_path
    from ecom_video.remotion_renderer import frame_local_time, render_remotion
    from ecom_video.shotcraft import MotionPlan, effective_transitions, resolve_motion

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or data == Path("/"):
        ap.error("Use a dedicated external output directory")
    data.mkdir(parents=True, exist_ok=True)
    library = ROOT / "examples/client-demo"
    sources = {
        "cup": library / "sources/6177758.mp4",
        "pour": ROOT / "examples/p9-real/originals/6177761.mp4",
        "desk": library / "sources/6177756.mp4",
    }
    results = {}
    for style in STYLES:
        folder = data / style
        folder.mkdir(exist_ok=True)
        runtime = folder / "runtime"
        job = json.loads((library / style / "preview-job.json").read_text())
        old = copy.deepcopy(job)
        job["id"] = "narrative-" + style
        snap = job["snapshot"]
        snap["preview_only"] = True
        for a in snap["assets"]:
            src = safe_path(library / "work", a["path"])
            assert digest(src) == a["sha256"], a["name"]
            dst = runtime / a["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)
        edits = []
        for index, parts in RECUTS.get(style, {}).items():
            shot = snap["storyboard"]["shots"][index]
            a = next(a for a in snap["assets"] if a["id"] == shot["asset_id"])
            segments = []
            for n, (source, start, duration, crop) in enumerate(parts):
                path = folder / f"recut-{index}-{n}.mp4"
                frames = round(duration * 30)
                w, h, x, y = crop
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-ss",
                        str(start),
                        "-i",
                        str(sources[source]),
                        "-an",
                        "-vf",
                        f"crop={w}:{h}:{x}:{y},scale=1080:1080,fps=30,setsar=1",
                        "-frames:v",
                        str(frames),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "18",
                        str(path),
                    ],
                    check=True,
                )
                segments.append(path)
                edits.append(
                    {
                        "shot_id": shot["shot_id"],
                        "source": str(sources[source].relative_to(ROOT)),
                        "source_sha256": digest(sources[source]),
                        "source_in": start,
                        "seconds": duration,
                        "crop": crop,
                        "review": "assistant frame review; not customer approval",
                    }
                )
            listing = folder / f"recut-{index}.txt"
            listing.write_text("".join(f"file '{p.name}'\n" for p in segments))
            dst = runtime / a["path"]
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(listing),
                    "-c",
                    "copy",
                    str(dst),
                ],
                check=True,
            )
            a.update(
                sha256=digest(dst),
                size=dst.stat().st_size,
                metadata={**inspect_media(dst, "video"), "customer_role": "product"},
            )
            assert round(a["metadata"]["duration"] * 30) == round(shot["duration"] * 30)
        for asset in snap["assets"]:
            assert digest(safe_path(runtime, asset["path"])) == asset["sha256"]
        board = snap["storyboard"]
        snap["provenance"] = corrected_provenance(snap["provenance"], board, edits)
        for index, shot in enumerate(board["shots"]):
            shot["shot_recipe"] = RECIPES[style][index]
            intent = (
                "hook"
                if index == 0
                else "outro"
                if index == len(board["shots"]) - 1
                else "action"
                if index in GUARDS[style]
                else "detail"
                if style == "lab" and index in (1, 2)
                else "context"
            )
            shot["motion_plan"] = MotionPlan(
                strength="subtle"
                if style == "cinema"
                else "bold"
                if style == "social"
                else "balanced",
                intent=intent,
            ).model_dump()
            shot["motion_plan"]["windows"] = [
                {"start": a, "end": b, "basis": "manual"} for a, b in GUARDS[style].get(index, [])
            ]
            shot["transition"] = "cut"
            if style == "cinema" and index == 4:
                shot["transition"] = "line-carry"
            if style == "social" and index in (3, 6):
                shot["transition"] = "push-stack"
            if style == "lab" and index == 5:
                shot["transition"] = "line-carry"
            if style == "lab" and index == 1:
                shot.update(focus_x=0.63, focus_y=0.18)
            if style == "lab" and index == 2:
                shot.update(focus_x=0.5, focus_y=0.32)
        board["creative"]["fingerprint"] = rebase_fingerprint(
            old["snapshot"], snap, old["snapshot"]["storyboard"]["creative"]
        )
        transitions = effective_transitions(
            [{**s, "frames": round(s["duration"] * 30)} for s in board["shots"]]
        )
        timing = []
        position = 0
        for index, shot in enumerate(board["shots"]):
            sentence = snap["alignment"]["sentences"][index]
            start = position / 30
            words = [
                {
                    **w,
                    "start": frame_local_time(w["start"], start),
                    "end": frame_local_time(w["end"], start),
                }
                for w in sentence["words"]
            ]
            scene = {
                **shot,
                "frames": round(shot["duration"] * 30),
                "text": snap["script"].splitlines()[index],
                "start": start,
                "voice_start": sentence["start"],
            }
            decision = resolve_motion(scene, words)
            timing.append(
                {
                    "shot_id": shot["shot_id"],
                    "requested": shot["shot_recipe"],
                    "decision": decision,
                    "transition": transitions[index],
                }
            )
            position += scene["frames"]
        assert 600 <= position <= 900 and all(
            a["kind"] == "video" for a in snap["assets"] if a["kind"] != "audio"
        )
        assert (
            len({d["decision"]["recipe"] for d in timing if d["decision"]["recipe"] != "none"}) >= 2
        ), timing
        assert any(t["transition"] != "cut" for t in timing)
        save(folder / "preview-job.json", job)
        save(
            folder / "creative-timing.json",
            {
                "style": style,
                "duration": position / 30,
                "shots": timing,
                "source_edits": edits,
                "voice_source": "reused existing Volcengine voice, zero provider calls",
                "approval": "needs_review",
            },
        )
        print(
            style,
            "prepared",
            position / 30,
            [(t["decision"]["recipe"], t["decision"]["guard_outcome"]) for t in timing],
            flush=True,
        )
        if args.prepare_only:
            continue
        out = folder / "film"
        out.mkdir(exist_ok=True)
        render_remotion(job, runtime, out, lambda: None)
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["alignment"] == old["snapshot"]["alignment"]
        # Change only a visual timing/strength parameter. No narration, source or transition changes.
        revision = copy.deepcopy(job)
        target = 2
        revision["id"] += "-single"
        revision["snapshot"]["storyboard"]["shots"][target]["motion_plan"]["cue_offset"] = 0.25
        revision["snapshot"]["storyboard"]["shots"][target]["motion_plan"]["strength"] = "bold"
        retry = folder / "single"
        retry.mkdir(exist_ok=True)
        render_remotion(revision, runtime, retry, lambda: None)
        after = json.loads((retry / "manifest.json").read_text())
        assert after["cache"] == {
            "hits": len(board["shots"]) - 1,
            "rendered": 1,
            "total": len(board["shots"]),
        }, after["cache"]
        for i in range(len(board["shots"])):
            if i != target:
                assert manifest["scenes"][i]["cache_key"] == after["scenes"][i]["cache_key"]
                assert digest(out / f"scene-{i:03d}.mp4") == digest(retry / f"scene-{i:03d}.mp4")
        assert digest(out / "narration.wav") == digest(retry / "narration.wav")
        record = {
            "status": "needs_review",
            "style": style,
            "duration": position / 30,
            "frames": position,
            "cache": after["cache"],
            "single_target": board["shots"][target]["shot_id"],
            "other_scene_files_unchanged": True,
            "raw_narration_unchanged": True,
            "word_anchors_unchanged": manifest["alignment"] == after["alignment"],
            "provider_calls": 0,
            "database_writes": 0,
            "old_sample_sha256": digest(library / style / "output.mp4"),
            "film_sha256": digest(out / "output.mp4"),
            "source_edits": edits,
        }
        save(folder / "acceptance.json", record)
        results[style] = record
        print(style, "rendered", after["cache"], flush=True)
    if not args.prepare_only:
        save(data / "acceptance.json", results)


if __name__ == "__main__":
    main()
