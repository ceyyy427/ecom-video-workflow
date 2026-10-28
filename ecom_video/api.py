"""Same-origin local API. Only registered file identifiers are downloadable."""

import copy
import secrets
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agent_api import router as agent_router
from .analysis_api import router as analysis_router
from .customer_api import router as customer_router
from .db import Conflict, Store
from .distribution_api import router as distribution_router
from .experiment_api import router as experiment_router
from .media import EXTENSIONS, MAX_UPLOAD, digest, font_path, inspect_media, safe_path
from .product_api import router as product_router
from .qianchuan_api import router as qianchuan_router
from .qianchuan_tasks import QianchuanTasks
from .review_api import router as review_router
from .sample_library import (
    category_router,
    contextual_router,
    framing_router,
    full_library_motion_router,
    material_router,
    motion_router,
    narrative_router,
    product_cards_router,
    production_router,
    prompt_category_router,
    prompt_router,
    quality_router,
    readiness_router,
    refinement_router,
    semantic_mix_router,
)
from .sample_library import router as sample_library_router
from .shot_library import router as shot_library_router
from .volc_voice import VolcVoice
from .volc_voice_api import router as volc_voice_router

WEB = Path(__file__).parent / "web"


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=120)
    script: str = Field(min_length=1, max_length=3000)
    seconds: float = Field(default=3, ge=1, le=15)


class StoryboardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: dict
    revision: int = Field(ge=0)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=2000)
    confirmed: bool


class BodyLimit:
    def __init__(self, app, root=None):
        self.app = app
        self.root = root

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = (
            2 * 1024**3 + 1024**2
            if scope["path"] == "/api/maintenance/import"
            else 32 * 1024**2
            if scope["path"] == "/api/maintenance/packages"
            else 513 * 1024**2
            if (
                scope["path"].startswith("/api/customer-projects/")
                and scope["path"].endswith("/assets")
            )
            or scope["path"] == "/api/idea-uploads"
            else MAX_UPLOAD + 1024**2
            if scope["path"].endswith("/assets")
            else (
                11 * 1024**2
                if scope["path"].endswith(("/documents", "/reports/import"))
                or "/alignments/" in scope["path"]
                else 64 * 1024
            )
        )
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "无效 Content-Length"}, status_code=400)(
                scope, receive, send
            )
        maintenance_upload = scope["path"] in (
            "/api/maintenance/import",
            "/api/maintenance/packages",
        )

        def has_space(amount):
            return all(
                shutil.disk_usage(folder).free >= amount + 1024**3
                for folder in (self.root or tempfile.gettempdir(), tempfile.gettempdir())
            )

        if maintenance_upload and not has_space(2 * max(length, 1024**2)):
            return await JSONResponse(
                {"detail": "磁盘空间不足，未接收上传；需预留暂存、副本及至少1GiB余量。"},
                status_code=507,
            )(scope, receive, send)
        if length > limit:
            return await JSONResponse({"detail": "上传内容超过大小限制"}, status_code=413)(
                scope, receive, send
            )
        count = 0

        async def bounded_receive():
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                count += len(message.get("body", b""))
                if count > limit:
                    raise HTTPException(413, "上传内容超过大小限制")
                if maintenance_upload and not has_space(2 * len(message.get("body", b""))):
                    raise HTTPException(507, "上传已停止：磁盘空间不足，请释放空间后重试。")
            return message

        await self.app(scope, bounded_receive, send)


