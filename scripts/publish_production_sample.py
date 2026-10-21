"""Publish an isolated cross-category customer workflow, without approval or stock files."""

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
    data = ap.parse_args().data.resolve()
    assert not data.is_relative_to(ROOT)
    v = json.loads((data / "versions.json").read_text())
    visual = json.loads((data / "visual.json").read_text())
    assert v["status"] == visual["status"] == "needs_review"
    assert v["other_scenes_equal"] and v["outside_pcm_equal"]
    assert v["cache"] == visual["cache"] == {"hits": 5, "rendered": 1, "total": 6}
    assert visual["other_scene_files_unchanged"] and visual["narration_and_alignment_unchanged"]
    assert v["provider_calls"] == 3 and visual["provider_calls"] == 0
    m = json.loads((data / "deliverables/revised-manifest.json").read_text())
    assert m["storyboard"]["creative"]["production"] == "narrative-v1"
    rec = json.loads((data / "recommendation-cases.json").read_text())
    assert len(rec["original"]["options"]) == 3
    target = ROOT / "examples/production-demo/headphones"
    evidence = ROOT / "docs/evidence/production-directions"
    target.mkdir(parents=True, exist_ok=True)
    for source, name in [
        ("parent-video.mp4", "parent.mp4"),
        ("revised-video.mp4", "output.mp4"),
        ("visual-video.mp4", "retake.mp4"),
        ("revised-manifest.json", "manifest.json"),
        ("revised-shotbook.json", "shotbook.json"),
        ("revised-subtitles.srt", "subtitles.srt"),
        ("old.wav", "old.wav"),
        ("new.wav", "new.wav"),
    ]:
        shutil.copy2(data / "deliverables" / source, target / name)
    assert digest(target / "output.mp4") == v["child_film_sha256"]
    assert digest(target / "retake.mp4") == visual["film_sha256"]
    shutil.copy2(data / "recommendation-cases.json", target / "recommendations.json")
    for name in (
        "versions.json",
        "visual.json",
        "acceptance.json",
        "provider-calls.json",
        "planning.json",
        "recommendation-cases.json",
        "observations.json",
        "rankings.json",
    ):
        if (data / name).exists():
            shutil.copy2(data / name, evidence / name)
    if (data / "manual-selection.json").exists():
        shutil.copy2(data / "manual-selection.json", target / "manual-selection.json")
        shutil.copy2(data / "manual-selection.json", evidence / "manual-selection.json")
    for name in ("parent-manifest.json", "revised-manifest.json", "visual-manifest.json"):
        shutil.copy2(data / "deliverables" / name, evidence / name)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "2",
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
    seconds = float(probe(target / "output.mp4")["format"]["duration"])
    assert 20 <= seconds <= 30
    rows = [
        {
            "style": "headphones",
            "duration": seconds,
            "title": "黑色耳机 · 生活种草完整编排",
            "description": "年轻学生与通勤人群，亲切自然。客户流程真实配音、本机识别与选段；保留第三句旧新试听及首镜动效修改。"
            + (
                "选段经回看片校正，原始自动建议保留。"
                if v["selection_mode"] != "automatic"
                else "自动选段建议仍待人工核对。"
            )
            + "外观与动作示例，非音质/降噪测试，商业SKU未知；仍待人工听核和审片。",
        }
    ]
    (target.parent / "library.json").write_text(
        json.dumps({"samples": rows}, ensure_ascii=False, indent=2) + "\n"
    )
    print("Published cross-category full customer workflow, still pending human review")


if __name__ == "__main__":
    main()
