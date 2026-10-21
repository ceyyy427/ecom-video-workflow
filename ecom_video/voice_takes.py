"""Completed audio receipts, bounded per project; never approvals or production inputs."""

import json
import time

from .db import Conflict
from .media import digest, safe_path

MAX_TAKES = 40
MAX_PROJECT_BYTES = 500 * 1024**2


def budget(c, pid, extra_size=0, extra_count=0):
    count = c.execute(
        "SELECT (SELECT count(*) FROM voice_takes WHERE product_id=?)+(SELECT count(*) FROM voice_patches WHERE product_id=?)",
        (pid, pid),
    ).fetchone()[0]
    if count + extra_count > MAX_TAKES:
        raise ValueError("本项目最多保留40条试听/声音版本；未发起新的云请求。")
    size = c.execute(
        "SELECT coalesce(sum(size),0) FROM (SELECT path,size FROM customer_media WHERE product_id=? UNION SELECT path,size FROM voice_takes WHERE product_id=?)",
        (pid, pid),
    ).fetchone()[0]
    size += c.execute(
        "SELECT coalesce(sum(size),0) FROM voice_patches WHERE product_id=?", (pid,)
    ).fetchone()[0]
    if size + extra_size > MAX_PROJECT_BYTES:
        raise ValueError("项目素材与保留声音总量不得超过500 MiB")


def insert(c, a, pid, draft_id, script_hash, scope, params, request_hash):
    prior = c.execute("SELECT * FROM voice_takes WHERE id=?", (a["id"],)).fetchone()
    if prior:
        if (
            prior["product_id"] != pid
            or prior["sha256"] != a["sha256"]
            or prior["path"] != a["path"]
        ):
            raise Conflict("声音版本标识已被其他内容占用")
        return
    c.execute(
        "INSERT INTO voice_takes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            a["id"],
            pid,
            draft_id,
            script_hash,
            scope,
            json.dumps(params, ensure_ascii=False),
            request_hash,
            a["path"],
            a["sha256"],
            a["size"],
            a["metadata"]["duration"],
            time.time(),
        ),
    )


def archive(c, a, pid):
    if saved_file(c, pid, a):
        return
    meta = json.loads(a["metadata"]) if isinstance(a["metadata"], str) else a["metadata"]
    source = meta.get("voice_source") or {"provider": "uploaded", "content_unverified": True}
    insert(
        c,
        {**a, "metadata": meta},
        pid,
        source.get("draft_id", ""),
        source.get("script_hash", ""),
        "full",
        source,
        "archived-" + a["id"],
    )


def saved_file(c, pid, a):
    return bool(
        c.execute(
            "SELECT 1 FROM voice_takes WHERE product_id=? AND path=? AND sha256=? AND size=?",
            (pid, a["path"], a["sha256"], a["size"]),
        ).fetchone()
    )


def listing(c, pid):
    return [
        {
            **{
                k: row[k]
                for k in (
                    "id",
                    "draft_id",
                    "script_hash",
                    "scope",
                    "sha256",
                    "size",
                    "duration",
                    "created_at",
                )
            },
            "params": json.loads(row["params"]),
        }
        for row in c.execute(
            "SELECT * FROM voice_takes WHERE product_id=? ORDER BY created_at DESC,id DESC", (pid,)
        )
    ]


def get(c, pid, aid):
    row = c.execute("SELECT * FROM voice_takes WHERE product_id=? AND id=?", (pid, aid)).fetchone()
    if not row:
        raise KeyError(aid)
    return dict(row)


def file(root, row):
    path = safe_path(root, row["path"])
    if not path.is_file() or path.is_symlink() or digest(path) != row["sha256"]:
        raise Conflict("声音版本文件缺失或已变化；未重新调用供应商")
    return path
