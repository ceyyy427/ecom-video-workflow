"""One pinned v3-to-v4 observation migration; cached actions are never authoritative."""

import json
import shutil
import tempfile
from pathlib import Path

from .creative import signature
from .media import digest, safe_path

V3_INSPECTION_SHA256 = "20f3a82b037567a86b01360b747e78d6091cd0c0c9b65a5d4ff030ccf065a7a1"


def _actual_inputs(root, asset, context):
    source = safe_path(root, asset["path"])
    reference = safe_path(root, context["reference_path"])
    return (
        source.is_file()
        and reference.is_file()
        and digest(source) == asset["sha256"]
        and digest(reference) == context["reference_sha256"]
    )


def reuse_observations(root, store, asset, context, model, folder, check):
    """Return copied observations only after every provenance and file check passes."""
    if context.get("version") != "reference-motion-v4":
        return None
    root, folder = Path(root).resolve(), Path(folder).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("识别缓存目标超出工作目录")
    package = Path(__file__).parent
    expected_engine = signature(
        {
            "model": model,
            "scanner": digest(package / "clip_scan.py"),
            "adapter": digest(package / "vision_model.py"),
            "inspection": V3_INSPECTION_SHA256,
        }
    )
    published_engine = signature(
        {
            "model": model,
            "scanner": digest(package / "clip_scan.py"),
            "adapter": "4e98d0c96d9757cbb957db115f7c68b63bb5b1f13731450d4bbdd91fa16ac80c",
            "inspection": V3_INSPECTION_SHA256,
        }
    )
    expected_context = {**context, "version": "reference-motion-v3"}
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM media_analyses WHERE media_id=? AND status='ready' ORDER BY created_at DESC,rowid DESC",
            (asset["id"],),
        ).fetchall()
    for row in rows:
        check()
        try:
            result = json.loads(row["result"])
            if not (
                row["source_sha256"] == asset["sha256"]
                and result.get("source_sha256") == asset["sha256"]
                and result.get("analysis_id") == row["id"]
                and result.get("context") == expected_context
                and result.get("model") == model
                and result.get("engine") in (expected_engine, published_engine)
                and result.get("recognition") == "complete"
                and _actual_inputs(root, asset, context)
            ):
                continue
            old_folder = safe_path(root, f"analyses/{row['id']}")
            if (root / "analyses" / row["id"]).is_symlink():
                continue
            segments = result["segments"]
            if not isinstance(segments, list) or not 1 <= len(segments) <= 8:
                continue
            names = set()
            for segment in segments:
                frames = segment["frames"]
                if not isinstance(frames, list) or not frames:
                    raise ValueError("缓存缺少抽帧")
                for name in frames:
                    if (
                        not isinstance(name, str)
                        or not name
                        or name in (".", "..")
                        or "/" in name
                        or "\\" in name
                    ):
                        raise ValueError("缓存抽帧路径无效")
                    names.add(name)
                if segment.get("motion_check"):
                    segment["motion_check"]["events"] = []
                    segment["motion_check"].pop("verified_ranges", None)
                if not segment["quality"]["blank"]:
                    motion = segment["motion_check"]
                    if (
                        motion["version"] != "reference-motion-v3"
                        or motion["reference_sha256"] != context["reference_sha256"]
                        or not motion["samples"]
                        or any(sample["frame"] not in frames for sample in motion["samples"])
                    ):
                        raise ValueError("缓存观测来源不匹配")
            folder.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".inspection-copy-", dir=folder.parent) as temp:
                staging = Path(temp)
                for name in sorted(names):
                    check()
                    source = old_folder / name
                    if source.is_symlink() or not source.is_file():
                        raise ValueError("缓存抽帧缺失或路径无效")
                    if safe_path(old_folder, name) != source:
                        raise ValueError("缓存抽帧越界")
                    expected = digest(source)
                    shutil.copyfile(source, staging / name)
                    if digest(source) != expected or digest(staging / name) != expected:
                        raise ValueError("缓存抽帧复制期间发生变化")
                check()
                if not _actual_inputs(root, asset, context):
                    raise ValueError("缓存复制期间来源发生变化")
                folder.mkdir(parents=True, exist_ok=True)
                for name in names:
                    destination = folder / name
                    if destination.exists() or destination.is_symlink():
                        raise ValueError("新识别目录已有同名抽帧")
                for name in names:
                    (staging / name).replace(folder / name)
            result["reused_observations_from"] = row["id"]
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Missing, changed or untrusted cache is merely ineligible; scan normally.
            continue
    return None
