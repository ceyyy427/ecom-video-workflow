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
from .delivery_plan import IdentityTarget, MediaIdentity, SourceCut
from .media import EXTENSIONS, MAX_UPLOAD, digest, inspect_media, safe_path
from .media_intake import MAX_VIDEO_SOURCE, intake_video
from .shotcraft import MotionPlan, RecipeId
from .typography import Typography

Role = Literal["product", "detail", "lifestyle", "evidence", "voice", "music"]


class Settings(Strict):
    delivery_version: Literal[1] | None = None
    identity_lock: IdentityTarget | None = None
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


class CreativeRequest(Version):
    product_revision: int = Field(ge=0)


class CreativeChoice(CreativeRequest):
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_id: Literal["overview", "scene", "details"]


class SettingsInput(Version):
    settings: Settings


class MediaEdit(Version):
    identity: MediaIdentity | None = None
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


class StyleReview(Version):
    stage: Literal["direction", "storyboard"]
    style_id: StyleId
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class ShotChanges(Strict):
    presentation: Literal["client", "legacy"] | None = None
    source_cuts: list[SourceCut] | None = Field(default=None, min_length=1, max_length=4)
    motion_plan: MotionPlan | None = None
    shot_recipe: RecipeId | None = None
    media_id: str | None = None
    headline: str | None = Field(default=None, max_length=8)
    typography: Typography | None = None
    caption_note: str | None = Field(default=None, max_length=40)
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


class ImpactChanges(ShotChanges):
    asset_id: str | None = None
    transition: Literal["cut", "wipe", "iris", "push-stack", "line-carry", "media-pass"] | None = None


class Impact(JobVersion):
    shot_id: str = Field(min_length=1, max_length=64)
    changes: ImpactChanges


class RestoreVersion(JobVersion):
    target_job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class ShotReview(JobVersion):
    basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    shot_id: str = Field(min_length=1, max_length=64)
    decision: Literal["pass", "changes_requested"]
    reason: Literal["checked", "product_visibility", "action_mismatch", "caption_timing", "voice", "facts", "other"]
    note: str = Field(min_length=1, max_length=1000)
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


