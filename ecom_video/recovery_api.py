"""Same-origin, token-protected, fixed-purpose local maintenance endpoints."""

import os
import shutil
import subprocess
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field

from .creative import Strict
from .customer_recovery import Recovery
from .maintenance import MaintenanceError, local_path
from .maintenance_lock import MaintenanceBusy


class Confirm(Strict):
    confirmed: Literal[True]


class Upgrade(Confirm):
    package_id: str = Field(pattern=r"^p-[a-f0-9]{32}$")
    trusted_code: Literal[True]


def router(root):
    api = APIRouter(prefix="/api/maintenance")
    service = Recovery(root)

    def start(kind, **arguments):
        try:
            return service.start(kind, **arguments)
        except (MaintenanceBusy, MaintenanceError):
            raise HTTPException(
                409, "存在运行任务、在途修改或其他维护操作。请暂停/取消制作并等待停止，再重试。"
            ) from None

    @api.get("/status")
    def status():
        return service.status()

    @api.get("/operations/{oid}")
    def operation(oid: str):
        return service.operation(oid)

    @api.post("/backups", status_code=202)
    def backup(data: Confirm):
        return start("backup")

    @api.post("/backups/{bid}/verify")
    def verify(bid: str, data: Confirm):
        return service.verify_backup(bid)

    @api.get("/backups/{bid}/download")
    def download(bid: str):
        return FileResponse(
            service.download(bid), filename=bid + ".zip", media_type="application/zip"
        )

    @api.post("/backups/{bid}/restore", status_code=202)
    def restore(bid: str, data: Confirm):
        service.backup_folder(bid)
        return start("restore", backup_id=bid)

    async def receive(file, maximum):
        path = service.vault / "incoming" / uuid.uuid4().hex
        size = 0
        try:
            if shutil.disk_usage(service.vault).free < 2 * (file.size or 0) + 1024**3:
                raise HTTPException(507, "磁盘空间不足以保存上传副本，未开始导入。")
            with path.open("xb") as out:
                path.chmod(0o600)
                while chunk := await file.read(1024**2):
                    size += len(chunk)
                    if size > maximum:
                        raise HTTPException(413, "上传文件超过页面大小限制，请使用离线维护工具。")
                    if shutil.disk_usage(service.vault).free < len(chunk) + 1024**3:
                        raise HTTPException(507, "磁盘余量不足，上传已停止且临时文件已清理。")
                    out.write(chunk)
            if not size:
                raise HTTPException(422, "上传文件为空。")
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @api.post("/import", status_code=202)
    async def import_backup(
        confirmed: Annotated[Literal["true"], Form()], file: Annotated[UploadFile, File()]
    ):
        upload = await receive(file, 2 * 1024**3)
        try:
            return start("import", upload=upload)
        except BaseException:
            upload.unlink(missing_ok=True)
            raise

    @api.post("/packages", status_code=201)
    async def package(
        confirmed: Annotated[Literal["true"], Form()],
        sha256: Annotated[str, Form(pattern=r"^[a-f0-9]{64}$")],
        file: Annotated[UploadFile, File()],
    ):
        upload = await receive(file, 30 * 1024**2)
        try:
            return service.upload_package(upload, sha256)
        finally:
            upload.unlink(missing_ok=True)

    @api.post("/upgrades", status_code=202)
    def upgrade(data: Upgrade):
        folder = service.path("packages", data.package_id)
        if not local_path(folder, "info.json").is_file():
            raise HTTPException(404, "安装包尚未登记。")
        return start("upgrade", package_id=data.package_id)

    @api.post("/open/{kind}/{value}")
    def open_folder(kind: Literal["backups", "restores", "releases"], value: str, data: Confirm):
        folder = service.path(kind, value)
        if not local_path(folder, "info.json").is_file():
            raise HTTPException(404, "目录未准备完成。")
        if os.sys.platform == "win32":
            os.startfile(str(folder))
            return {"opened": True}
        if os.sys.platform != "darwin":
            raise HTTPException(
                409, "本系统请按页面显示的路径打开目录；目录入口支持macOS与Windows。"
            )
        subprocess.run(["/usr/bin/open", str(folder)], check=True, timeout=5)
        return {"opened": True}

    return api
