"""Publish verified edited motion comparisons to the read-only gallery, still pending review."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.media import digest, probe

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    records = json.loads((args.data / "acceptance.json").read_text())
    target = ROOT / "examples/motion-demo"
    evidence = ROOT / "docs/evidence/shotcraft-integration"
    evidence.mkdir(exist_ok=True)
    rows = []
    for case, title, description in [
        ("headphones", "耳机 · 节奏字卡", "关键词冲击、实拍动作连续呈现、推叠换章"),
        ("serum", "滴管瓶 · 质感杂志", "手绘划线、操作分阶段展开、线条接力"),
    ]:
        record = records[case]
        assert record["status"] == "needs_review" and record["source_ranges_unchanged"]
        assert record["word_anchors_unchanged"] and record["narration_unchanged"]
        assert record["single_recipe_cache"] == {"hits": 4, "rendered": 1, "total": 5}
        src = args.data / case
        parent = ROOT / "examples/category-demo" / case / "output.mp4"
        assert digest(parent) == record["parent_film_sha256"]
        assert digest(src / "motion/output.mp4") == record["motion_film_sha256"]
        folder = target / case
        folder.mkdir(parents=True, exist_ok=True)
        for source, name in [
            (parent, "parent.mp4"),
            (src / "single-recipe/output.mp4", "retake.mp4"),
        ]:
            shutil.copy2(source, folder / name)
        for name in ("output.mp4", "shotbook.json", "manifest.json", "subtitles.srt"):
            shutil.copy2(src / "motion" / name, folder / name)
        shutil.copy2(src / "acceptance.json", evidence / (case + ".json"))
        for phase in ("motion", "single-recipe"):
            shutil.copy2(src / phase / "manifest.json", evidence / f"{case}-{phase}-manifest.json")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "1",
                "-i",
                str(folder / "output.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(folder / "poster.jpg"),
            ],
            check=True,
        )
        duration = float(probe(folder / "output.mp4")["format"]["duration"])
        rows.append(
            {
                "style": case,
                "title": title,
                "duration": duration,
                "description": description
                + "。复用原文稿、配音及人工校正实拍；竖屏适配，仍待听审。",
            }
        )
    (target / "library.json").write_text(
        json.dumps({"samples": rows}, ensure_ascii=False, indent=2) + "\n"
    )
    print("Published edited comparisons, pending human review:", len(rows))


if __name__ == "__main__":
    main()
