"""Local diagnostics and verified data-only recovery. Never start workers or providers."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path, PurePosixPath

from .db import SCHEMA_VERSION
from .media import font_path

PROJECT = Path(__file__).resolve().parents[1]
REFERENCES = {
    "assets": ("path", "sha256"),
    "artifacts": ("path", "sha256"),
    "product_sources": ("path", "sha256"),
    "customer_media": ("path", "sha256"),
    "idea_uploads": ("path", "sha256"),
    "voice_takes": ("path", "sha256"),
    "report_batches": ("path", "sha256"),
    "review_sources": ("path", "sha256"),
    "distribution_tasks": ("package_path", "package_hash"),
}
PENDING = {
    "jobs": ("queued", "validating", "rendering", "auditing"),
    "idea_plans": ("queued", "rendering"),
    "alignments": ("running",),
    "media_analyses": ("queued", "running"),
    "agent_executions": ("queued", "running"),
    "report_syncs": ("queued", "fetching"),
    "distribution_tasks": ("queued", "exporting"),
    "qianchuan_tasks": (
        "upload_queued",
        "uploading",
        "material_pending",
        "checking_material",
        "create_queued",
        "creating",
    ),
}
DATA_DIRS = {
    "jobs",
    "products",
    "customers",
    "analyses",
    "reports",
    "distribution",
    "ideas",
    "operations",
}


class MaintenanceError(ValueError):
    """A deliberately safe, user-facing local maintenance failure."""


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def local_path(root, name):
    p = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or "\\" in name
        or p.is_absolute()
        or not p.parts
        or ".." in p.parts
        or str(p) != name
    ):
        raise MaintenanceError("非法备份路径")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise MaintenanceError("备份与恢复不接受软链接")
    return current


def root_path(value):
    path = Path(value).expanduser().absolute()
    # macOS /var itself is a system alias; resolve parent, reject a supplied root symlink.
    if path.is_symlink():
        raise MaintenanceError("数据根目录不能是软链接")
    return path.resolve()


def readonly(path, *, frozen=False):
    if not path.is_file() or path.is_symlink():
        raise MaintenanceError("数据库不存在或不是普通文件")
    query = "?mode=ro&immutable=1" if frozen else "?mode=ro"
    return sqlite3.connect(path.as_uri() + query, uri=True, timeout=5)


def inspect_database(c, *, quiescent=False):
    version = c.execute("PRAGMA user_version").fetchone()[0]
    if not 1 <= version <= SCHEMA_VERSION:
        raise MaintenanceError("数据库版本不受支持；请使用匹配版本，禁止降级")
    if c.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise MaintenanceError("数据库完整性校验失败")
    if c.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MaintenanceError("数据库引用校验失败")
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pending = {}
    for table, statuses in PENDING.items():
        if table in tables:
            count = c.execute(
                f"SELECT count(*) FROM {table} WHERE status IN ({','.join('?' * len(statuses))})",
                statuses,
            ).fetchone()[0]
            if count:
                pending[table] = count
    if (
        "resource_leases" in tables
        and c.execute(
            "SELECT count(*) FROM resource_leases WHERE expires_at>?", (time.time(),)
        ).fetchone()[0]
    ):
        pending["resource_leases"] = 1
    if quiescent and pending:
        raise MaintenanceError("仍有待执行或运行中的任务；先在页面暂停/取消并等待停止，再备份")
    return {"status": "ok", "schema": version, "pending": pending}, tables


def references(c, tables):
    result = {}

    def add(name, sha):
        local_path(Path("."), name)
        if PurePosixPath(name).parts[0] not in DATA_DIRS:
            raise MaintenanceError("数据库文件引用超出业务数据目录")
        if name in result and result[name] != sha:
            raise MaintenanceError("同一文件存在不一致的指纹")
        result[name] = sha

    for table, (path, sha) in REFERENCES.items():
        if table in tables:
            for name, fingerprint in c.execute(
                f"SELECT {path},{sha} FROM {table} WHERE {path} IS NOT NULL"
            ):
                add(name, fingerprint)
    if "voice_patches" in tables:
        for row in c.execute("SELECT files FROM voice_patches"):
            for item in json.loads(row[0]).values():
                add(item["path"], item["sha256"])

    if "idea_plans" in tables:
        for raw, previews in c.execute("SELECT plan,previews FROM idea_plans"):
            for asset in json.loads(raw)["materials"]:
                add(asset["path"], asset["sha256"])
                original = asset["metadata"].get("intake") or {}
                if original.get("original_path"):
                    add(original["original_path"], original["original_sha256"])
            for preview in json.loads(previews).values():
                for kind in ("video", "poster"):
                    if preview.get(kind):
                        add(preview[kind]["path"], preview[kind]["sha256"])

    def add_frames(aid, result):
        for segment in result.get("segments", []):
            for frame in segment.get("frames", []):
                add(f"analyses/{aid}/{frame}", None)

    frozen_ids = set()
    # Working copies and historical job snapshots retain the original receipt.
    # A library entry may have been removed after the job was frozen.
    for table in ("assets", "customer_media", "idea_uploads"):
        if table in tables:
            for (raw,) in c.execute(f"SELECT metadata FROM {table}"):
                original = json.loads(raw).get("intake") or {}
                if original.get("original_path"):
                    add(original["original_path"], original["original_sha256"])
    if "assets" in tables:
        for (raw,) in c.execute("SELECT metadata FROM assets"):
            analysis = json.loads(raw).get("content_analysis")
            if analysis:
                aid = analysis["analysis_id"]
                frozen_ids.add(aid)
                # The source media/analysis row may have been deleted after freezing this job.
                add_frames(aid, analysis)
    if "media_analyses" in tables:
        latest = set()
        for aid, mid, status, raw in c.execute(
            "SELECT id,media_id,status,result FROM media_analyses ORDER BY created_at DESC,rowid DESC"
        ):
            retained = status == "ready" or (status == "partial" and mid not in latest)
            if raw and (retained or aid in frozen_ids):
                add_frames(aid, json.loads(raw))
            latest.add(mid)
    if "operation_files" in tables:
        for path, sha in c.execute("SELECT path,sha256 FROM operation_files"):
            add(path, sha)
    return result


def check(root):
    root = root_path(root)
    checks = []

    def item(name, ok, action, required=False):
        checks.append(
            {
                "name": name,
                "status": "ok" if ok else "missing",
                "required": required,
                "action": "无需处理" if ok else action,
            }
        )

    item("Python ≥3.11", sys.version_info >= (3, 11), "安装 Python 3.11+ 后 uv sync --locked", True)
    for binary in ("ffmpeg", "ffprobe"):
        item(binary, bool(shutil.which(binary)), f"安装 {binary} 并重新启动工作流", True)
    from .customer_setup import node_ready

    item("Node.js ≥22", node_ready(), "安装Node.js 22或24，再重新启动工作流", True)
    try:
        font_path()
        font = True
    except ValueError:
        font = False
    item("中文字幕字体", font, "配置 ECOM_FONT 为可用的中文字体文件", True)
    item(
        "Remotion 依赖",
        (PROJECT / "render/remotion/node_modules/remotion").is_dir(),
        "在 render/remotion 执行 npm ci",
        True,
    )
    item(
        "本机字级对齐模型",
        all(
            (PROJECT / "var/models/firered" / n).is_file()
            for n in ("model.int8.onnx", "tokens.txt")
        ),
        "按 P8 指南安装 FireRed；配音制作前须就绪",
    )
    item(
        "Ollama 程序",
        bool(shutil.which("ollama")),
        "按 P8 指南安装本机视觉模型；也可人工选段。此检查不代表模型已加载",
    )
    existing = root
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    item(
        "磁盘余量 ≥5GiB",
        free >= 5 * 1024**3,
        "释放磁盘空间；5GiB 只是提醒线，实际预算取决于素材和分辨率",
    )
    database = {"status": "not_created", "schema": None, "pending": {}}
    if (root / "workflow.db").exists():
        try:
            # mode=ro may create/change WAL sidecars. Inspect a private copy instead.
            # A concurrent checkpoint can invalidate this diagnostic copy; it is not a backup.
            with tempfile.TemporaryDirectory(prefix="ecom-check-") as temporary:
                copied = Path(temporary) / "workflow.db"
                shutil.copyfile(local_path(root, "workflow.db"), copied)
                wal = local_path(root, "workflow.db-wal")
                if wal.exists():
                    shutil.copyfile(wal, copied.with_name("workflow.db-wal"))
                with closing(readonly(copied)) as c:
                    database, _ = inspect_database(c)
        except (ValueError, sqlite3.Error, OSError):
            database["status"] = "unsupported"
    from .volc_voice import status

    voice = {"configured": status()["configured"], "live_verified": False}
    return {
        "ready": all(x["status"] == "ok" for x in checks if x["required"])
        and database["status"] != "unsupported",
        "checks": checks,
        "database": database,
        "voice": voice,
        "free_bytes": free,
        "platform_writes_enabled": os.getenv("ECOM_QIANCHUAN_WRITES") == "1",
        "os": platform.system(),
        "scope": "local_single_user",
        "limits": [
            "未执行模型推理、浏览器启动、云请求或平台操作；依赖存在不等于端到端可用。",
            "模型、配音权限、真实听审与客户机器安装仍须单独验收；Windows 未实机验收。",
        ],
    }


def new_destination(source, target):
    target = root_path(target)
    if target == source or source in target.parents or target in source.parents:
        raise MaintenanceError("目标必须在源目录之外，不能互相包含")
    if target.exists():
        raise MaintenanceError("目标已存在；只允许恢复或备份到全新目录")
    if not target.parent.is_dir():
        raise MaintenanceError("目标父目录须已存在")
    target.mkdir(mode=0o700)
    return target


def copy_file(source, target, expected=None):
    if not source.is_file() or source.is_symlink():
        raise MaintenanceError("备份所需文件缺失或不是普通文件")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    target.chmod(0o600)
    sha = digest(target)
    if expected is not None and sha != expected:
        raise MaintenanceError("文件指纹不一致；请停止编辑后重试，禁止跳过损坏文件")
    return {"path": target.name, "sha256": sha, "size": target.stat().st_size}


def backup(root, destination):
    root = root_path(root)
    with closing(readonly(local_path(root, "workflow.db"))) as source:
        inspect_database(source, quiescent=True)
        target = new_destination(root, destination)
        try:
            db = target / "workflow.db"
            with closing(sqlite3.connect(db)) as dest:
                source.backup(dest)
            db.chmod(0o600)
            with closing(readonly(db, frozen=True)) as frozen:
                info, tables = inspect_database(frozen, quiescent=True)
                refs = references(frozen, tables)
            files = []
            for name, sha in sorted(refs.items()):
                record = copy_file(local_path(root, name), local_path(target, name), sha)
                record["path"] = name
                files.append(record)
            manifest = {
                "format": 1,
                "schema": info["schema"],
                "created_at": time.time(),
                "database": {
                    "path": "workflow.db",
                    "sha256": digest(db),
                    "size": db.stat().st_size,
                },
                "files": files,
                "excluded": [
                    "credentials",
                    "models",
                    "cache",
                    "logs",
                    "unregistered_files",
                    "source_code",
                ],
            }
            (target / "backup.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            (target / "backup.json").chmod(0o600)
            return verify(target)
        except BaseException:
            shutil.rmtree(target)
            raise


def verify(bundle):
    bundle = root_path(bundle)
    try:
        path = local_path(bundle, "backup.json")
        if path.stat().st_size > 16 * 1024**2:
            raise MaintenanceError("备份清单过大")
        manifest = json.loads(path.read_text())
        if manifest["format"] != 1 or manifest["database"]["path"] != "workflow.db":
            raise MaintenanceError("不支持的备份格式")
        items = [manifest["database"], *manifest["files"]]
        names = [r["path"] for r in items]
        if len(set(names)) != len(names):
            raise MaintenanceError("备份清单有重复文件")
        for record in items:
            file = local_path(bundle, record["path"])
            if (
                not file.is_file()
                or file.stat().st_size != record["size"]
                or digest(file) != record["sha256"]
            ):
                raise MaintenanceError("备份文件缺失、损坏或被改写")
        with closing(readonly(local_path(bundle, "workflow.db"), frozen=True)) as c:
            info, tables = inspect_database(c, quiescent=True)
            refs = references(c, tables)
        actual = {r["path"]: r["sha256"] for r in manifest["files"]}
        if (
            info["schema"] != manifest["schema"]
            or set(refs) != set(actual)
            or any(sha is not None and actual[name] != sha for name, sha in refs.items())
        ):
            raise MaintenanceError("备份清单与数据库引用不一致")
        return {
            "valid": True,
            "schema": info["schema"],
            "files": len(refs),
            "bytes": sum(r["size"] for r in items),
            "database_sha256": manifest["database"]["sha256"],
        }
    except (KeyError, TypeError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        raise MaintenanceError("无法校验备份；请检查清单、数据库和文件完整性") from exc


def restore(bundle, destination):
    bundle = root_path(bundle)
    result = verify(bundle)
    target = new_destination(bundle, destination)
    try:
        manifest = json.loads((bundle / "backup.json").read_text())
        for item in [manifest["database"], *manifest["files"]]:
            copy_file(
                local_path(bundle, item["path"]), local_path(target, item["path"]), item["sha256"]
            )
        return {
            **result,
            "restored": True,
            "workers_started": False,
            "message": "仅恢复数据；密钥、模型和平台授权需重新检查，尚未启动服务。",
        }
    except BaseException:
        shutil.rmtree(target)
        raise


def main():
    parser = argparse.ArgumentParser(description="剪序本机维护；不启动服务或外部调用")
    parser.add_argument("action", choices=("check", "backup", "verify", "restore"))
    parser.add_argument("--data", default=os.getenv("ECOM_DATA_DIR", "var"))
    parser.add_argument("--bundle")
    parser.add_argument("--to")
    args = parser.parse_args()
    try:
        if args.action == "check":
            result = check(args.data)
        elif args.action == "backup" and args.to:
            result = backup(args.data, args.to)
        elif args.action == "verify" and args.bundle:
            result = verify(args.bundle)
        elif args.action == "restore" and args.bundle and args.to:
            result = restore(args.bundle, args.to)
        else:
            raise MaintenanceError("backup 需要 --to，verify 需要 --bundle，restore 需要二者")
    except MaintenanceError as exc:
        print(
            json.dumps(
                {"ok": False, "code": "maintenance_blocked", "message": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    except (ValueError, OSError, sqlite3.Error):
        # Do not echo exception paths, database values, or user-supplied arguments.
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "maintenance_blocked",
                    "message": "操作未完成。请检查任务是否停止、版本是否匹配、文件指纹与目标目录；参见交付运维指南。",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
