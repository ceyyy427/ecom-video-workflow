"""Render an isolated detail-card variant and prove all six other shots/PCM are unchanged.

Requires the new external output of build_prompt_samples.py; never touches the database.
"""

import argparse
import copy
import json
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    from build_prompt_samples import pcm, pixels, save, variant_for

    from ecom_video.media import digest
    from ecom_video.remotion_renderer import render_remotion

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    base = args.data.resolve()
    if base.is_relative_to(root):
        parser.error("Use an external rehearsal directory")
    if any((case / "detail-single").exists() for case in base.iterdir() if case.is_dir()):
        parser.error("Detail retake already exists; never overwrite")
    results = json.loads((base / "acceptance.json").read_text())
    for style, r in results.items():
        case = base / style
        job = json.loads((case / "job.json").read_text())
        parent = case / "refined"
        m = json.loads((parent / "manifest.json").read_text())
        assert m["scenes"][1]["motion_decision"]["recipe"] == "product-detail-bracket", m["scenes"][
            1
        ]["motion_decision"]
        assert m["scenes"][2]["motion_decision"]["recipe"] == "product-fact-row", m["scenes"][2][
            "motion_decision"
        ]
        assert (
            m["scenes"][2]["motion_decision"]["quote"]["text"]
            == job["snapshot"]["script"].splitlines()[2]
        )
        assert m["scenes"][4]["motion_decision"]["recipe"] == "none"
        assert m["scenes"][3]["transition"] == "media-pass", m["scenes"][3]
        child = copy.deepcopy(job)
        child["id"] += "-detail-single"
        s = child["snapshot"]["storyboard"]["shots"][1]
        old = s["motion_plan"]["prompt_card"]
        s["motion_plan"]["prompt_card"] = variant_for(old)
        target = case / "detail-single"
        target.mkdir()
        render_remotion(child, case / "runtime", target, lambda: None)
        after = json.loads((target / "manifest.json").read_text())
        assert after["cache"] == {"hits": 6, "rendered": 1, "total": 7}
        assert pixels(parent / "scene-001.mp4") != pixels(target / "scene-001.mp4")
        assert all(
            digest(parent / f"scene-{i:03d}.mp4") == digest(target / f"scene-{i:03d}.mp4")
            for i in range(7)
            if i != 1
        )
        assert pcm(parent / "output.mp4") == pcm(target / "output.mp4")
        r["detail_retake"] = {
            "changed_index": 1,
            "from": old,
            "to": s["motion_plan"]["prompt_card"],
            "cache": after["cache"],
            "other_six_byte_equal": True,
            "whole_audio_pcm_equal": True,
            "changed_scene_pixels_differ": True,
            "video_sha256": digest(target / "output.mp4"),
        }
        r["applied_recipes"] = [s["motion_decision"]["recipe"] for s in m["scenes"]]
        r["effective_transitions"] = [s["transition"] for s in m["scenes"]]
        save(case / "acceptance.json", r)
        print(style, r["detail_retake"], flush=True)
    save(base / "acceptance.json", results)


if __name__ == "__main__":
    main()
