"""Publish three verified edited films to the read-only, unapproved gallery."""

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
    from scripts.build_narrative_samples import corrected_provenance

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    args = ap.parse_args()
    records = json.loads((args.data / "acceptance.json").read_text())
    target = ROOT / "examples/narrative-demo"
    evidence = ROOT / "docs/evidence/narrative-samples"
    evidence.mkdir(parents=True, exist_ok=True)
    rows = []
    for style, seconds, title, description in [
        (
            "cinema",
            26,
            "克制质感 · 倒一杯，慢下来",
            "全幅实拍、留白宋体、缓叙口播；倒水与拿起优先，手绘划线和语义卡片轻点题",
        ),
        (
            "social",
            27,
            "生活种草 · 给工作留一点空隙",
            "大字开场、暖色场景、轻快口播；拿起与放回接力，底边推叠换章",
        ),
        (
            "lab",
            28,
            "细节解说 · 先看杯口，再看动作",
            "分章观察、局部扫描和焦点框、清晰口播；拿起和放下与原声逐词对齐",
        ),
    ]:
        record = records[style]
        assert record["status"] == "needs_review" and record["duration"] == seconds
        assert all(
            record[k]
            for k in (
                "other_scene_files_unchanged",
                "raw_narration_unchanged",
                "word_anchors_unchanged",
            )
        )
        assert record["cache"]["rendered"] == 1
        assert record["provider_calls"] == record["database_writes"] == 0
        src = args.data / style
        old = ROOT / "examples/client-demo" / style
        assert digest(old / "output.mp4") == record["old_sample_sha256"]
        assert digest(src / "film/output.mp4") == record["film_sha256"]
        # Reconcile metadata against the actual recut ledger before publishing. No pixels,
        # words, approvals or cache keys are changed; keep both previous and revised cuts.
        original = json.loads((old / "preview-job.json").read_text())["snapshot"]
        prepared = json.loads((src / "preview-job.json").read_text())["snapshot"]
        for asset in prepared["assets"]:
            assert digest(src / "runtime" / asset["path"]) == asset["sha256"]
        for edit in record["source_edits"]:
            assert digest(ROOT / edit["source"]) == edit["source_sha256"]
        provenance = corrected_provenance(
            original["provenance"], prepared["storyboard"], record["source_edits"]
        )
        (evidence / f"{style}-source-reconciliation.json").write_text(
            json.dumps(
                {
                    "basis": "verified prepared asset SHA and actual recut ledger; metadata reconciliation only",
                    "before": original["provenance"],
                    "after": provenance,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        folder = target / style
        folder.mkdir(parents=True, exist_ok=True)
        for source, name in [
            (old / "output.mp4", "parent.mp4"),
            (src / "single/output.mp4", "retake.mp4"),
            (old / "voice-source.json", "voice-source.json"),
        ]:
            shutil.copy2(source, folder / name)
        for name in (
            "output.mp4",
            "narration.wav",
            "shotbook.json",
            "manifest.json",
            "subtitles.srt",
        ):
            if name in ("manifest.json", "shotbook.json"):
                payload = json.loads((src / "film" / name).read_text())
                payload["provenance" if name == "manifest.json" else "script_source"] = provenance
                (folder / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            else:
                shutil.copy2(src / "film" / name, folder / name)
        for name in ("acceptance.json", "creative-timing.json"):
            shutil.copy2(src / name, evidence / f"{style}-{name}")
        for phase in ("film", "single"):
            payload = json.loads((src / phase / "manifest.json").read_text())
            payload["provenance"] = provenance
            (evidence / f"{style}-{phase}-manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "3",
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
        assert abs(duration - seconds) < 0.05
        rows.append(
            {
                "style": style,
                "title": title,
                "duration": duration,
                "description": description
                + "。同一透明杯系列的许可实拍；非材质、容量或性能测评。待人工听审。",
            }
        )
    (target / "library.json").write_text(
        json.dumps({"samples": rows}, ensure_ascii=False, indent=2) + "\n"
    )
    print("Published three 26/27/28s edited films, pending human review")


if __name__ == "__main__":
    main()
