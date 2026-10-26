"""Reuses checked local intake; clients reference IDs, never arbitrary filesystem paths."""

import json
import shutil
import time
import uuid
from pathlib import Path

from .db import Conflict
from .media import EXTENSIONS, MAX_UPLOAD, digest, inspect_media, safe_path
from .media_intake import MAX_VIDEO_SOURCE, intake_video
from .products import encoded


def upload(root, store, stream, name, source_note):
    if not source_note.strip():
        raise ValueError("请填写素材来源与本次使用范围")
    name = (name or "upload").replace("\\", "/").split("/")[-1][:180]
    suffix = Path(name).suffix.lower()
    kind = next((k for k in ("image", "video") if suffix in EXTENSIONS[k]), None)
    if not kind:
        raise ValueError("创意预览仅接受图片与实拍视频")
    aid = uuid.uuid4().hex
    directory = Path(root) / "ideas/uploads" / aid
    directory.mkdir(parents=True)
    original = directory / ("original" + suffix)
    target = directory / ("visual.mp4" if kind == "video" else "visual" + suffix)
    try:
        limit = MAX_VIDEO_SOURCE if kind == "video" else MAX_UPLOAD
        size = 0
        with original.open("xb") as out:
            while chunk := stream.read(1024**2):
                size += len(chunk)
                if size > limit:
                    raise ValueError("素材超过单文件上传限制")
                out.write(chunk)
        if kind == "video":
            metadata = intake_video(original, target)
            metadata["intake"]["original_path"] = original.relative_to(root).as_posix()
        else:
            shutil.copyfile(original, target)
            metadata = inspect_media(target, kind)
        relative = target.relative_to(root).as_posix()
        with store.transaction() as c:
            c.execute(
                "INSERT INTO idea_uploads VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    aid,
                    name,
                    relative,
                    kind,
                    digest(target),
                    target.stat().st_size,
                    encoded(metadata),
                    source_note,
                    time.time(),
                ),
            )
        return {
            "origin": "upload",
            "id": aid,
            "name": name,
            "kind": kind,
            "source_in": 0,
            "source_note": source_note,
        }
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def resolve(root, store, brief):
    materials = []
    with store.connect() as c:
        for ref in brief.materials:
            if ref.origin == "upload":
                row = c.execute("SELECT * FROM idea_uploads WHERE id=?", (ref.id,)).fetchone()
            else:
                if not ref.project_id:
                    raise ValueError("请选择素材所属项目")
                row = c.execute(
                    "SELECT * FROM customer_media WHERE id=? AND product_id=?",
                    (ref.id, ref.project_id),
                ).fetchone()
            if not row:
                raise ValueError("素材不存在或已从原项目移除")
            item = dict(row)
            if item["kind"] not in ("image", "video"):
                raise ValueError("预览画面只能使用图片或视频")
            if isinstance(item["metadata"], str):
                item["metadata"] = json.loads(item["metadata"])
            if ref.origin == "customer":
                attach_existing_checks(c, item, ref.project_id)
            item.update(source_in=ref.source_in, origin=ref.origin, project_id=ref.project_id)
            if item["kind"] == "image" and ref.source_in:
                raise ValueError("图片不支持视频入点")
            if item["kind"] == "video" and ref.source_in + 4 > item["metadata"]["duration"] + 0.001:
                raise ValueError("素材入点后不足4秒，请换入点或补充素材；不会循环或冻结填充")
            materials.append(item)
    check_materials(root, materials)
    identities = {
        (m["metadata"]["identity"].get("sku"), m["metadata"]["identity"].get("color"))
        for m in materials
        if m["metadata"].get("identity")
    }
    if len(identities) > 1:
        raise Conflict("所选素材有不同款式或配色，请分开制作或人工核对")
    return materials


def check_materials(root, materials):
    for asset in materials:
        path = safe_path(root, asset["path"])
        if not path.is_file() or digest(path) != asset["sha256"]:
            raise ValueError("原始素材缺失或已变化，请重新选择素材生成方案")


