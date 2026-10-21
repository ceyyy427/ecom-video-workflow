"""Render two isolated motion comparisons from frozen, already licensed category examples.

No account, API, provider, model, review, database or platform mutation is performed.
The existing narration and manually reviewed source ranges are reused byte-for-byte.
"""

import argparse
import copy
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.media import digest, safe_path
    from ecom_video.remotion_renderer import render_remotion
    from ecom_video.shotcraft import choreography

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--headphones-runtime", type=Path, required=True)
    ap.add_argument("--serum-runtime", type=Path, required=True)
    args = ap.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or data == Path("/"):
        ap.error("Render into a dedicated external directory")
    data.mkdir(parents=True, exist_ok=True)
    report = {}
    for case in ("headphones", "serum"):
        runtime = getattr(args, case + "_runtime").resolve()
        published = ROOT / "examples/category-demo" / case
        manifest = json.loads((published / "manifest.json").read_text())
        # Read-only SQLite connection: even the isolated source fixture stays unchanged.
        with sqlite3.connect(f"file:{runtime / 'workflow.db'}?mode=ro", uri=True) as db:
            raw = db.execute(
                "SELECT snapshot FROM jobs WHERE id=?", (manifest["job_id"],)
            ).fetchone()
        snap = json.loads(raw[0])
        assert snap["storyboard"] == manifest["storyboard"]
        folder = data / case
        folder.mkdir(exist_ok=True)
        local = folder / "runtime"
        for asset in snap["assets"]:
            src = safe_path(runtime, asset["path"])
            assert digest(src) == asset["sha256"]
            dst = local / asset["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)
            assert digest(dst) == asset["sha256"]
        snap["preview_only"] = True
        old_board = copy.deepcopy(snap["storyboard"])
        style = old_board["creative"]["style_id"]
        decisions = choreography(
            snap["script"].splitlines(), style, [s["duration"] for s in old_board["shots"]]
        )
        for shot, decision in zip(snap["storyboard"]["shots"], decisions, strict=True):
            shot.update(shot_recipe=decision["shot_recipe"], transition=decision["transition"])
        expected = copy.deepcopy(snap)
        original = published / "output.mp4"
        before = digest(original)
        out = folder / "motion"
        out.mkdir(exist_ok=True)
        render_remotion(
            {"id": "motion-" + manifest["job_id"], "snapshot": snap}, local, out, lambda: None
        )
        current = json.loads((out / "manifest.json").read_text())
        assert snap == expected and digest(original) == before
        assert current["alignment"] == manifest["alignment"]
        for old, new in zip(manifest["scenes"], current["scenes"], strict=True):
            for key in ("asset_sha256", "source_in", "frames", "word_anchors"):
                assert old[key] == new[key], (case, key)
        # Actual incremental render, not just comparing a mocked key generator.
        revised = copy.deepcopy(snap)
        revised["storyboard"]["shots"][2]["shot_recipe"] = "none"
        retry = folder / "single-recipe"
        retry.mkdir(exist_ok=True)
        render_remotion(
            {"id": "motion-retake-" + manifest["job_id"], "snapshot": revised},
            local,
            retry,
            lambda: None,
        )
        retake = json.loads((retry / "manifest.json").read_text())
        assert retake["cache"] == {"hits": 4, "rendered": 1, "total": 5}, retake["cache"]
        for i, (a, b) in enumerate(zip(current["scenes"], retake["scenes"], strict=True)):
            if i != 2:
                assert a["cache_key"] == b["cache_key"]
                assert digest(out / f"scene-{i:03d}.mp4") == digest(retry / f"scene-{i:03d}.mp4")
        assert digest(out / "narration.wav") == digest(retry / "narration.wav")
        record = {
            "status": "needs_review",
            "parent_job": manifest["job_id"],
            "parent_film_sha256": before,
            "motion_film_sha256": digest(out / "output.mp4"),
            "style": style,
            "decisions": decisions,
            "source_ranges_unchanged": True,
            "word_anchors_unchanged": True,
            "single_recipe_cache": retake["cache"],
            "other_four_scene_files_unchanged": True,
            "narration_unchanged": True,
            "provider_calls": 0,
            "database_writes": 0,
            "note": "复用先前人工校正的实拍区间与合成配音；本次仅检查画面编排，不代表自动识别已达到客户验收精度。",
        }
        (folder / "acceptance.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        )
        report[case] = record
        print(case, record["single_recipe_cache"], flush=True)
    (data / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
