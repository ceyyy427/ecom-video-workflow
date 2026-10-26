"""Loopback-only preview tools; the main app supplies token and maintenance guards."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field

from .content_plan import ContentBrief
from .creative import Strict
from .idea_adoption import adopt, apply_script
from .idea_media import resolve, upload
from .idea_plans import IdeaPlans
from .idea_renderer import engine_key


class Basis(Strict):
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")


class Adoption(Basis):
    option_id: str = Field(min_length=1, max_length=80)


class Script(Basis):
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: int = Field(ge=0)


def router(root, store):
    api = APIRouter()
    service = IdeaPlans(root, store)

    @api.post("/api/idea-uploads", status_code=201)
    def add_upload(
        file: Annotated[UploadFile, File()],
        source_note: Annotated[str, Form(min_length=1, max_length=500)],
        usage_confirmed: Annotated[Literal["true"], Form()],
    ):
        return upload(root, store, file.file, file.filename, source_note.strip())

    @api.post("/api/idea-plans", status_code=201)
    def create(data: ContentBrief):
        return service.create(data, resolve(root, store, data), engine=engine_key())

    @api.get("/api/idea-plans/{pid}")
    def get(pid: str):
        return service.get(pid)

    @api.post("/api/idea-plans/{pid}/previews")
    def previews(pid: str, data: Basis):
        from .db import Conflict

        current = service.get(pid)
        if (current["status"] != "ready" or current["repair_needed"]) and current["plan"][
            "engine"
        ] != engine_key():
            raise Conflict("渲染引擎已更新，请按当前输入重新生成方案；旧预览保留，不混用版本")
        return service.enqueue(pid, data.basis)

    @api.delete("/api/idea-plans/{pid}/previews")
    def cancel(pid: str):
        return service.cancel(pid)

    @api.get("/api/idea-plans/{pid}/previews/{option}/{kind}")
    def preview(pid: str, option: str, kind: str):
        path = service.preview(pid, option, kind)
        return FileResponse(
            path,
            media_type="video/mp4" if kind == "video" else "image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @api.post("/api/idea-plans/{pid}/adopt", status_code=201)
    def choose(pid: str, data: Adoption):
        return adopt(root, store, pid, data.basis, data.option_id)

    @api.post("/api/idea-plans/{pid}/script")
    def script(pid: str, data: Script):
        from .db import Conflict
        from .idea_adoption import selected_plan

        selected = selected_plan(store, data.project_id)
        if not selected or selected["plan_id"] != pid:
            raise Conflict("方案不属于当前客户项目")
        return apply_script(store, data.project_id, data.basis, data.revision)

    return api
