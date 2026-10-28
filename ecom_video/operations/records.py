"""Immutable, typed-by-owner operation objects and registered backup files."""

import hashlib
import json
import re
import time
from pathlib import Path

from ..db import Conflict
from ..media import digest, safe_path

KINDS = {
    "source",
    "connection",
    "oauth_config",
    "observation_batch",
    "observation_snapshot",
    "comments",
    "comment_insights",
    "hypothesis",
    "iteration",
    "comparison",
    "research",
    "strategy",
    "image_pack",
    "publication_pack",
    "publication_registration",
    "content_matrix",
}


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def identity(kind, payload):
    if kind not in KINDS:
        raise ValueError("未知运营对象")
    raw = encoded({"kind": kind, "payload": payload})
    if len(raw.encode()) > 8 * 1024**2:
        raise ValueError("运营对象超过大小限制")
    basis = hashlib.sha256(raw.encode()).hexdigest()
    return basis[:32], basis


class Records:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    def freeze_bytes(self, kind, payload, raw, suffix):
        if (
            suffix not in (".csv", ".json", ".zip", ".png")
            or not isinstance(raw, bytes)
            or len(raw) > 256 * 1024**2
        ):
            raise ValueError("冻结文件的类型或大小不合要求")
        oid, _ = identity(kind, payload)
        relative = f"operations/{kind}/{oid}{suffix}"
        path = safe_path(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(raw).hexdigest()
        try:
            with path.open("xb") as file:
                file.write(raw)
        except FileExistsError:
            if not path.is_file() or digest(path) != sha:
                raise Conflict("冻结文件已存在且内容不同，保留原文件") from None
        return self.put(kind, payload, files=[{"path": relative, "sha256": sha}])

    def get(self, oid, kind=None):
        if not isinstance(oid, str) or not re.fullmatch("[a-f0-9]{32}", oid):
            raise ValueError("运营对象ID无效")
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM operation_objects WHERE id=?", (oid,)).fetchone()
            files = [
                dict(r)
                for r in c.execute(
                    "SELECT path,sha256 FROM operation_files WHERE object_id=? ORDER BY path",
                    (oid,),
                )
            ]
        if row is None:
            raise KeyError(oid)
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["files"] = files
        if (
            identity(result["kind"], result["payload"]) != (oid, result["basis"])
            or kind is not None
            and result["kind"] != kind
        ):
            raise ValueError("运营对象的类型或冻结摘要不符")
        for f in files:
            path = safe_path(self.root, f["path"])
            if not path.is_file() or digest(path) != f["sha256"]:
                raise ValueError("冻结来源或导出文件已改变，请从备份恢复；不会重算覆盖")
        return result

    def put(self, kind, payload, *, files=(), on_create=None):
        oid, basis = identity(kind, payload)
        if len(files) > 64:
            raise ValueError("文件数量超过限制")
        ordered = sorted([dict(f) for f in files], key=lambda f: f["path"])
        if len({f["path"] for f in ordered}) != len(ordered):
            raise ValueError("重复文件引用")
        for f in ordered:
            if (
                set(f) != {"path", "sha256"}
                or not f["path"].startswith("operations/")
                or not re.fullmatch("[a-f0-9]{64}", f["sha256"])
            ):
                raise ValueError("只能登记受管运营文件")
            path = safe_path(self.root, f["path"])
            if not path.is_file() or digest(path) != f["sha256"]:
                raise ValueError("待冻结文件不符")
        with self.store.transaction() as c:
            prior = c.execute("SELECT id FROM operation_objects WHERE basis=?", (basis,)).fetchone()
            if prior:
                existing = [
                    dict(r)
                    for r in c.execute(
                        "SELECT path,sha256 FROM operation_files WHERE object_id=? ORDER BY path",
                        (oid,),
                    )
                ]
                if existing != ordered:
                    raise Conflict("同一对象不得替换来源文件")
            else:
                if c.execute("SELECT COUNT(*) FROM operation_objects").fetchone()[0] >= 10000:
                    raise ValueError("运营记录达到容量上限，请先备份整理")
                if on_create is not None:
                    on_create(c)
                c.execute(
                    "INSERT INTO operation_objects VALUES(?,?,?,?,?)",
                    (oid, kind, basis, encoded(payload), time.time()),
                )
                c.executemany(
                    "INSERT INTO operation_files VALUES(?,?,?)",
                    [(oid, f["path"], f["sha256"]) for f in ordered],
                )
        return self.get(oid, kind)

    def listing(self, kind, limit=100):
        if kind not in KINDS or not 1 <= limit <= 500:
            raise ValueError("查询范围无效")
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM operation_objects WHERE kind=? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                )
            ]
        return [self.get(oid, kind) for oid in ids]

    def matches(self, kind, fields):
        allowed = {
            "platform",
            "account_ref",
            "content_ref",
            "hypothesis_ref",
            "candidate_id",
            "project_id",
        }
        if kind not in KINDS or not fields or set(fields) - allowed:
            raise ValueError("运营查询条件不在白名单")
        clause = " AND ".join("json_extract(payload, ?) = ?" for _ in fields)
        args = [item for key, value in fields.items() for item in ("$." + key, value)]
        with self.store.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM operation_objects WHERE kind=? AND "
                    + clause
                    + " ORDER BY created_at",
                    [kind, *args],
                )
            ]
        return [self.get(oid, kind) for oid in ids]
