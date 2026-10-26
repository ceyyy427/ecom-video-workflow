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
