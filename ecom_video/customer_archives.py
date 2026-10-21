"""Bounded ZIP validation, never execute an uploaded package."""

import hashlib
import json
import re
import shutil
import stat
import zipfile
from pathlib import PurePosixPath

from .maintenance import DATA_DIRS, MaintenanceError, verify

MAX_BACKUP = 10 * 1024**3
MAX_PACKAGE = 128 * 1024**2


def entries(archive, budget):
    rows = archive.infolist()
    if not 1 <= len(rows) <= 20000 or sum(x.file_size for x in rows) > budget:
        raise MaintenanceError("压缩包文件数量或解压体积超限。")
    names = set()
    result = []
    for info in rows:
        name = info.filename.rstrip("/")
        p = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (
            not name
            or p.is_absolute()
            or ".." in p.parts
            or "\\" in name
            or ":" in name
            or str(p) != name
            or name in names
            or info.flag_bits & 1
            or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
        ):
            raise MaintenanceError("压缩包包含非法路径、重复文件、加密文件或软链接。")
        names.add(name)
        if not info.is_dir():
            result.append(info)
    return result


def read_json(z, name, maximum=2 * 1024**2):
    if z.getinfo(name).file_size > maximum:
        raise MaintenanceError("压缩包清单过大。")
    return json.loads(z.read(name))


def extract(z, rows, target):
    target.mkdir(mode=0o700)
    try:
        for info in rows:
            dest = target / info.filename
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with z.open(info) as src, dest.open("xb") as out:
                while chunk := src.read(1024**2):
                    out.write(chunk)
            dest.chmod(0o700 if info.filename.endswith(".command") else 0o600)
    except BaseException:
        # Keep interrupted candidates for diagnosis, never publish as valid.
        raise


def unpack_backup(path, target):
    try:
        with zipfile.ZipFile(path) as z:
            rows = entries(z, MAX_BACKUP)
            required = sum(r.file_size for r in rows) + path.stat().st_size + 1024**3
            if shutil.disk_usage(target.parent).free < required:
                raise MaintenanceError("磁盘空间不足，未开始解压备份。")
            manifest = read_json(z, "backup.json", 16 * 1024**2)
            allowed = {"backup.json", "workflow.db", *(r["path"] for r in manifest["files"])}
            if {r.filename for r in rows} != allowed:
                raise MaintenanceError("备份压缩包与清单不一致。")
            if any(
                PurePosixPath(n).parts[0] not in DATA_DIRS
                for n in allowed - {"backup.json", "workflow.db"}
            ):
                raise MaintenanceError("备份包含非业务文件。")
            extract(z, rows, target)
        return verify(target)
    except (KeyError, TypeError, OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise MaintenanceError("备份包未通过路径、清单、数据库或SHA校验；未启用。") from None


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise MaintenanceError("版本号格式无效。")
    return tuple(map(int, value.split(".")))


def unpack_release(path, target, expected, schema, current):
    from .customer_setup import package_path_allowed
    from .maintenance import digest

    if digest(path) != expected:
        raise MaintenanceError("发行包SHA256与人工核对值不一致。")
    try:
        with zipfile.ZipFile(path) as z:
            rows = entries(z, MAX_PACKAGE)
            manifest = read_json(z, "PACKAGE.json")
            release = manifest["release"]
            if (
                manifest["format"] != 1
                or release["app"] != "ecom-video-workflow"
                or release["maintenance_protocol"] != 1
                or version(release["version"]) < version(current)
                or not release["schema_min"] <= schema <= release["schema_max"]
            ):
                raise MaintenanceError("发行包不支持当前版本、维护协议或数据结构，禁止降级。")
            records = {r["path"]: r for r in manifest["files"]}
            if len(records) != len(manifest["files"]) or {r.filename for r in rows} != {
                "PACKAGE.json",
                *records,
            }:
                raise MaintenanceError("发行清单与文件不一致。")
            required = {
                "pyproject.toml",
                "uv.lock",
                "启动剪序.command",
                "scripts/launch_customer.py",
                "ecom_video/maintenance.py",
                "ecom_video/api.py",
                "ecom_video/recovery_api.py",
            }
            if version(release["version"]) >= (0, 13, 0):
                required.update(
                    {
                        "启动剪序.cmd",
                        "验收剪序.cmd",
                        "ecom_video/host_os.py",
                        "ecom_video/windows_dpapi.py",
                        "ecom_video/customer_demo_speech.py",
                        "scripts/customer_windows.ps1",
                        "scripts/customer_speech.ps1",
                    }
                )
            if not required <= records.keys() or any(not package_path_allowed(n) for n in records):
                raise MaintenanceError("发行包缺少启动文件或包含非发行目录。")
            for name, record in records.items():
                if (
                    z.getinfo(name).file_size != record["size"]
                    or hashlib.sha256(z.read(name)).hexdigest() != record["sha256"]
                ):
                    raise MaintenanceError("发行文件SHA校验失败。")
            extract(z, rows, target)
            import tomllib

            project = tomllib.loads((target / "pyproject.toml").read_text())["project"]
            if project["name"] != release["app"] or project["version"] != release["version"]:
                raise MaintenanceError("应用版本与发行清单不一致。")
            return release
    except (KeyError, TypeError, OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise MaintenanceError(
            "发行包校验失败；请使用发行方提供的完整新版与SHA值，旧版本未修改。"
        ) from None
