"""Local, same-origin routes; official reads opt in separately from file operations."""

import os
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from ..maintenance_lock import MaintenanceBusy, acquire
from ..media import safe_path
from ..operations.media_pack import publication_pack, register_content
from ..operations.records import Records
from .contracts import (
    AccountInput,
    AuthorizeInput,
    OAuthConfig,
    PackInput,
    ReadInput,
    RegistrationInput,
)
from .douyin_readonly import DouyinReadOnly
from .mcp_client import sdk_status
from .oauth import DouyinAuth, enabled
from .registry import connector_catalog
from .xhs_import import add_account, freeze_source


def router(root, store):
    api = APIRouter(prefix="/api/operations")
    records = Records(root, store)
    auth = DouyinAuth(records)

    @api.get("/connectors")
    def catalog():
        return {
            "connectors": connector_catalog(),
            "mcp_sdk": sdk_status(),
            "official_reads_enabled": enabled(),
            "accounts": records.listing("connection"),
            "oauth_configs": records.listing("oauth_config"),
            "platform_writes": False,
        }

    @api.post("/accounts", status_code=201)
    def account(data: AccountInput):
        return add_account(records, data.platform, data.name, data.subject)

    @api.post("/sources", status_code=201)
    async def source(
        account_id: Annotated[str, Form()],
        declaration: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ):
        raw = await file.read(2 * 1024**2 + 1)
        return freeze_source(records, account_id, raw, file.filename or "", declaration)

    @api.post("/connectors/douyin/config", status_code=201)
    def configure(data: OAuthConfig):
        return auth.configure(data.client_key, data.client_secret.get_secret_value(), data.callback)

    @api.post("/connectors/douyin/authorize")
    def authorize(data: AuthorizeInput):
        return auth.begin(data.config_id, confirmed=data.confirmed)

    @api.get("/connectors/douyin/callback")
    def callback(
        state: str = Query(min_length=32, max_length=128),
        code: str = Query(min_length=1, max_length=2048),
    ):
        # A GET OAuth callback still writes local credentials, so it shares maintenance fencing.
        try:
            fd = acquire(root)
        except MaintenanceBusy:
            raise HTTPException(423, "正在维护数据，请完成后重新开始授权") from None
        try:
            auth.callback(state, code)
        finally:
            os.close(fd)
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><title>授权完成</title><p>本人作品只读授权完成。<a href="/operations">返回运营工作台</a></p>'
        )

    @api.post("/connectors/{account_id}/disconnect")
    def disconnect(account_id: str):
        return auth.disconnect(account_id)

    @api.post("/connectors/douyin/read", status_code=201)
    def read(data: ReadInput):
        grant = auth.grant(data.account_id)
        known = {
            r["payload"]["content_ref"]
            for r in records.matches("publication_registration", {"account_ref": data.account_id})
        }
        if set(data.content_ids) - known:
            raise ValueError("请先人工登记本账户作品ID与成片的对应关系")
        result = DouyinReadOnly().read(grant, data.content_ids)
        # Freeze counters with their definitions in D4, not in the legacy paid-ad table.
        from ..operations.observations import import_official

        return import_official(records, result)

    @api.post("/publication-packs", status_code=201)
    def pack(data: PackInput):
        return publication_pack(records, data.job_id, data.platform, data.title, data.text)

    @api.post("/registrations", status_code=201)
    def registration(data: RegistrationInput):
        return register_content(
            records, data.pack_id, data.account_id, data.content_id, data.reviewer, data.confirmed
        )

    @api.get("/objects")
    def objects(kind: str):
        return records.listing(kind)

    @api.get("/objects/{oid}")
    def object_read(oid: str):
        return records.get(oid)

    @api.get("/objects/{oid}/files/{index}")
    def object_file(oid: str, index: int):
        row = records.get(oid)
        if row["kind"] not in {"source", "publication_pack", "image_pack"} or not 0 <= index < len(
            row["files"]
        ):
            raise HTTPException(404, "文件不存在")
        path = safe_path(root, row["files"][index]["path"])
        return FileResponse(path, filename=path.name)

    return api
