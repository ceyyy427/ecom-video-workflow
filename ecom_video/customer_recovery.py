"""Managed local recovery and upgrade preparation. Never activate or execute uploaded code."""

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

from . import maintenance as m
from .customer_archives import unpack_backup, unpack_release
from .customer_setup import PROJECT, release_info
from .maintenance_lock import MaintenanceBusy, acquire


def identifier(prefix):
    return prefix + "-" + uuid.uuid4().hex


class Recovery:
    def __init__(self, root, project=PROJECT):
        self.root, self.project = Path(root).resolve(), Path(project).resolve()
        self.vault = self.root.parent / (self.root.name + "-maintenance")
        if self.vault.is_symlink():
            raise ValueError("维护目录不能为软链接。")
        self.vault.mkdir(mode=0o700, exist_ok=True)
        for name in ("operations", "backups", "restores", "releases", "packages", "incoming"):
            m.local_path(self.vault, name).mkdir(mode=0o700, exist_ok=True)

    def path(self, kind, value):
        if not isinstance(value, str) or not re.fullmatch(r"[bpru]-[a-f0-9]{32}", value):
            raise KeyError(value)
        return m.local_path(self.vault, kind + "/" + value)

    def write(self, path, value):
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("x") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
        temporary.chmod(0o600)
        os.replace(temporary, path)

    def operation(self, oid):
        path = self.path("operations", oid).with_suffix(".json")
        if path.is_symlink() or not path.is_file():
            raise KeyError(oid)
        return self.operation_state(json.loads(path.read_text()))

    def operation_state(self, record):
        if record.get("state") == "running":
            try:
                fd = acquire(self.root)
            except MaintenanceBusy:
                return record
            try:
                # The exclusive owner may have completed after our first read.
                latest = json.loads(
                    self.path("operations", record["id"]).with_suffix(".json").read_text()
                )
                if latest.get("state") != "running":
                    return latest
                return {
                    **latest,
                    "state": "interrupted",
                    "message": "上次维护已中断，候选目录未启用。已完成备份保留，可重新发起新操作。",
                }
            finally:
                os.close(fd)
        return record

    def disk(self, amount):
        if amount > 10 * 1024**3 or shutil.disk_usage(self.vault).free < 2 * amount + 1024**3:
            raise m.MaintenanceError(
                "维护空间不足或数据超过10GiB页面预算，请释放空间或使用离线维护工具。"
            )

    def status(self):
        def recent(folder, filename):
            result = []
            for path in sorted(
                (self.vault / folder).glob("*/" + filename),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:50]:
                if path.is_symlink() or path.parent.is_symlink():
                    continue
                try:
                    result.append(json.loads(path.read_text()))
                except (ValueError, OSError):
                    continue
            return result

        jobs = []
        for path in sorted(
            (self.vault / "operations").glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:20]:
            if not path.is_symlink():
                jobs.append(self.operation_state(json.loads(path.read_text())))
        return {
            "application": release_info(self.project),
            "schema": m.SCHEMA_VERSION,
            "data_directory": str(self.root),
            "storage_directory": str(self.vault),
            "backups": recent("backups", "info.json"),
            "restores": recent("restores", "info.json"),
            "releases": recent("releases", "info.json"),
            "packages": recent("packages", "info.json"),
            "operations": jobs,
            "platform_writes": os.getenv("ECOM_QIANCHUAN_WRITES") == "1",
            "limits": {
                "upload_backup_bytes": 2 * 1024**3,
                "upload_package_bytes": 30 * 1024**2,
                "data_bytes": 10 * 1024**3,
            },
            "message": "准备和恢复只创建独立副本，当前数据目录不切换；完成后从新目录双击启动并人工验收。",
        }

    def start(self, kind, **arguments):
        fd = acquire(self.root, exclusive=True)
        try:
            with closing(m.readonly(self.root / "workflow.db")) as c:
                m.inspect_database(c, quiescent=True)
            oid = identifier("r")
            record = {
                "id": oid,
                "kind": kind,
                "state": "running",
                "created_at": time.time(),
                "message": "维护已开始，制作写入暂时锁定。关闭网页不会取消操作。",
            }
            path = self.path("operations", oid).with_suffix(".json")
            self.write(path, record)
            thread = threading.Thread(
                target=self.run, args=(fd, path, record, kind, arguments), daemon=True
            )
            thread.start()
            return record
        except BaseException:
            os.close(fd)
            raise

    def run(self, fd, path, record, kind, arguments):
        try:
            if kind == "backup":
                result = self.backup()
            elif kind == "restore":
                result = self.restore(arguments["backup_id"])
            elif kind == "import":
                result = self.import_backup(arguments["upload"])
            elif kind == "upgrade":
                # The backup is made before any package extraction or data preparation.
                result = self.backup()
                record.update(
                    message="升级前备份已校验；正在独立目录准备新版。",
                    backup_id=result["backup_id"],
                )
                self.write(path, record)
                result = self.upgrade(arguments["package_id"], result["backup_id"])
            else:
                raise ValueError("未知维护操作。")
            record.update(
                state="complete", result=result, message="操作完成；旧目录保留，恢复/新版尚未启动。"
            )
        except m.MaintenanceError as exc:
            record.update(state="failed", message=str(exc) + " 旧数据未覆盖，已完成备份保留。")
        except Exception:
            record.update(
                state="failed",
                message="操作未完成，旧数据未覆盖。请检查任务状态、磁盘、压缩包来源与校验值；备份如已完成会保留，失败候选目录不会启用。",
            )
        finally:
            try:
                upload = arguments.get("upload")
                if upload is not None:
                    upload.unlink(missing_ok=True)
                self.write(path, record)
            finally:
                os.close(fd)

    def backup(self):
        with closing(m.readonly(self.root / "workflow.db")) as c:
            _, tables = m.inspect_database(c, quiescent=True)
            refs = m.references(c, tables)
            size = (self.root / "workflow.db").stat().st_size + sum(
                m.local_path(self.root, n).stat().st_size for n in refs
            )
        self.disk(size)
        bid = identifier("b")
        folder = self.path("backups", bid)
        folder.mkdir(mode=0o700)
        result = m.backup(self.root, folder / "bundle")
        archive = folder / "backup.zip"
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
            for file in sorted((folder / "bundle").rglob("*")):
                if file.is_file():
                    z.write(file, file.relative_to(folder / "bundle").as_posix())
        archive.chmod(0o600)
        info = {
            **result,
            "backup_id": bid,
            "created_at": time.time(),
            "archive_sha256": m.digest(archive),
            "archive_bytes": archive.stat().st_size,
        }
        self.write(folder / "info.json", info)
        return info

    def backup_folder(self, bid):
        folder = self.path("backups", bid)
        info_path = m.local_path(folder, "info.json")
        if not info_path.is_file():
            raise KeyError(bid)
        info = json.loads(info_path.read_text())
        if info["backup_id"] != bid:
            raise KeyError(bid)
        return folder

    def verify_backup(self, bid):
        folder = self.backup_folder(bid)
        return m.verify(m.local_path(folder, "bundle"))

    def download(self, bid):
        folder = self.backup_folder(bid)
        self.verify_backup(bid)
        info = json.loads((folder / "info.json").read_text())
        archive = m.local_path(folder, "backup.zip")
        if not archive.is_file() or m.digest(archive) != info["archive_sha256"]:
            raise m.MaintenanceError("下载压缩包已损坏；原目录备份仍可校验，请重新创建一份备份。")
        return archive

    def import_backup(self, upload):
        bid = identifier("b")
        folder = self.path("backups", bid)
        folder.mkdir(mode=0o700)
        result = unpack_backup(upload, folder / "bundle")
        archive = folder / "backup.zip"
        shutil.copyfile(upload, archive)
        archive.chmod(0o600)
        info = {
            **result,
            "backup_id": bid,
            "created_at": time.time(),
            "imported": True,
            "archive_sha256": m.digest(archive),
            "archive_bytes": archive.stat().st_size,
        }
        self.write(folder / "info.json", info)
        return info

    def launch_file(self, folder, name):
        # Relative paths only; no user input enters shell text.
        path = folder / name
        path.write_text(
            '#!/bin/sh\nset -eu\ncd "$(dirname "$0")/application"\nexec ./启动剪序.command --data ../data --port 8770 "$@"\n'
        )
        path.chmod(0o700)
        path.with_suffix(".cmd").write_text(
            "@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n"
            'cd /d "%~dp0application"\ncall "启动剪序.cmd" --data ../data --port 8770 %*\n',
            encoding="utf-8",
            newline="\r\n",
        )

    def restore(self, bid):
        bundle = self.backup_folder(bid) / "bundle"
        info = m.verify(bundle)
        self.disk(info["bytes"])
        rid = identifier("r")
        folder = self.path("restores", rid)
        folder.mkdir(mode=0o700)
        # A restore is a self-contained runnable copy, so it remains independent of the original checkout.
        from .customer_setup import build_package

        archive = folder / "current-code.zip"
        package = build_package(self.project, archive)
        unpack_release(
            archive,
            folder / "application",
            package["sha256"],
            info["schema"],
            release_info(self.project)["version"],
        )
        result = m.restore(bundle, folder / "data")
        self.launch_file(folder, "启动恢复副本.command")
        info = {
            **result,
            "restore_id": rid,
            "backup_id": bid,
            "directory": str(folder),
            "data_directory": str(folder / "data"),
            "created_at": time.time(),
        }
        self.write(folder / "info.json", info)
        return info

    def upload_package(self, upload, expected):
        pid = identifier("p")
        folder = self.path("packages", pid)
        folder.mkdir(mode=0o700)
        if m.digest(upload) != expected:
            raise ValueError("安装包SHA256不匹配，未登记。")
        archive = folder / "release.zip"
        shutil.copyfile(upload, archive)
        archive.chmod(0o600)
        info = {
            "package_id": pid,
            "sha256": expected,
            "bytes": archive.stat().st_size,
            "created_at": time.time(),
        }
        self.write(folder / "info.json", info)
        return info

    def upgrade(self, pid, bid):
        package = self.path("packages", pid)
        record = json.loads(m.local_path(package, "info.json").read_text())
        bundle = self.backup_folder(bid) / "bundle"
        info = m.verify(bundle)
        self.disk(info["bytes"])
        uid = identifier("u")
        folder = self.path("releases", uid)
        folder.mkdir(mode=0o700)
        release = unpack_release(
            m.local_path(package, "release.zip"),
            folder / "application",
            record["sha256"],
            info["schema"],
            release_info(self.project)["version"],
        )
        result = m.restore(bundle, folder / "data")
        self.launch_file(folder, "启动新版本.command")
        info = {
            **result,
            "upgrade_id": uid,
            "backup_id": bid,
            "package_id": pid,
            "release": release,
            "directory": str(folder),
            "data_directory": str(folder / "data"),
            "state": "prepared_not_activated",
            "created_at": time.time(),
        }
        self.write(folder / "info.json", info)
        return info
