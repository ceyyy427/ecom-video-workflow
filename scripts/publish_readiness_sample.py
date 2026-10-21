"""Publish only an explicitly pending, isolated sample and frozen checks."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    data = ap.parse_args().data.resolve()
    assert not data.is_relative_to(ROOT)
    receipt = json.loads((data / "acceptance.json").read_text())
    assert receipt["status"] == "needs_review" and receipt["cloud_calls"] == 0
    report = json.loads((data / "deliverables/audit.json").read_text())
    assert report["human_review_required"] and report["output_sha256"] == receipt["output_sha256"]
    dest = ROOT / "examples/readiness-demo/headphones"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "output.mp4",
        "audit.html",
        "audit.json",
        "shotbook.json",
        "subtitles.srt",
        "manifest.json",
    ):
        shutil.copy2(data / "deliverables" / name, dest / name)
    for source, name in (
        ("generated-script.json", "script.json"),
        ("preflight-measured.json", "preflight.json"),
        ("manual-selection.json", "manual-selection.json"),
    ):
        shutil.copy2(data / source, dest / name)
    evidence = ROOT / "docs/evidence/script-readiness"
    for name in (
        "generated-script.json",
        "preflight-empty.json",
        "preflight-unscanned.json",
        "preflight-scanned.json",
        "preflight-measured.json",
        "observations.json",
        "recommendations.json",
        "manual-selection.json",
        "alignment.json",
        "acceptance.json",
        "sources.json",
        "snapshot.json",
        "automatic-plan-rejection.json",
    ):
        shutil.copy2(data / name, evidence / name)
    shutil.copy2(data / "deliverables/audit.json", evidence / "audit.json")
    shutil.copy2(data / "deliverables/manifest.json", evidence / "manifest.json")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "2",
            "-i",
            str(dest / "output.mp4"),
            "-frames:v",
            "1",
            "-vf",
            "scale=360:640",
            str(dest / "poster.jpg"),
        ],
        check=True,
        timeout=30,
    )
    (dest.parent / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "style": "headphones",
                        "title": "耳机 · 新稿、素材缺口与综合审核",
                        "duration": receipt["duration"],
                        "description": "本机按已确认观察资料编排5句，实际识别两条实拍，经人工回看选段；本机Tingting配音与字级对齐，成片OCR抽样和实际音轨ASR。报告未覆盖项不作通过。全部确认仅验收fixture，待真人听核和审片。",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("Published pending readiness sample; no formal jobs or approvals added")


if __name__ == "__main__":
    main()
