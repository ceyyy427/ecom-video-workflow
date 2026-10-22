"""Explicit local handoff packaging and model configuration; never dispatch providers."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    ".env.example",
    "CUSTOMER_NOTICE.md",
    "启动剪序.command",
    "启动剪序.cmd",
    "验收剪序.cmd",
}
SCRIPTS = {
    "launch_customer.py",
    "start.sh",
    "start.ps1",
    "install_customer.py",
    "setup_p5.py",
    "vision_setup.py",
    "customer_smoke.py",
    "customer_windows.ps1",
    "customer_speech.ps1",
    "local_ocr.swift",
    "volc_voice_setup.py",
    "volc_voice_check.py",
    "qianchuan_setup.py",
}
DOCS = {
    "CUSTOMER_INSTALL.md",
    "CUSTOMER_WINDOWS.md",
    "CUSTOMER_HANDOFF.md",
    "CUSTOMER_RECOVERY.md",
    "DELIVERY_OPERATIONS.md",
    "P5_MODEL.json",
    "P5_USAGE.md",
    "P8_USAGE.md",
    "VOLC_VOICE_AUTHORIZATION.md",
    "CAPABILITY_MATRIX.md",
    "P3_USAGE.md",
    "P3_CONTRACTS.md",
}


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def customer_profile():
    os.environ.update(
        {
            "ECOM_CUSTOMER_MODE": "1",
            "ECOM_QIANCHUAN_WRITES": "0",
            "ECOM_AGENT_EXECUTION_ENABLED": "0",
            "ECOM_REVIEW_SNAPSHOTS_ENABLED": "1",
            "ECOM_EXPERIMENTS_ENABLED": "1",
        }
    )


def node_ready():
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=5, check=True
        )
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+\s*", result.stdout)
        return bool(match and int(match[1]) >= 22)
    except (OSError, subprocess.SubprocessError):
        return False


def release_info(root=PROJECT):
    import tomllib

    # Fixture packages may omit complete metadata; such packages cannot be upgraded.
    try:
        project = tomllib.loads((Path(root) / "pyproject.toml").read_text())["project"]
        from .db import SCHEMA_VERSION

        return {
            "app": project["name"],
            "version": project["version"],
            "schema_min": 1,
            "schema_max": SCHEMA_VERSION,
            "maintenance_protocol": 1,
        }
    except (OSError, ValueError, KeyError):
        return {}


def package_path_allowed(value):
    name = Path(value)
    parts = name.parts
    return (
        (len(parts) == 1 and parts[0] in ROOT_FILES)
        or (
            parts[0] == "ecom_video"
            and Path(name).suffix in (".py", ".sql", ".html", ".js", ".css", ".svg", ".json")
        )
        or (
            parts[:2] == ("render", "remotion")
            and len(parts) >= 3
            and (
                parts[2] == "src"
                or (
                    len(parts) == 3
                    and Path(name).name
                    in (
                        "render.mjs",
                        "setup-browser.mjs",
                        "package.json",
                        "package-lock.json",
                        "tsconfig.json",
                    )
                )
            )
        )
        or (len(parts) == 2 and parts[0] == "scripts" and parts[1] in SCRIPTS)
        or (len(parts) == 2 and parts[0] == "docs" and parts[1] in DOCS)
        or (parts[:2] == ("docs", "third-party") and "LICENSE" in Path(name).name)
        or (
            parts[:2] in (("vendor", "video-shotcraft"), ("vendor", "mg-styles-15"))
            and Path(name).name == "LICENSE"
        )
    )


def build_package(root, target):
    root, target = Path(root).resolve(), Path(target).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError("安装包目标已存在，不能覆盖")
    files = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root)
        parts = name.parts
        # Do not traverse or include data/dependency trees, even when they contain code files.
        selected = package_path_allowed(name)
        if not selected or any(p in ("__pycache__", "node_modules", ".venv") for p in parts):
            continue
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise ValueError("安装包源文件包含软链接")
        if path.is_file():
            files.append((name.as_posix(), path))
    manifest = {
        "format": 1,
        "release": release_info(root),
        "contains_customer_data": False,
        "models_included": False,
        "credentials_included": False,
        "files": [
            {"path": name, "sha256": sha(path), "size": path.stat().st_size} for name, path in files
        ],
    }
    try:
        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
            for name, path in files:
                archive.write(path, name)
            archive.writestr("PACKAGE.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        target.chmod(0o600)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"files": len(files), "bytes": target.stat().st_size, "sha256": sha(target)}


def build_bridge(root, target):
    """0.12.0's immutable file allowlist needs one transparent loader upgrade first.

    No code is executed during preparation. The customer starts the independent
    0.12.1 copy, then uploads the normal release there; data remains copied.
    """
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("安装包目标已存在，不能覆盖")
    excluded = {
        "启动剪序.cmd",
        "验收剪序.cmd",
        "scripts/customer_windows.ps1",
        "scripts/customer_speech.ps1",
        "docs/CUSTOMER_WINDOWS.md",
        "docs/CUSTOMER_HANDOFF.md",
    }
    with tempfile.TemporaryDirectory(prefix="ecom-bridge-") as directory:
        complete = Path(directory) / "complete.zip"
        build_package(root, complete)
        with zipfile.ZipFile(complete) as source:
            manifest = json.loads(source.read("PACKAGE.json"))
            old_version = manifest["release"]["version"]
            manifest["release"]["version"] = "0.12.1"
            values = {}
            for row in manifest["files"]:
                name = row["path"]
                if name in excluded:
                    continue
                raw = source.read(name)
                if name in ("pyproject.toml", "uv.lock", "ecom_video/api.py"):
                    raw = raw.replace(('"' + old_version + '"').encode(), b'"0.12.1"')
                if name in ("CUSTOMER_NOTICE.md", "docs/CUSTOMER_INSTALL.md"):
                    raw = (
                        "# 0.12.1 过渡版：只用于升级\n\n"
                        "从0.12.0页面准备本包并人工启动副本后，直接进入 /maintenance 登记正式0.13.1包。"
                        "这是旧校验器白名单的兼容步骤，不代表已完成正式新版升级；"
                        "不要在此过渡副本配置声音或制作商品。两阶段均先备份、恢复新目录，原版保留。\n\n"
                    ).encode() + raw
                values[name] = raw
            manifest["files"] = [
                {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in values.items()
            ]
        created = False
        try:
            with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
                created = True
                for name, raw in values.items():
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (0o100700 if name.endswith(".command") else 0o100600) << 16
                    archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED)
                archive.writestr("PACKAGE.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            target.chmod(0o600)
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
    return {
        "files": len(values),
        "bytes": target.stat().st_size,
        "sha256": sha(target),
        "version": "0.12.1",
        "purpose": "legacy_loader_bridge_only",
    }


def import_asr(source, target, expected):
    source, target = Path(source), Path(target)
    if (
        source.is_symlink()
        or target.is_symlink()
        or any(
            (source / name).is_symlink()
            or not (source / name).is_file()
            or sha(source / name) != digest
            for name, digest in expected.items()
        )
    ):
        raise ValueError("本机模型缺失或SHA256不符；未安装，不能跳过校验")
    if target.exists():
        if all(
            (target / n).is_file() and not (target / n).is_symlink() and sha(target / n) == h
            for n, h in expected.items()
        ):
            return {"verified": True, "copied": False}
        raise ValueError("目标模型目录已有不同内容；请保留旧目录，使用全新目录安装")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".asr-", dir=target.parent))
    try:
        for name, expected_sha in expected.items():
            shutil.copyfile(source / name, staging / name)
            if sha(staging / name) != expected_sha:
                raise ValueError("复制期间模型发生变化，未安装")
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"verified": True, "copied": True}


def configure_vision(name, target):
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,160}", name) or "cloud" in name.lower():
        raise ValueError("只允许有效的本机视觉模型名")
    from .vision_model import identity

    result = identity(name)
    target = Path(target)
    if target.is_symlink():
        raise ValueError("视觉配置不能是软链接")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description="客户交付包与本机模型设置")
    sub = parser.add_subparsers(dest="action", required=True)
    package = sub.add_parser("package")
    package.add_argument("--to", type=Path, required=True)
    package.add_argument("--legacy-bridge", action="store_true", help="仅供0.12.0校验器过渡到新版")
    models = sub.add_parser("models")
    models.add_argument("--asr-from", type=Path)
    models.add_argument("--vision-model")
    args = parser.parse_args()
    try:
        if args.action == "package":
            result = (build_bridge if args.legacy_bridge else build_package)(PROJECT, args.to)
        else:
            result = {}
            if args.asr_from:
                record = json.loads((PROJECT / "docs/P5_MODEL.json").read_text())
                result["asr"] = import_asr(
                    args.asr_from, PROJECT / "var/models/firered", record["files"]
                )
            if args.vision_model:
                result["vision"] = configure_vision(
                    args.vision_model, PROJECT / "var/models/vision.json"
                )
            if not result:
                raise ValueError("请选择--asr-from或--vision-model；未执行任何安装")
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