def create_app(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "workflow.db")
    app = FastAPI(title="剪序 · 电商视频工作台", version="0.17.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.qianchuan = QianchuanTasks(root, store)
    token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        oauth_callback = (
            request.method == "GET" and request.url.path == "/api/qianchuan/oauth/callback"
        )
        if not oauth_callback and (
            (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "仅允许同源本地访问"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
            request.headers.get("x-workflow-token", ""), token
        ):
            return JSONResponse({"detail": "页面会话已更新，请刷新页面后重试"}, status_code=403)
        import os

        from .maintenance_lock import MaintenanceBusy, acquire

        fd = None
        if request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith(
            "/api/maintenance/"
        ):
            try:
                fd = acquire(root)
            except MaintenanceBusy:
                return JSONResponse(
                    {"detail": "正在备份/恢复/准备升级，暂不接受制作修改；完成后可继续。"},
                    status_code=423,
                )
        try:
            response = await call_next(request)
        finally:
            if fd is not None:
                os.close(fd)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(BodyLimit, root=root)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == "/api/setup/voice":
            return JSONResponse(
                {"detail": "语音配置格式无效；请检查 Key、音色和表单字段。"}, status_code=422
            )
        return JSONResponse({"detail": jsonable_encoder(exc.errors())}, status_code=422)

    from .onboarding import router as setup_router

    app.include_router(setup_router(root, store))
    from .recovery_api import router as recovery_router

    app.include_router(recovery_router(root))

    @app.get("/maintenance")
    def maintenance_page():
        return FileResponse(WEB / "recovery.html")

    @app.get("/setup")
    def setup_page():
        return FileResponse(WEB / "setup.html")

    @app.exception_handler(Conflict)
    async def conflict(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(_request, _exc):
        return JSONResponse({"detail": "任务或文件不存在"}, status_code=404)

    @app.get("/api/session")
    def session():
        return {"token": token, "mode": "local_single_user"}

    @app.get("/create")
    def customer_create():
        return FileResponse(WEB / "customer.html")

    @app.get("/studio")
    def creative_studio():
        return FileResponse(WEB / "studio.html")

    @app.get("/api/health")
    def health():
        try:
            font = str(font_path())
        except ValueError:
            font = None
        return {
            "status": "ok",
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
            "font_ready": bool(font),
            "workers": store.workers(),
            "scope": "local_single_user",
        }

    @app.get("/api/system/check")
    def system_check():
        from .maintenance import check

        return check(root)

    @app.get("/api/system/install-guide")
    def install_guide():
        return FileResponse(
            WEB.parent.parent / "docs/CUSTOMER_INSTALL.md",
            media_type="text/markdown; charset=utf-8",
            filename="CUSTOMER_INSTALL.md",
        )

    @app.get("/api/system/windows-guide")
    def windows_guide():
        return FileResponse(
            WEB.parent.parent / "docs/CUSTOMER_WINDOWS.md",
            media_type="text/markdown; charset=utf-8",
            filename="CUSTOMER_WINDOWS.md",
        )

    @app.get("/api/system/handoff-guide")
    def handoff_guide():
        return FileResponse(
            WEB.parent.parent / "docs/CUSTOMER_HANDOFF.md",
            media_type="text/markdown; charset=utf-8",
            filename="CUSTOMER_HANDOFF.md",
        )

    app.include_router(sample_library_router())
    app.include_router(contextual_router())
    app.include_router(category_router())
    app.include_router(motion_router())
    app.include_router(narrative_router())
    app.include_router(production_router())
    app.include_router(prompt_router())
    app.include_router(full_library_motion_router())
    app.include_router(product_cards_router())
    app.include_router(semantic_mix_router())
    app.include_router(material_router())
    app.include_router(shot_library_router())
    app.include_router(prompt_category_router())
    app.include_router(readiness_router())
    app.include_router(quality_router())
    app.include_router(framing_router())
    app.include_router(refinement_router())

    @app.get("/api/samples")
    def samples():
        import json

        with store.connect() as c:
            rows = c.execute("""SELECT j.id,j.title,j.status,j.storyboard FROM jobs j
                JOIN artifacts a ON a.job_id=j.id AND a.kind='video'
                WHERE json_extract(j.storyboard,'$.sample')=1
                AND j.status IN ('needs_review','ready','rejected') ORDER BY j.created_at DESC""").fetchall()
        latest = {}
        for row in rows:
            board = json.loads(row["storyboard"])
            style = (board.get("creative") or {}).get("style_id", board["style"])
            if style not in latest:
                latest[style] = {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "style": style,
                }
        return list(latest.values())

    @app.get("/prompts")
    def prompts_page():
        return FileResponse(WEB / "prompts.html")

    @app.get("/samples")
    def sample_gallery():
        return FileResponse(WEB / "samples.html")

    @app.get("/api/jobs")
    def list_jobs():
        return store.list_jobs()

    @app.post("/api/jobs", status_code=201)
    def create(data: JobInput):
        return store.create_job(data.title, data.script, data.seconds)

    @app.get("/api/jobs/{jid}")
    def get(jid: str):
        return store.get(jid)

    @app.put("/api/jobs/{jid}")
    def update(jid: str, data: JobInput):
        return store.update_draft(jid, data.title, data.script, data.seconds)

    @app.post("/api/jobs/{jid}/assets", status_code=201)
    def upload(jid: str, kind: Annotated[str, Form()], file: Annotated[UploadFile, File()]):
        if store.get(jid)["status"] != "draft":
            raise Conflict("仅草稿可以上传素材")
        name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:180]
        suffix = Path(name).suffix.lower()
        if kind not in EXTENSIONS or suffix not in EXTENSIONS[kind]:
            raise ValueError("请选择支持的图片、视频或配音格式")
        aid = uuid.uuid4().hex
        relative = f"jobs/{jid}/assets/{aid}{suffix}"
        path = safe_path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with path.open("xb") as out:
                while chunk := file.file.read(1024**2):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "单文件不得超过 100 MiB")
                    out.write(chunk)
            metadata = inspect_media(path, kind)
            return store.add_asset(
                jid,
                {
                    "id": aid,
                    "name": name,
                    "path": relative,
                    "kind": kind,
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

    @app.delete("/api/jobs/{jid}/assets/{aid}")
    def remove(jid: str, aid: str):
        relative = store.remove_asset(jid, aid)
        safe_path(root, relative).unlink(missing_ok=True)
        return store.get(jid)

    @app.get("/api/jobs/{jid}/assets/{aid}")
    def asset_file(jid: str, aid: str):
        a = next((a for a in store.get(jid)["assets"] if a["id"] == aid), None)
        if not a:
            raise KeyError(aid)
        path = safe_path(root, a["path"])
        if not path.is_file():
            raise HTTPException(404, "素材文件缺失")
        return FileResponse(path)

    @app.get("/api/jobs/{jid}/storyboard")
    def storyboard(jid: str):
        from .storyboard import capabilities, default_board

        j = store.get(jid)
        return {
            "board": j["storyboard"] or default_board(j),
            "revision": j["storyboard_revision"],
            "saved": j["storyboard"] is not None,
            "capabilities": capabilities(),
        }

    @app.put("/api/jobs/{jid}/storyboard")
    def save_storyboard(jid: str, data: StoryboardInput):
        return store.save_storyboard(jid, data.board, data.revision)

    @app.post("/api/jobs/{jid}/submit")
    def submit(jid: str):
        return store.submit(jid)

    @app.post("/api/jobs/{jid}/cancel")
    def cancel(jid: str):
        return store.cancel(jid)

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: str):
        return store.retry(jid)

    @app.post("/api/jobs/{jid}/clone", status_code=201)
    def clone(jid: str):
        original = store.get(jid)
        new = store.create_job(
            original["title"],
            original["script"],
            original["seconds"],
            parent_id=jid,
            provenance=original["provenance"],
        )
        mapping = {}
        for asset in original["assets"]:
            aid = uuid.uuid4().hex
            mapping[asset["id"]] = aid
            relative = f"jobs/{new['id']}/assets/{aid}{Path(asset['path']).suffix}"
            destination = safe_path(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = safe_path(root, asset["path"])
            if not source.is_file():
                # Leave a usable draft and clearly fail; missing inputs are not fabricated.
                raise Conflict(f"原素材缺失；已保留新草稿 {new['id']}，请重新上传")
            shutil.copyfile(source, destination)
            copied = {**asset, "id": aid, "path": relative, "sha256": digest(destination)}
            store.add_asset(new["id"], copied)
        if original["storyboard"]:
            board = copy.deepcopy(original["storyboard"])
            board["previous_creative"] = board.get("creative") or board.get("previous_creative")
            if board["previous_creative"]:
                board["previous_creative"]["alignment_id"] = None
                board["creative_required"] = True
            board["creative"] = None
            for shot in board["shots"]:
                shot["asset_id"] = mapping[shot["asset_id"]]
            for obj, key in ((board, "music_id"), (board["narration"], "asset_id")):
                if obj[key]:
                    obj[key] = mapping[obj[key]]
            store.save_storyboard(new["id"], board, 0)
        return store.get(new["id"])

    @app.post("/api/jobs/{jid}/review")
    def review(jid: str, data: ReviewInput):
        return store.review(jid, data.decision, data.reviewer, data.note, data.confirmed)

    @app.get("/api/jobs/{jid}/artifacts/{kind}")
    def download(jid: str, kind: str, download: bool = False):
        a = next((a for a in store.get(jid)["artifacts"] if a["kind"] == kind), None)
        if not a:
            raise KeyError(kind)
        path = safe_path(root, a["path"])
        if not path.is_file():
            raise HTTPException(404, "产物文件缺失，请从备份恢复或重新生成")
        return FileResponse(
            path,
            filename=path.name if download else None,
            media_type="application/json" if path.suffix == ".json" else None,
        )

    from .creative_api import router as creative_router

    app.include_router(creative_router(root, store))
    app.include_router(product_router(root, store))
    app.include_router(customer_router(root, store))
    app.state.volc_voice = VolcVoice(root, store)
    from .shot_voice import ShotVoice

    app.state.shot_voice = ShotVoice(app.state.volc_voice)
    app.include_router(volc_voice_router(app.state.volc_voice, app.state.shot_voice))
    from .local_voice import LocalVoice
    from .local_voice_api import router as local_voice_router

    app.state.local_voice = LocalVoice(root, store)
    app.include_router(local_voice_router(app.state.local_voice))
    from .film_styles_api import router as film_styles_router

    app.include_router(film_styles_router())
    from .idea_api import router as idea_router

    app.include_router(idea_router(root, store))
    from .operations.api import router as operations_router

    app.include_router(operations_router(root, store))

    @app.get("/ideas")
    def ideas_page():
        return FileResponse(WEB / "ideas.html")

    app.include_router(analysis_router(root, store))
    app.include_router(agent_router(root, store))
    app.include_router(distribution_router(root, store))
    app.include_router(review_router(root, store))
    app.include_router(experiment_router(root, store))
    app.include_router(qianchuan_router())

    @app.get("/qianchuan")
    def qianchuan():
        return FileResponse(WEB / "qianchuan.html")

    @app.get("/guide")
    def guide():
        return FileResponse(WEB / "guide.html")

    @app.get("/distribution")
    def distribution():
        return FileResponse(WEB / "distribution.html")

    @app.get("/experiments")
    def experiments():
        return FileResponse(WEB / "experiments.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    return app
