"""Native routes use the local session boundary; OAuth state gates the callback."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import Field

from .db import Conflict
from .distribution_api import Input
from .platforms.qianchuan_http import ProviderError
from .qianchuan_auth import CALLBACK


class Consent(Input):
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=2000)
    confirmed: bool


class FinalConsent(Consent):
    snapshot_hash: str


class NativeInput(Input):
    job_id: str
    account_id: str
    name: str
    product_id: str
    aweme_id: str
    title: str
    budget: str
    roi2_goal: str
    is_aigc: bool


class Resolution(Consent):
    outcome: str
    ad_id: str = ""


def router():
    api = APIRouter(prefix="/api/qianchuan")

    @api.get("/accounts/{aid}")
    def status(aid: str, request: Request):
        return request.app.state.qianchuan.auth.status(aid)

    @api.post("/accounts/{aid}/authorize")
    def authorize(aid: str, request: Request):
        auth = request.app.state.qianchuan.auth
        expected = str(request.base_url).rstrip("/") + CALLBACK
        if auth.config()["redirect_uri"] != expected:
            raise Conflict("配置回调地址与当前服务不一致，请从配置的 127.0.0.1 端口打开页面")
        return auth.start(aid)

    @api.get("/oauth/callback")
    def callback(request: Request, state: str = "", auth_code: str = ""):
        # Avoid validation errors echoing auth_code, and never render provider text.
        try:
            result = request.app.state.qianchuan.auth.callback(state, auth_code)
        except Exception:
            return HTMLResponse(
                '<meta charset="utf-8"><p>授权未完成或回调已失效。请关闭此页，回到千川投放页面重新发起授权。</p>',
                status_code=409,
            )
        return RedirectResponse("/qianchuan?account=" + result["account_id"], status_code=303)

    @api.post("/accounts/{aid}/verify")
    def verify(aid: str, request: Request):
        try:
            return request.app.state.qianchuan.auth.verify(aid)
        except ProviderError:
            raise Conflict("平台授权核验失败，请检查权限或重新授权") from None

    @api.post("/accounts/{aid}/disconnect")
    def disconnect(aid: str, request: Request):
        return request.app.state.qianchuan.auth.revoke(aid)

    @api.get("/tasks")
    def tasks(account_id: str, request: Request):
        return request.app.state.qianchuan.list(account_id)

    @api.post("/tasks", status_code=201)
    def create(data: NativeInput, request: Request):
        values = data.model_dump()
        values.pop("job_id")
        values.pop("account_id")
        return request.app.state.qianchuan.create(data.job_id, data.account_id, values)

    @api.get("/tasks/{sid}")
    def get(sid: str, request: Request):
        return request.app.state.qianchuan.get(sid)

    @api.post("/tasks/{sid}/upload")
    def upload(sid: str, data: Consent, request: Request):
        return request.app.state.qianchuan.upload_confirm(
            sid, data.reviewer, data.note, data.confirmed
        )

    @api.post("/tasks/{sid}/approve")
    def approve(sid: str, data: FinalConsent, request: Request):
        return request.app.state.qianchuan.approve(
            sid, data.snapshot_hash, data.reviewer, data.note, data.confirmed
        )

    @api.post("/tasks/{sid}/recheck")
    def recheck(sid: str, request: Request):
        return request.app.state.qianchuan.recheck(sid)

    @api.post("/tasks/{sid}/cancel")
    def cancel(sid: str, request: Request):
        return request.app.state.qianchuan.cancel(sid)

    @api.post("/tasks/{sid}/resolve")
    def resolve(sid: str, data: Resolution, request: Request):
        return request.app.state.qianchuan.resolve(
            sid, data.outcome, data.ad_id, data.reviewer, data.note, data.confirmed
        )

    return api
