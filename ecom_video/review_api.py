"""Explicit local freeze/read/export operations; inherits loopback/session security."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .creative_features import Features
from .db import Conflict
from .review_contracts import (
    ALGORITHM_VERSION,
    FEATURE_VERSION,
    MAX_CELLS,
    MAX_MATERIALS,
    MAX_PAYLOAD,
    MAX_ROWS,
    MAX_SOURCE_BYTES,
    FreezeInput,
    LabelInput,
    enabled,
)
from .review_snapshots import Reviews


def checked(fn):
    try:
        return fn()
    except Conflict as exc:
        status, code, message = 409, "REVIEW_CONFLICT", str(exc)
    except KeyError:
        status, code, message = 404, "REVIEW_NOT_FOUND", "复盘、创意特征或来源记录不存在。"
    except ValueError as exc:
        status, code, message = 422, "REVIEW_INVALID_INPUT", str(exc)
    except Exception:
        status, code, message = 500, "REVIEW_INTERNAL_ERROR", "本机复盘处理未完成，请检查服务状态。"
    return JSONResponse(
        {"detail": message, "error": {"code": code, "safe_message": message, "retryable": False}},
        status_code=status,
    )


async def body(request):
    try:
        raw = await request.body()
        if len(raw) > 64 * 1024:
            raise ValueError
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("输入须为不超过 64 KiB 的有效 JSON。") from None


def router(root, store):
    api = APIRouter(prefix="/api")
    reviews = Reviews(root, store)
    features = Features(store)

    def gate():
        if not enabled():
            raise HTTPException(404)

    @api.get("/reviews/capabilities")
    def capabilities():
        return {
            "schema_version": 1,
            "phase": "P15",
            "enabled": enabled(),
            "algorithm_version": ALGORITHM_VERSION,
            "feature_version": FEATURE_VERSION,
            "cloud_calls": False,
            "platform_writes": False,
            "causal_inference": False,
            "experiment_apply": False,
            "create_schema": FreezeInput.model_json_schema(),
            "label_schema": LabelInput.model_json_schema(),
            "limits": {
                "days": 31,
                "rows": MAX_ROWS,
                "materials": MAX_MATERIALS,
                "material_days": MAX_CELLS,
                "payload_bytes": MAX_PAYLOAD,
                "source_bytes": MAX_SOURCE_BYTES,
            },
        }

    @api.post("/reviews/snapshots")
    async def create(request: Request):
        gate()
        try:
            value = await body(request)
        except ValueError:
            return JSONResponse(
                {
                    "detail": "输入须为不超过 64 KiB 的有效 JSON。",
                    "error": {
                        "code": "REVIEW_INVALID_INPUT",
                        "safe_message": "输入须为不超过 64 KiB 的有效 JSON。",
                        "retryable": False,
                    },
                },
                status_code=422,
            )
        return await run_in_threadpool(
            checked, lambda: JSONResponse(reviews.create(value), status_code=201)
        )

    @api.get("/reviews/snapshots")
    def listing(account_id: str, limit: int = 50):
        gate()
        return checked(lambda: reviews.listing(account_id, limit))

    @api.get("/reviews/snapshots/{rid}")
    def get(rid: str):
        gate()
        return checked(lambda: reviews.get(rid))

    @api.get("/reviews/snapshots/{rid}/export")
    def export(rid: str):
        gate()

        def respond():
            frozen = reviews.get(rid)
            return Response(
                reviews.export(rid),
                media_type="application/json",
                headers={
                    "ETag": '"' + frozen["snapshot_hash"] + '"',
                    "Content-Disposition": f'attachment; filename="review-{frozen["review_id"]}.json"',
                },
            )

        return checked(respond)

    @api.get("/reviews/snapshots/{rid}/verify")
    def verify(rid: str):
        gate()
        return checked(lambda: reviews.verify(rid))

    @api.get("/reviews/snapshots/{rid}/sources/{bid}")
    def source(rid: str, bid: str):
        gate()
        return checked(
            lambda: FileResponse(reviews.source(rid, bid), filename=f"review-source-{bid}.bin")
        )

    @api.get("/creative-features/{fid}")
    def feature(fid: str):
        gate()
        return checked(lambda: features.get(fid))

    @api.post("/creative-features/{fid}/labels")
    async def label(fid: str, request: Request):
        gate()
        try:
            value = await body(request)
        except ValueError:
            return JSONResponse(
                {
                    "detail": "输入须为不超过 64 KiB 的有效 JSON。",
                    "error": {
                        "code": "REVIEW_INVALID_INPUT",
                        "safe_message": "输入须为不超过 64 KiB 的有效 JSON。",
                        "retryable": False,
                    },
                },
                status_code=422,
            )
        return await run_in_threadpool(
            checked, lambda: JSONResponse(features.label(fid, value), status_code=201)
        )

    return api
