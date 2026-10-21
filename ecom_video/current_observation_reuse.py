"""Reuse source-bound raw v4 observations; derived action events are always rebuilt."""

import copy
import json
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from .creative import signature
from .media import digest, input_options, run_checked, safe_path

# Precisely the published, enhanced inspection before caching was introduced.
LEGACY = {
    "scanner": "73e378380d2301f94d017d6038dad1e1e9ecc981ec3b26b62a9f4cf046a1db6c",
    "adapter": "4e98d0c96d9757cbb957db115f7c68b63bb5b1f13731450d4bbdd91fa16ac80c",
    "inspection": "ebc007b21d43880bfc1417dd996be1f2c1e6ef4af845d49f4ed66e75fc1b95dd",
}
# Published runtime-only optimization before scoped processes. It already has
# sealed payload/frame manifests; unlike LEGACY, unsealed results are not adopted.
PREVIOUS_RUNTIME = {
    "scanner": "73e378380d2301f94d017d6038dad1e1e9ecc981ec3b26b62a9f4cf046a1db6c",
    "adapter": "c79ba22d4447964bd2352942aa55573ff27e1a7a9943bfa57a55557aab1277e6",
    "inspection": "65d8c37e463324067851406387781cb4516c4880ccb0d99e9a65b895a02845ab",
}


def engine(model, *, legacy=False):
    package = Path(__file__).parent
    return signature(
        {
            "model": model,
            **(
                LEGACY
                if legacy
                else {
                    "scanner": digest(package / "clip_scan.py"),
                    "adapter": digest(package / "vision_model.py"),
                    "inspection": digest(package / "product_inspection.py"),
                }
            ),
        }
    )


def payload(result):
    return signature({k: v for k, v in result.items() if k not in ("raw_manifest", "performance")})


def names(result):
    found = {n for s in result["segments"] for n in s["frames"]}
    for name in found:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", name):
            raise ValueError("invalid frame path")
    return found


def seal(result, folder):
    frames = {name: digest(Path(folder) / name) for name in sorted(names(result))}
    result["raw_manifest"] = {"version": 1, "payload_sha256": payload(result), "frames": frames}


def normalized(context):
    return {k: v for k, v in context.items() if k not in ("reference_id", "reference_path")}


def extract(source, kind, t, target, check):
    if kind == "image":
        with Image.open(source) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((640, 640))
            im.save(target)
    else:
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                *input_options(source),
                "-ss",
                str(t),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:640:force_original_aspect_ratio=decrease",
                str(target),
            ],
            check,
            timeout=30,
        )


def verify_published(root, asset, context, result, old, staging, check):
    """Old results have no frame hashes: re-extract every actual input frame first."""
    from .clip_scan import scan

    source = safe_path(root, asset["path"])
    fresh = scan(source, asset["kind"], json.loads(asset["metadata"]), staging, check)
    if len(fresh["segments"]) != len(result["segments"]) or fresh["cuts"] != result["cuts"]:
        raise ValueError("scan changed")
    for a, b in zip(fresh["segments"], result["segments"], strict=True):
        if any(a[k] != b[k] for k in ("id", "start", "end", "quality")):
            raise ValueError("sample layout changed")
        if (
            b["frames"][: len(a["frames"])] != a["frames"]
            or b["sample_times"][: len(a["sample_times"])] != a["sample_times"]
        ):
            raise ValueError("coarse frame mapping changed")
        motion = b["motion_check"]
        samples = motion["samples"]
        span = b["end"] - b["start"]
        count = min(20, max(1, int(span / 0.75)))
        times = (
            [0.0]
            if asset["kind"] == "image"
            else [round(b["start"] + 0.05 + (span - 0.1) * i / count, 4) for i in range(count + 1)]
        )
        if not samples or motion["planned_samples"] != len(times) or len(samples) > len(times):
            raise ValueError("sample coverage changed")
        if len(samples) < len(times) and samples[-1]["match"] != "different":
            raise ValueError("incomplete observation")
        for i, (sample, t) in enumerate(zip(samples, times, strict=False)):
            check()
            name = f"motion-{b['id']}-{i:02d}.jpg"
            if sample["time"] != t or sample["frame"] != name:
                raise ValueError("frame time changed")
            extract(source, asset["kind"], t, staging / name, check)
            if sample.get("comparison_frame"):
                target = sample["comparison_frame"]
                if target != Path(name).stem + "-target.jpg":
                    raise ValueError("crop path changed")
                x1, y1, x2, y2 = sample["bbox"]
                with Image.open(staging / name) as im:
                    w, h = im.size
                    im.crop(
                        (
                            max(0, round(x1 * w / 1000) - 8),
                            max(0, round(y1 * h / 1000) - 8),
                            min(w, round(x2 * w / 1000) + 8),
                            min(h, round(y2 * h / 1000) + 8),
                        )
                    ).save(staging / target)
                if digest(staging / target) != sample["appearance_evidence"]["comparison_sha256"]:
                    raise ValueError("crop proof changed")
    expected = {n: digest(staging / n) for n in names(result)}
    if any(digest(old / n) != sha for n, sha in expected.items()):
        raise ValueError("cached frame differs from actual pixels")
    return expected