def freeze_materials(root, materials):
    import copy
    import os

    check_materials(root, materials)
    result = copy.deepcopy(materials)

    def frozen(relative, expected):
        source = safe_path(root, relative)
        if not source.is_file() or digest(source) != expected:
            raise Conflict("待冻结原件缺失或指纹变化")
        target = safe_path(root, f"ideas/inputs/{expected}{source.suffix.lower()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(target) != expected:
                raise Conflict("冻结素材副本已损坏，请从备份恢复后再继续")
        else:
            temporary = target.with_name(target.name + "-" + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                if digest(temporary) != expected:
                    raise Conflict("素材复制时发生变化，未保存计划")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target.relative_to(root).as_posix()

    for asset in result:
        asset["path"] = frozen(asset["path"], asset["sha256"])
        intake = asset["metadata"].get("intake") or {}
        if intake.get("original_path"):
            intake["original_path"] = frozen(intake["original_path"], intake["original_sha256"])
    return result


def attach_existing_checks(c, item, pid):
    """Reuse existing current evidence; absence/staleness stays unknown, never verified."""
    from .delivery_timeline import cut_records
    from .material_suitability import complete_events, visible_ranges
    from .media_analysis import attach
    from .product_inspection import context_for, current_context

    attach(c, [item])
    analysis = item.pop("analysis", None)
    metadata = item["metadata"]
    actions = []
    visible = []
    context = context_for(c, pid, required=False)
    usable = bool(
        analysis
        and analysis["status"] == "ready"
        and analysis["source_sha256"] == item["sha256"]
        and current_context(analysis, context)
    )
    metadata["inspection_status"] = "current" if usable else "unknown_or_stale"
    if usable:
        metadata["inspection_snapshot"] = {
            "analysis_id": analysis["id"],
            "source_sha256": analysis["source_sha256"],
            "context": context,
        }
        for segment in analysis["result"].get("segments", []):
            candidate = {
                "asset_sha256": item["sha256"],
                "motion_check": segment.get("motion_check") or {},
            }
            visible += visible_ranges(candidate, context.get("reference_sha256"))
            for kind in ("pour", "open_lid", "close_lid"):
                actions += [
                    {
                        "name": kind,
                        "start": e["complete_start"],
                        "end": e["complete_end"],
                        "basis": "local_analysis",
                        "analysis_id": analysis["id"],
                    }
                    for e in complete_events(candidate, kind)
                ]
    # A manual complete-action annotation remains source evidence, not a new approval.
    for job in c.execute(
        "SELECT j.id,j.storyboard,j.snapshot FROM jobs j JOIN customer_jobs p ON p.job_id=j.id WHERE p.product_id=? AND j.storyboard IS NOT NULL",
        (pid,),
    ).fetchall():
        board = json.loads(job["storyboard"])
        snapshot = json.loads(job["snapshot"]) if job["snapshot"] else {}
        assets = snapshot.get("assets") or [
            dict(a) for a in c.execute("SELECT * FROM assets WHERE job_id=?", (job["id"],))
        ]
        lookup = {a["id"]: a for a in assets}
        for scene in board["shots"]:
            if not scene.get("source_cuts") or any(
                cut["asset_id"] not in lookup for cut in scene["source_cuts"]
            ):
                continue
            for cut in cut_records(scene, lookup):
                action = cut.get("complete_action")
                if action and cut["asset_sha256"] == item["sha256"]:
                    actions.append(
                        {
                            **action,
                            "basis": "manual_annotation",
                            "job_id": job["id"],
                            "shot_id": scene.get("shot_id"),
                        }
                    )
    metadata["complete_actions"] = list(
        {(a["name"], a["start"], a["end"]): a for a in actions}.values()
    )
    metadata["verified_visible_ranges"] = visible


def source_windows(asset, start, seconds):
    """A source interval must retain known visibility and whole actions, at original speed."""
    metadata = asset["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    visible = metadata.get("verified_visible_ranges") or []
    if visible and not any(
        r["start"] <= start + 0.001 and r["end"] >= start + seconds - 0.001 for r in visible
    ):
        raise ValueError("当前选段不在已核验的主体可见区间内，请调整入点或换素材")
    windows = []
    for action in metadata.get("complete_actions") or []:
        if start < action["end"] and start + seconds > action["start"]:
            if start > action["start"] + 0.001 or start + seconds < action["end"] - 0.001:
                raise ValueError("当前选段会截断已知完整动作，请调整入点、时长或换素材")
            window = {
                "start": max(0, action["start"] - start),
                "end": min(seconds, action["end"] - start),
                "basis": "manual" if action.get("basis") == "manual_annotation" else "analysis",
            }
            if window not in windows:
                windows.append(window)
    return windows
