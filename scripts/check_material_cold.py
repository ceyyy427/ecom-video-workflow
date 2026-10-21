"""Compare forced inference evidence against the same licensed five-file baseline.

Read-only for both fixture roots. Never infer, approve, render or touch live var/.
"""

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_frame_evidence(before, after, sa, sb):
    from PIL import Image

    from ecom_video.media import digest

    a, b = set(sa["frames"]), set(sb["frames"])
    original_a = {f for f in a if not f.endswith("-target.jpg")}
    original_b = {f for f in b if not f.endswith("-target.jpg")}
    assert original_a == original_b, "原抽帧集合变化"
    ma, mb = sa["motion_check"], sb["motion_check"]
    assert [(s["time"], s["frame"]) for s in ma["samples"]] == [
        (s["time"], s["frame"]) for s in mb["samples"]
    ], "抽样时间/帧对应变化"
    for frame in original_a:
        assert digest(before / frame) == digest(after / frame), "Original sampled pixels changed"
    changes = []
    crops = {f for f in a | b if f.endswith("-target.jpg")}
    for frame in sorted(crops):
        hashes, boxes = [], []
        for folder, names, motion in ((before, a, ma), (after, b, mb)):
            if frame not in names:
                assert not any(s.get("comparison_frame") == frame for s in motion["samples"])
                hashes.append(None)
                boxes.append(None)
                continue
            sample = next(s for s in motion["samples"] if s.get("comparison_frame") == frame)
            expected = digest(folder / frame)
            assert sample["appearance_evidence"]["comparison_sha256"] == expected
            assert sample["frame"] in original_a
            with Image.open(folder / sample["frame"]) as im:
                w, h = im.size
                x1, y1, x2, y2 = sample["bbox"]
                box = (
                    max(0, round(x1 * w / 1000) - 8),
                    max(0, round(y1 * h / 1000) - 8),
                    min(w, round(x2 * w / 1000) + 8),
                    min(h, round(y2 * h / 1000) + 8),
                )
                image = io.BytesIO()
                im.crop(box).save(image, format="JPEG")
            assert hashlib.sha256(image.getvalue()).hexdigest() == expected
            hashes.append(expected)
            boxes.append(sample["bbox"])
        if hashes[0] != hashes[1]:
            changes.append(
                {
                    "frame": frame,
                    "status": "added"
                    if hashes[0] is None
                    else "removed"
                    if hashes[1] is None
                    else "changed",
                    "boxes_before_after": boxes,
                    "independently_reproduced": True,
                }
            )
    for names, motion in ((a, ma), (b, mb)):
        assert all(
            s["comparison_frame"] in names for s in motion["samples"] if s.get("comparison_frame")
        )
    return len(original_a), changes


