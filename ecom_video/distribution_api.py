"""P2 routes inherit the application's local origin and session boundary."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .db import Conflict
from .distribution import Distribution
from .media import digest, safe_path
from .platforms.ocean_watch import OceanWatch
from .reporting import COLUMNS, MAX_BYTES, Reporting


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccountInput(Input):
    name: str = Field(min_length=1, max_length=120)
    platform: str
    advertiser_id: str
    auth_account_id: str = ""


class TaskInput(Input):
    job_id: str
    account_id: str
    name: str
    budget: str
    target_roi: str


class ApprovalInput(Input):
    snapshot_hash: str
    reviewer: str
    note: str
    confirmed: bool


class ReceiptInput(Input):
    status: str
    ad_id: str
    reviewer: str
    note: str
    confirmed: bool


class SyncInput(Input):
    account_id: str
    start_date: str
    end_date: str
    actor: str


class BindingInput(Input):
    account_id: str
    material_id: str
    job_id: str
    actor: str
    confirmed: bool


def router(root, store):
    api = APIRouter(prefix="/api")
    dist, reports = Distribution(root, store), Reporting(root, store)

    @api.get("/distribution/capabilities")
    def capabilities():
        return OceanWatch(root).capabilities()

    @api.get("/distribution/accounts")
    def accounts():
        return dist.accounts()

    @api.post("/distribution/accounts", status_code=201)
    def account(data: AccountInput):
        return dist.add_account(data.name, data.platform, data.advertiser_id, data.auth_account_id)

    @api.get("/distribution/tasks")
    def tasks():
        return dist.tasks()

    @api.post("/distribution/tasks", status_code=201)
    def create(data: TaskInput):
        return dist.create(data.job_id, data.account_id, data.name, data.budget, data.target_roi)

    @api.get("/distribution/tasks/{sid}")
    def get(sid: str):
        return dist.get(sid)

    @api.post("/distribution/tasks/{sid}/approve")
    def approve(sid: str, data: ApprovalInput):
        return dist.approve(sid, data.snapshot_hash, data.reviewer, data.note, data.confirmed)

    @api.post("/distribution/tasks/{sid}/cancel")
    def cancel(sid: str):
        return dist.cancel(sid)

    @api.post("/distribution/tasks/{sid}/receipt")
    def receipt(sid: str, data: ReceiptInput):
        return dist.receipt(sid, data.status, data.ad_id, data.reviewer, data.note, data.confirmed)

    @api.get("/distribution/tasks/{sid}/package")
    def package(sid: str):
        return FileResponse(dist.package(sid), filename=f"distribution-{sid}.zip")

    @api.get("/reports/template")
    def template():
        return Response(
            "\ufeff" + ",".join(COLUMNS) + "\n",
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="daily-material-template.csv"'},
        )

    @api.post("/reports/import", status_code=201)
    def import_csv(
        account_id: Annotated[str, Form()],
        start_date: Annotated[str, Form()],
        end_date: Annotated[str, Form()],
        actor: Annotated[str, Form()],
        confirmed: Annotated[bool, Form()],
        file: Annotated[UploadFile, File()],
        attribution_window: Annotated[str | None, Form(max_length=80)] = None,
        context_confirmed: Annotated[bool, Form()] = False,
    ):
        return reports.import_csv(
            account_id,
            start_date,
            end_date,
            file.file.read(MAX_BYTES + 1),
            actor,
            confirmed,
            attribution_window=attribution_window,
            context_confirmed=context_confirmed,
        )

    @api.get("/reports/dashboard")
    def dashboard(account_id: str, start_date: str, end_date: str):
        return reports.dashboard(account_id, start_date, end_date)

    @api.get("/reports/export")
    def export(account_id: str, start_date: str, end_date: str):
        return JSONResponse(
            reports.dashboard(account_id, start_date, end_date),
            headers={"Content-Disposition": 'attachment; filename="material-review.json"'},
        )

    @api.get("/reports/batches")
    def batches(account_id: str):
        return reports.batches(account_id)

    @api.get("/reports/batches/{bid}/source")
    def source(bid: str):
        with store.connect() as c:
            batch = c.execute("SELECT * FROM report_batches WHERE id=?", (bid,)).fetchone()
        if batch is None:
            raise KeyError(bid)
        path = safe_path(root, batch["path"])
        if not path.is_file() or digest(path) != batch["sha256"]:
            raise Conflict("报表证据缺失或校验失败")
        return FileResponse(path, filename=path.name)

    @api.post("/reports/bindings")
    def bind(data: BindingInput):
        if not data.confirmed:
            raise ValueError("请确认平台素材与本地成片一致")
        return reports.bind(data.account_id, data.material_id, data.job_id, data.actor)

    @api.post("/reports/syncs", status_code=201)
    def sync(data: SyncInput):
        return reports.enqueue(data.account_id, data.start_date, data.end_date, data.actor)

    @api.get("/reports/syncs")
    def syncs(account_id: str):
        return reports.syncs(account_id)

    return api
