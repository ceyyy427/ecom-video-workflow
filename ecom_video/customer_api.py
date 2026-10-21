"""Unified customer production API; existing product and alignment routes own their confirmations."""

import re
import threading
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field, field_validator

from .creative import Brand, Brief, Strict, StyleId
from .customer import Customers, uid
from .media import EXTENSIONS, MAX_UPLOAD, digest, inspect_media, safe_path
from .shotcraft import MotionPlan, RecipeId

Role = Literal["product", "detail", "lifestyle", "evidence", "voice", "music"]


class Settings(Strict):
    material_checks: bool = False
    motion_repeat_limit: int = Field(default=2, ge=1, le=4)
    brief: Brief = Field(default_factory=lambda: Brief(format="showcase"))
    brand_name: str = Field(default="", max_length=24)
    brand: Brand | None = None
    review_context: str = Field(default="", max_length=1000)
    sfx: bool = True
    auto_select: bool = False
    reference_only: bool = False
    strict_product: bool = False
    action_timing: bool = False
    product_reference_id: str | None = Field(default=None, max_length=64)

    @field_validator("brief")
    @classmethod
    def named_format(cls, value):
        if value.format == "auto":
            raise ValueError("请选择一种客户片种")
        return value


class Create(Strict):
    title: str = Field(min_length=1, max_length=120)
    settings: Settings = Field(default_factory=Settings)


class Version(Strict):
    revision: int = Field(ge=0)


class SettingsInput(Version):
    settings: Settings


class MediaEdit(Version):
    role: Role
    source_in: float = Field(default=0, ge=0, le=600)
    note: str = Field(default="", max_length=500)


class JobVersion(Version):
    job_id: str
    board_revision: int = Field(ge=0)


class Plan(JobVersion):
    style_id: StyleId
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    alignment_id: str | None = None


class ShotChanges(Strict):
    motion_plan: MotionPlan | None = None
    shot_recipe: RecipeId | None = None
    media_id: str | None = None
    headline: str | None = Field(default=None, max_length=8)
    source_in: float | None = Field(default=None, ge=0, le=600)
    motion: Literal["static", "push", "pull", "pan_left", "pan_right"] | None = None
    fit: Literal["contain", "cover"] | None = None
    source_framing: Literal["original", "square"] | None = None
    focus_x: float | None = Field(default=None, ge=0, le=1)
    focus_y: float | None = Field(default=None, ge=0, le=1)
    treatment: Literal["auto", "hero", "macro", "split", "context", "end", "footage"] | None = None


class Revise(JobVersion):
    shot_id: str
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,64}$")
    changes: ShotChanges


def router(root, store):
    api = APIRouter(prefix="/api/customer-projects")
    service = Customers(root, store)
    preview_lock = threading.Lock()

    @api.post("/{pid}/direction-previews")
    def direction_previews(pid: str, data: Version):
        from .customer_directions import direction_input
        from .remotion_renderer import style_previews

        p = service.get(pid)
        if p["revision"] != data.revision:
            from .db import Conflict

            raise Conflict("项目已更新，请刷新风格推荐")
        source = direction_input(p)
        if not preview_lock.acquire(blocking=False):
            from .db import Conflict

            raise Conflict("风格帧正在生成，可先选择方向，稍后重试预览")
        try:
            urls = style_previews(source, root, p["recommendations"])
            return {
                key: url.replace(
                    f"/api/jobs/{source['id']}/creative/previews/",
                    f"/api/customer-projects/{pid}/direction-previews/",
                )
                for key, url in urls.items()
            }
        finally:
            preview_lock.release()

    @api.get("/{pid}/direction-previews/{key}/{style}")
    def direction_preview_file(pid: str, key: str, style: str):
        from .creative import CATALOG

        service.get(pid)
        if not re.fullmatch("[a-f0-9]{64}", key) or style not in {s["id"] for s in CATALOG}:
            raise KeyError(key)
        path = safe_path(root, f"previews/customer-{pid}/{key}/{style}.png")
        if not path.is_file():
            raise KeyError(key)
        return FileResponse(path)

    @api.get("")
    def listing():
        return service.listing()

    @api.post("", status_code=201)
    def create(data: Create):
        return service.create(data.title, data.settings.model_dump())

    @api.get("/{pid}")
    def get(pid: str):
        return service.get(pid)

    @api.get("/{pid}/preflight")
    def preflight(pid: str):
        from .readiness import project_preflight

        return project_preflight(service.get(pid))

    @api.put("/{pid}")
    def settings(pid: str, data: SettingsInput):
        return service.settings(pid, data.revision, data.settings.model_dump())

    @api.post("/{pid}/assets", status_code=201)
    def upload(
        pid: str,
        revision: Annotated[int, Form()],
        role: Annotated[Role, Form()],
        file: Annotated[UploadFile, File()],
    ):
        try:
            with store.connect() as c:
                service.row(c, pid, revision)
            name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:180]
            suffix = Path(name).suffix.lower()
            kind = next((k for k, extensions in EXTENSIONS.items() if suffix in extensions), None)
            if not kind or (kind == "audio") != (role in ("voice", "music")):
                raise ValueError("请选择匹配用途的图片、视频或音频格式")
            aid = uid()
            relative = f"customers/{pid}/media/{aid}{suffix}"
            path = safe_path(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                size = 0
                with path.open("xb") as out:
                    while chunk := file.file.read(1024**2):
                        size += len(chunk)
                        if size > MAX_UPLOAD:
                            raise HTTPException(413, "单文件不得超过100 MiB")
                        out.write(chunk)
                metadata = inspect_media(path, kind)
                return service.add_media(
                    pid,
                    revision,
                    {
                        "id": aid,
                        "name": name,
                        "path": relative,
                        "kind": kind,
                        "role": role,
                        "sha256": digest(path),
                        "size": size,
                        "metadata": metadata,
                    },
                )
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        finally:
            file.file.close()

    @api.get("/{pid}/assets/{aid}")
    def media(pid: str, aid: str):
        a = next((a for a in service.get(pid)["media"] if a["id"] == aid), None)
        if not a:
            raise KeyError(aid)
        path = safe_path(root, a["path"])
        if not path.is_file():
            raise KeyError(aid)
        return FileResponse(path)

    @api.put("/{pid}/assets/{aid}")
    def edit(pid: str, aid: str, data: MediaEdit):
        return service.edit_media(pid, aid, data.revision, data.role, data.source_in, data.note)

    @api.delete("/{pid}/assets/{aid}")
    def remove(pid: str, aid: str, data: Version):
        return service.remove_media(pid, aid, data.revision)

    @api.post("/{pid}/prepare")
    def prepare(pid: str, data: Version):
        return service.prepare(pid, data.revision)

    @api.post("/{pid}/plan")
    def plan(pid: str, data: Plan):
        return service.plan(
            pid,
            data.revision,
            data.job_id,
            data.board_revision,
            data.style_id,
            data.fingerprint,
            data.alignment_id,
        )

    @api.post("/{pid}/submit")
    def submit(pid: str, data: JobVersion):
        return service.submit(pid, data.revision, data.job_id, data.board_revision)

    @api.post("/{pid}/revise-shot", status_code=201)
    def revise(pid: str, data: Revise):
        return service.revise(pid, data.model_dump(exclude_unset=True))

    return api