def router(root, store):
    api = APIRouter(prefix="/api/customer-projects")
    service = Customers(root, store)
    preview_lock = threading.Lock()

    @api.get("/{pid}/prompt-adaptation")
    def prompt_adaptation(pid: str, card_id: str, shot_id: str | None = None):
        from .prompt_choice import adaptation
        try:
            return adaptation(service, pid, card_id, shot_id)
        except KeyError:
            raise HTTPException(404, "项目或参考卡不存在") from None

    @api.get("/{pid}/timeline")
    def editor_timeline(pid: str, job_id: str | None = None):
        from .editor_timeline import timeline

        return timeline(service, root, pid, job_id)

    @api.post("/{pid}/edit-impact")
    def edit_impact(pid: str, data: Impact):
        from .delivery_revision import impact
        value = data.model_dump()
        value["changes"] = data.changes.model_dump(exclude_unset=True)
        return impact(service, pid, value)

    @api.get("/{pid}/version-comparison")
    def comparison(pid: str, before: str, after: str):
        from .delivery_revision import compare
        return compare(service, pid, before, after)

    @api.post("/{pid}/restore-version")
    def restore_version(pid: str, data: RestoreVersion):
        from .delivery_revision import restore
        return restore(service, pid, data.model_dump())

    @api.get("/{pid}/learning-links")
    def learning_links(pid: str):
        from .delivery_revision import learning_links
        return learning_links(service, pid)

    @api.get("/{pid}/shot-reviews")
    def shot_reviews(pid: str):
        return service.get(pid)["shot_reviews"]

    @api.post("/{pid}/shot-reviews")
    def shot_review(pid: str, data: ShotReview):
        from .delivery_revision import review
        return review(service, pid, data.model_dump())

    @api.post("/{pid}/creative-proposals")
    def creative_proposals(pid: str, data: CreativeRequest):
        from .creative_proposals import proposals

        return proposals(service, pid, data.model_dump())[0]

    @api.post("/{pid}/creative-proposals/adopt", status_code=201)
    def adopt_creative(pid: str, data: CreativeChoice):
        from .creative_proposals import PlanReceipt, proposals
        from .db import Conflict

        bundle, p = proposals(service, pid, data.model_dump())
        if bundle["basis"] != data.basis:
            raise Conflict("联合方案依据已变化，请重新比较后采用")
        if p["job"] and p["job"]["status"] in ("queued", "validating", "rendering", "auditing"):
            raise Conflict("当前制作正在运行，请完成或取消后再采用新稿")
        chosen = next(c for c in bundle["candidates"] if c["id"] == data.candidate_id)
        service.products.save_draft(pid, data.product_revision, chosen["payload"], "joint-" + chosen["id"], receipt=PlanReceipt(p, bundle, chosen))
        return service.get(pid)

    @api.post("/{pid}/creative-proposals/preview")
    def preview_creative(pid: str, data: CreativeChoice):
        from .creative_preview import create_preview
        from .creative_proposals import proposals
        from .db import Conflict

        bundle, p = proposals(service, pid, data.model_dump())
        if bundle["basis"] != data.basis:
            raise Conflict("联合方案已变化，请刷新后重新预览")
        chosen = next(c for c in bundle["candidates"] if c["id"] == data.candidate_id)
        result = create_preview(root, store, p, chosen, bundle["basis"])
        latest, _ = proposals(service, pid, data.model_dump())
        if latest["basis"] != bundle["basis"]:
            raise Conflict("预览生成期间输入已变化，请重新比较后预览")
        return result

    @api.get("/{pid}/creative-proposals/previews/{key}")
    def creative_preview_file(pid: str, key: str):
        from .creative_preview import preview_path

        service.get(pid)
        return FileResponse(preview_path(root, pid, key), media_type="video/mp4")

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

    @api.post("/{pid}/handoffs", status_code=201)
    def create_handoff(pid: str, data: JobVersion):
        from .customer_handoff import Handoff

        return Handoff(root, store).create(pid, data.model_dump())

    @api.get("/{pid}/handoffs/{hid}/download")
    def download_handoff(pid: str, hid: str):
        from .customer_handoff import Handoff

        path, filename = Handoff(root, store).download(pid, hid)
        return FileResponse(path, filename=filename, media_type="application/zip")

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
            relative = f"customers/{pid}/media/{aid}{'.mp4' if kind == 'video' else suffix}"
            path = safe_path(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            original_relative = f"customers/{pid}/originals/{aid}{suffix}"
            original = safe_path(root, original_relative) if kind == "video" else path
            original.parent.mkdir(parents=True, exist_ok=True)
            try:
                size = 0
                limit = MAX_VIDEO_SOURCE if kind == "video" else MAX_UPLOAD
                with original.open("xb") as out:
                    while chunk := file.file.read(1024**2):
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, f"单文件不得超过{limit // 1024**2} MiB")
                        out.write(chunk)
                metadata = (
                    intake_video(original, path) if kind == "video" else inspect_media(path, kind)
                )
                if kind == "video":
                    metadata["intake"]["original_path"] = original_relative
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
                        "size": path.stat().st_size,
                        "metadata": metadata,
                    },
                )
            except BaseException:
                path.unlink(missing_ok=True)
                original.unlink(missing_ok=True)
                raise
        finally:
            file.file.close()

    @api.get("/{pid}/assets/{aid}/original")
    def original_file(pid: str, aid: str):
        a = next((a for a in service.get(pid)["media"] if a["id"] == aid), None)
        if not a:
            raise KeyError(aid)
        original = a["metadata"].get("intake", {}).get("original_path", a["path"])
        path = safe_path(root, original)
        if not path.is_file():
            raise KeyError(aid)
        return FileResponse(path, filename=a["name"], media_type="application/octet-stream")

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
        return service.edit_media(pid, aid, data.revision, data.role, data.source_in, data.note,
                                  identity=data.identity.model_dump() if data.identity else None)

    @api.delete("/{pid}/assets/{aid}")
    def remove(pid: str, aid: str, data: Version):
        return service.remove_media(pid, aid, data.revision)

    @api.post("/{pid}/prepare")
    def prepare(pid: str, data: Version):
        return service.prepare(pid, data.revision)

    @api.post("/{pid}/style-reviews")
    def style_review(pid: str, data: StyleReview):
        from .delivery_reviews import confirm_style

        return confirm_style(service, pid, data.model_dump())

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
