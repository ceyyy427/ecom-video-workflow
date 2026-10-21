"""Two-category refinement rehearsal. No browser UI, cloud, DB or approval writes.

Read frozen source snapshots through read-only SQLite. Preserve licensed footage,
whole narration and anchors. Only the dedicated external output directory changes.
"""

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def pcm(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def main():
    from ecom_video.creative import recommend
    from ecom_video.media import digest, safe_path
    from ecom_video.production_direction import choreography_for
    from ecom_video.remotion_renderer import render_remotion

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--headphones-runtime", type=Path, required=True)
    ap.add_argument("--serum-runtime", type=Path, required=True)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or data == Path("/") or data.exists():
        ap.error("Use a new dedicated external directory; existing outputs are never overwritten")
    data.mkdir(parents=True)
    outputs = {}
    neutral = {}
    for case in ["headphones", "serum"]:
        published = ROOT / "examples/category-demo" / case
        m = json.loads((published / "manifest.json").read_text())
        runtime = getattr(args, case + "_runtime").resolve()
        with sqlite3.connect((runtime / "workflow.db").as_uri() + "?mode=ro", uri=True) as db:
            raw = db.execute("SELECT snapshot FROM jobs WHERE id=?", (m["job_id"],)).fetchone()
        snap = json.loads(raw[0])
        assert snap["storyboard"] == m["storyboard"]
        folder = data / case
        folder.mkdir()
        local = folder / "runtime"
        for a in snap["assets"]:
            src = safe_path(runtime, a["path"])
            assert digest(src) == a["sha256"]
            dst = safe_path(local, a["path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            assert digest(dst) == a["sha256"]
        brief = snap["storyboard"]["creative"]["brief"]
        rec = recommend(snap, brief)
        chosen = rec["options"][0]["id"]
        assert chosen == snap["storyboard"]["creative"]["style_id"]
        comparisons = {"original": rec}
        for field, value in [
            ("audience", "理性观察产品细节与功能的专业消费者"),
            ("tone", "严谨理性，参数细节，清楚观察"),
        ]:
            changed = recommend(snap, {**brief, field: value})
            assert changed["fingerprint"] != rec["fingerprint"]
            assert [s["id"] for s in changed["options"]] != [s["id"] for s in rec["options"]]
            comparisons["changed_" + field] = changed
        neutral[case] = recommend(
            {
                "title": "商品示例",
                "script": snap["script"],
                "assets": [{"kind": "video", "sha256": "neutral"}],
            },
            {
                "format": "narrated",
                "category": "日用品",
                "audience": "普通消费者",
                "tone": "清楚展示",
            },
        )
        save(folder / "recommendations.json", comparisons)
        shutil.copyfile(published / "manual-selection.json", folder / "manual-selection.json")
        old = copy.deepcopy(snap)
        snap["preview_only"] = True
        board = snap["storyboard"]
        board["creative"]["production"] = "narrative-v1"
        rows = choreography_for(
            snap["script"].splitlines(), chosen, [s["duration"] for s in board["shots"]]
        )
        for shot, row in zip(board["shots"], rows, strict=True):
            shot.update(
                shot_recipe=row["shot_recipe"],
                transition=row["transition"],
                motion_plan=row["motion_plan"],
            )
        job = {"id": "refinement-" + case, "snapshot": snap}
        save(folder / "job.json", job)
        save(folder / "planning.json", rows)
        if args.prepare_only:
            print(case, "prepared", chosen, flush=True)
            continue
        out = folder / "refined"
        out.mkdir()
        render_remotion(job, local, out, lambda: None)
        current = json.loads((out / "manifest.json").read_text())
        assert current["alignment"] == old["alignment"]
        for a, b in zip(current["scenes"], m["scenes"], strict=True):
            assert all(
                a[k] == b[k] for k in ["source_in", "frames", "asset_sha256", "word_anchors"]
            )
        # Literal same voice version, never a TTS call in this rehearsal.
        voice = next(a for a in snap["assets"] if a["id"] == board["narration"]["asset_id"])
        # The renderer intentionally normalizes uploaded 24k mono voice to 48k stereo.
        # Compare with the same frozen version's normalized render, not its raw container.
        normalized = list((runtime / "jobs" / m["job_id"]).glob("attempt-*/narration.wav"))
        assert normalized and any(digest(out / "narration.wav") == digest(p) for p in normalized)
        assert digest(safe_path(local, voice["path"])) == voice["sha256"]
        child = copy.deepcopy(job)
        child["id"] += "-single"
        child["snapshot"]["storyboard"]["shots"][2]["motion_plan"]["visual_finish"] = "legacy"
        retry = folder / "single"
        retry.mkdir()
        render_remotion(child, local, retry, lambda: None)
        after = json.loads((retry / "manifest.json").read_text())
        n = len(current["scenes"])
        assert after["cache"] == {"hits": n - 1, "rendered": 1, "total": n}
        assert digest(out / "scene-002.mp4") != digest(retry / "scene-002.mp4")
        for i in range(n):
            if i != 2:
                assert digest(out / f"scene-{i:03d}.mp4") == digest(retry / f"scene-{i:03d}.mp4")
        assert current["alignment"] == after["alignment"] and pcm(out / "output.mp4") == pcm(
            retry / "output.mp4"
        )
        for p in [out / "output.mp4", retry / "output.mp4"]:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(p), "-f", "null", "-"], check=True, timeout=90
            )
        save(folder / "treatment.json", current["motion_treatment"])
        first = current["scenes"][0]
        cue = first.get("motion_decision", {}).get("cue_frame", 15) / 30
        poster_time = min(first["end"] - 0.2, max(0.5, cue + 0.5))
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(poster_time),
                "-i",
                str(out / "output.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(folder / "poster.jpg"),
            ],
            check=True,
            timeout=30,
        )
        row = {
            "style": chosen,
            "duration": current["duration"],
            "shots": n,
            "cache": after["cache"],
            "original_selection_and_anchors_unchanged": True,
            "narration_file_unchanged": True,
            "other_scene_bytes_equal": True,
            "target_scene_changed": True,
            "decoded_mix_equal": True,
            "emphasis_phrases": sum(
                bool(c.get("emphasis")) for s in current["scenes"] for c in s["caption_layout"]
            ),
            "timing_warnings": [
                {"shot_id": s["shot_id"], "warnings": s["warnings"]}
                for s in current["motion_treatment"]["shots"]
                if s["warnings"]
            ],
            "film_sha256": digest(out / "output.mp4"),
            "retake_sha256": digest(retry / "output.mp4"),
            "status": "needs_review",
            "cloud_calls": 0,
            "database_writes": 0,
            "platform_writes": 0,
            "selection_mode": "previous_manual_after_local_proposals",
            "computer_use": False,
        }
        save(folder / "acceptance.json", row)
        outputs[case] = row
        print(case, json.dumps(row, ensure_ascii=False), flush=True)
    save(data / "content-only-recommendations.json", neutral)
    save(data / "acceptance.json", outputs)


if __name__ == "__main__":
    main()
