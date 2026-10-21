"""Copy verified isolated runs to the read-only gallery; never approve or distribute."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.creative import CATALOG
    from ecom_video.media import digest, probe

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--headphones-data", type=Path, help="Use a later isolated visual revision")
    args = ap.parse_args()
    cases = json.loads((ROOT / "docs/evidence/category-validation/cases.json").read_text())
    catalog = {s["id"]: s for s in CATALOG}
    samples = []
    for case, spec in cases.items():
        src = (
            args.headphones_data
            if case == "headphones" and args.headphones_data
            else args.data / case
        )
        v = json.loads((src / "versions.json").read_text())
        assert v["selection_mode"] in {"manual_after_local_proposals", "automatic"}
        assert v["status"] == "needs_review" and v["outside_pcm_equal"] and v["other_scenes_equal"]
        assert v["cache"] == {"hits": 4, "rendered": 1, "total": 5}
        assert digest(src / "deliverables/parent-video.mp4") == v["parent_film_sha256"]
        assert digest(src / "deliverables/revised-video.mp4") == v["child_film_sha256"]
        duration = float(probe(src / "deliverables/revised-video.mp4")["format"]["duration"])
        target = ROOT / "examples/category-demo" / case
        target.mkdir(parents=True, exist_ok=True)
        for source, dest in [
            ("parent-video.mp4", "parent.mp4"),
            ("revised-video.mp4", "output.mp4"),
            ("revised-subtitles.srt", "subtitles.srt"),
            ("revised-shotbook.json", "shotbook.json"),
            ("revised-manifest.json", "manifest.json"),
            ("old.wav", "old.wav"),
            ("new.wav", "new.wav"),
        ]:
            shutil.copy2(src / "deliverables" / source, target / dest)
        for source, dest in [
            ("versions.json", "versions.json"),
            ("recommendation-cases.json", "recommendations.json"),
        ]:
            shutil.copy2(src / source, target / dest)
        if v["selection_mode"] == "manual_after_local_proposals":
            shutil.copy2(src / "manual-selection.json", target / "manual-selection.json")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "1",
                "-i",
                str(target / "output.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=360:640",
                str(target / "poster.jpg"),
            ],
            check=True,
        )
        samples.append(
            {
                "style": case,
                "title": spec["title"] + " · " + catalog[spec["style"]]["name"],
                "duration": duration,
                "description": spec["brief"]["audience"]
                + "；"
                + spec["brief"]["tone"]
                + (
                    "。本机识别与匹配尝试后，经人工回看校正选段。"
                    if v["selection_mode"] == "manual_after_local_proposals"
                    else "。本机识别与自动建议选段，仍须人工回看。"
                )
                + "许可实拍与普通合成语音，第三句重做；不是性能或功效测评。",
                "selection_mode": v["selection_mode"],
                "hook": spec["lines"][0],
                "status": "needs_review",
            }
        )
    (ROOT / "examples/category-demo/library.json").write_text(
        json.dumps(
            {
                "samples": samples,
                "human_review": "pending",
                "no_automatic_distribution": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(json.dumps(samples, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