def reuse(root, store, asset, context, model, folder, check):
    from .inspection_cache import _actual_inputs
    from .product_inspection import current_context
    from .vision_model import Observation

    if context.get("material_checks") != "material-checks-v1":
        return None
    root, folder = Path(root).resolve(), Path(folder).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("cache destination outside data root")
    with store.connect() as db:
        rows = db.execute(
            "SELECT * FROM media_analyses WHERE source_sha256=? AND status='ready' ORDER BY created_at DESC,rowid DESC LIMIT 64",
            (asset["sha256"],),
        ).fetchall()
    expected_engine, published = engine(model), engine(model, legacy=True)
    sealed_previous = signature({"model": model, **PREVIOUS_RUNTIME})
    for row in rows:
        check()
        try:
            result = json.loads(row["result"])
            if not (
                result.get("source_sha256") == asset["sha256"]
                and result.get("analysis_id") == row["id"]
                and result.get("model") == model
                and result.get("recognition") == "complete"
                and normalized(result.get("context", {})) == normalized(context)
                and result.get("engine") in (expected_engine, published, sealed_previous)
                and _actual_inputs(root, asset, context)
            ):
                continue
            if not current_context({"result": {**result, "context": context}}, context):
                continue
            if not 1 <= len(result["segments"]) <= 8:
                continue
            for s in result["segments"]:
                Observation.model_validate(s["observation"])
            old = safe_path(root, "analyses/" + row["id"])
            if (root / "analyses" / row["id"]).is_symlink():
                continue
            frame_names = names(result)
            if any((old / n).is_symlink() or not (old / n).is_file() for n in frame_names):
                continue
            folder.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".raw-reuse-", dir=folder.parent) as temp:
                staging = Path(temp)
                manifest = result.get("raw_manifest")
                if manifest:
                    if not (
                        manifest["version"] == 1
                        and manifest["payload_sha256"] == payload(result)
                        and set(manifest["frames"]) == frame_names
                    ):
                        continue
                    hashes = manifest["frames"]
                elif result["engine"] == published:
                    hashes = verify_published(root, asset, context, result, old, staging, check)
                else:
                    continue
                for name, sha in hashes.items():
                    check()
                    if digest(old / name) != sha:
                        raise ValueError("frame checksum changed")
                    target = staging / name
                    if not target.exists():
                        shutil.copyfile(old / name, target)
                    if digest(target) != sha or digest(old / name) != sha:
                        raise ValueError("frame changed during copy")
                if not _actual_inputs(root, asset, context):
                    raise ValueError("inputs changed during reuse")
                folder.mkdir(parents=True, exist_ok=True)
                if any((folder / n).exists() or (folder / n).is_symlink() for n in hashes):
                    continue
                for name in hashes:
                    (staging / name).replace(folder / name)
            result = copy.deepcopy(result)
            result.pop("raw_manifest", None)
            result.pop("performance", None)
            result["reused_observations_from"] = row["id"]
            result["raw_reuse_validation"] = (
                "sealed_hashes" if manifest else "published_frames_reextracted"
            )
            for s in result["segments"]:
                motion = s.get("motion_check", {})
                motion["events"] = []
                motion.pop("verified_ranges", None)
                motion.pop("material_visible_ranges", None)
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None
