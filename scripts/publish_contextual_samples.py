"""Publish completed isolated acceptance films as read-only, unapproved sample copies."""

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.creative import CATALOG
    from ecom_video.media import digest, probe, safe_path

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    base = args.data.resolve()
    out = ROOT / "examples/contextual-demo"
    out.mkdir(exist_ok=True)
    catalog = {s["id"]: s for s in CATALOG}
    samples = []
    for style in ("quiet", "editorial", "evidence"):
        src = base / style
        v = json.loads((src / "versions.json").read_text())
        assert v["status"] == "needs_review" and v["outside_pcm_equal"] and v["other_shots_equal"]
        assert v["cache"] == {"hits": 6, "rendered": 1, "total": 7}
        assert digest(src / "deliverables/parent-video.mp4") == v["parent_film_sha256"]
        assert digest(src / "deliverables/revised-video.mp4") == v["child_film_sha256"]
        duration = float(probe(src / "deliverables/revised-video.mp4")["format"]["duration"])
        assert 1 <= duration <= 120
        target = out / style
        target.mkdir(exist_ok=True)
        for source, dest in (
            ("parent-video.mp4", "parent.mp4"),
            ("revised-video.mp4", "output.mp4"),
            ("revised-subtitles.srt", "subtitles.srt"),
            ("revised-shotbook.json", "shotbook.json"),
            ("revised-manifest.json", "manifest.json"),
        ):
            shutil.copy2(src / "deliverables" / source, target / dest)
        runtime = src / "runtime"
        with sqlite3.connect("file:" + str(runtime / "workflow.db") + "?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            patch = c.execute(
                "select * from voice_patches where id=?", (v["voice_patch_id"],)
            ).fetchone()
            files = json.loads(patch["files"])
            for kind in ("old", "new"):
                audio = safe_path(runtime, files[kind]["path"])
                assert digest(audio) == files[kind]["sha256"]
                shutil.copy2(audio, target / (kind + ".wav"))
            voices = c.execute(
                "select path,metadata from assets where job_id=? and kind='audio'", (v["revised"],)
            ).fetchall()
            voice = next(
                r for r in voices if json.loads(r["metadata"]).get("customer_role") == "voice"
            )
            shutil.copy2(safe_path(runtime, voice["path"]), target / "narration.wav")
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
        shutil.copy2(src / "versions.json", target / "versions.json")
        shutil.copy2(src / "recommendations.json", target / "recommendations.json")
        samples.append(
            {
                "style": style,
                "title": catalog[style]["name"],
                "duration": duration,
                "description": catalog[style]["description"]
                + " 第三句换声后的新版，另保留父片与旧新句对比。",
                "hook": "屏幕先等等，先喝一口。",
                "status": "needs_review",
            }
        )
    (out / "library.json").write_text(
        json.dumps(
            {"samples": samples, "human_review": "pending", "no_automatic_distribution": True},
            ensure_ascii=False,
            indent=2,
        )
    )
    shutil.copy2(ROOT / "examples/client-demo/sources.json", out / "sources.json")
    print(json.dumps(samples, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