def main():
    from ecom_video.material_suitability import complete_events, current_appearance, visible_ranges
    from ecom_video.media import digest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--run-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before-suffix", choices=("bounded", "forced"), default="bounded")
    parser.add_argument("--baseline-summary", type=Path)
    args = parser.parse_args()
    before, after = args.before.resolve(), args.after.resolve()
    assert not before.is_relative_to(ROOT / "var") and not after.is_relative_to(ROOT / "var")
    assert not args.output.resolve().is_relative_to(ROOT / "var")
    assert not args.output.exists(), "Keep completed evidence"
    summary = json.loads((args.run_evidence / "summary.json").read_text())
    assert summary["complete"] and len(summary["files"]) == 5
    assert summary.get("measurement_valid", True), "Invalid benchmark clocks"
    old_times = {
        n: float(t)
        for n, t in re.findall(
            r"DONE (\S+) ([\d.]+) sec",
            (ROOT / "docs/evidence/material-suitability/bounded-inference.log").read_text(),
        )
    }
    if args.baseline_summary:
        baseline = json.loads(args.baseline_summary.read_text())
        assert baseline["complete"] and len(baseline["files"]) == 5
        assert baseline.get("measurement_valid", True), "Invalid baseline clocks"
        old_times = {r["name"]: r["seconds"] for r in baseline["files"]}
    results = []
    for row in summary["files"]:
        assert row.get("measurement_valid", True), "Invalid file timing"
        name = row["name"]
        x = json.loads((before / (name + "." + args.before_suffix + ".json")).read_text())
        y = json.loads((after / (name + ".forced.json")).read_text())
        assert y["status"] == "ready" and y["result"]["recognition"] == "complete"
        a, b = x["result"], y["result"]
        assert a["model"] == b["model"] and a["source_sha256"] == b["source_sha256"]
        assert a["context"] == b["context"]
        assert a["cuts"] == b["cuts"] and len(a["segments"]) == len(b["segments"])
        assert row["cache"]["forced_inference"] and row["cache"]["hits"] == 0
        assert b["performance"]["execution"]["release_errors"] == 0
        assert row["model_calls"] > 0
        assert digest(before / "runtime/analyses" / x["id"] / "reference.jpg") == digest(
            after / "runtime/analyses" / y["id"] / "reference.jpg"
        ), "Reference thumbnail pixels changed"
        shared_frames = 0
        derived_crop_changes = []
        feature_changes = []
        states_equal = True
        ranges_equal = True
        event_equal = True
        observations_equal = True
        intervals = []
        for sa, sb in zip(a["segments"], b["segments"], strict=True):
            assert all(sa[k] == sb[k] for k in ("start", "end", "quality"))
            ma, mb = sa["motion_check"], sb["motion_check"]
            assert ma["planned_samples"] == mb["planned_samples"]
            observations_equal &= sa["observation"] == sb["observation"]
            ranges_equal &= ma.get("material_visible_ranges", []) == mb.get(
                "material_visible_ranges", []
            )
            event_equal &= ma["events"] == mb["events"]

            def judgments(m):
                return [
                    {
                        k: s.get(k)
                        for k in (
                            "time",
                            "match",
                            "target_count",
                            "visibility",
                            "bbox",
                            "flow",
                            "lid",
                            "handling_lid",
                        )
                    }
                    for s in m["samples"]
                ]

            states_equal &= judgments(ma) == judgments(mb)
            for old_sample, new_sample in zip(ma["samples"], mb["samples"], strict=False):
                if old_sample.get("appearance_evidence") != new_sample.get("appearance_evidence"):
                    feature_changes.append(
                        {
                            "time": new_sample["time"],
                            "before": old_sample.get("appearance_evidence"),
                            "after": new_sample.get("appearance_evidence"),
                        }
                    )
            count, crop_changes = verify_frame_evidence(
                before / "runtime/analyses" / x["id"],
                after / "runtime/analyses" / y["id"],
                sa,
                sb,
            )
            shared_frames += count
            derived_crop_changes.extend(crop_changes)
            candidate = {"asset_sha256": b["source_sha256"], "motion_check": mb}
            reference = b["context"]["reference_sha256"]
            assert current_appearance(candidate, reference)
            intervals += visible_ranges(candidate, reference)
            if name == "pour.mp4":
                assert len(mb["samples"]) == mb["planned_samples"] == 11
                assert ma["events"] == mb["events"]
                events = complete_events(candidate, "pour")
                assert (
                    events
                    and events[0]["complete_start"]
                    < events[0]["start"]
                    < events[0]["end"]
                    < events[0]["complete_end"]
                )
            if name in ("other.mp4", "wide.mp4"):
                assert not visible_ranges(candidate, reference), name
        results.append(
            {
                "name": name,
                "historical_before_seconds": old_times[name],
                "forced_after_seconds": row["seconds"],
                "backend_requests": row["model_calls"],
                "same_model_source_reference": True,
                "reference_thumb_sha_verified": True,
                "shared_frame_sha_verified": shared_frames,
                "derived_crop_changes": derived_crop_changes,
                "sampled_judgments_equal": states_equal,
                "usable_ranges_equal": ranges_equal,
                "actions_equal": event_equal,
                "sparse_observations_equal": observations_equal,
                "new_usable_ranges": intervals,
                "permanent_evidence_differences": feature_changes,
                "performance": b["performance"],
            }
        )
    report = {
        "before_suffix": args.before_suffix,
        "baseline_summary": str(args.baseline_summary) if args.baseline_summary else None,
        "historical_actual_before_seconds": sum(old_times.values()),
        "fresh_forced_after_seconds": summary["seconds"],
        "fresh_five_file_before_repeated_this_round": False,
        "speedup_ratio": round(sum(old_times.values()) / summary["seconds"], 3),
        "files": results,
        "negative_other_and_tiny_subject_excluded": True,
        "complete_pour_evidence_retained": True,
        "business_cache_hits": sum(r["cache"]["hits"] for r in summary["files"]),
        "backend_chat_calls": summary["backend_chat_calls"],
        "human_listening_and_film_review": "pending",
        "computer_use": False,
        "platform_writes": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in report.items() if k != "files"}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
