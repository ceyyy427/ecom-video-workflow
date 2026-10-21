"""Loopback/session-bound P16 commands. No renderer, provider or placement dispatch."""

import hashlib
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .creative_features import sha
from .db import Conflict
from .experiment_contracts import Action, Attach, Evaluate, Proposal, Select, Style, enabled
from .experiments import Experiments


def checked(fn):
    try:
        return fn()
    except Conflict as exc:
        status, code, message = 409, "EXPERIMENT_CONFLICT", str(exc)
    except ValueError as exc:
        status, code, message = 422, "EXPERIMENT_INVALID_INPUT", str(exc)
    except KeyError:
        status, code, message = 404, "EXPERIMENT_NOT_FOUND", "创意迭代或引用记录不存在。"
    except Exception:
        status, code, message = 500, "EXPERIMENT_INTERNAL", "本机创意迭代未完成，请检查服务状态。"
    return JSONResponse(
        {"detail": message, "error": {"code": code, "safe_message": message, "retryable": False}},
        status_code=status,
    )


def router(root, store):
    api = APIRouter(prefix="/api/experiments")
    service = Experiments(root, store)

    def gate():
        if not enabled():
            raise HTTPException(404)

    @api.get("/capabilities")
    def capabilities():
        return {
            "phase": "P16",
            "enabled": enabled(),
            "schema_version": 1,
            "cloud_calls": False,
            "model_calls": False,
            "platform_writes": False,
            "automatic_apply": False,
            "causal_inference": False,
            "schemas": {
                "proposal": Proposal.model_json_schema(),
                "select": Select.model_json_schema(),
                "apply": Action.model_json_schema(),
                "attach": Attach.model_json_schema(),
                "style": Style.model_json_schema(),
                "evaluate": Evaluate.model_json_schema(),
            },
            "limits": {
                "command_bytes": 65536,
                "events_per_experiment": 500,
                "evaluations_per_experiment": 100,
                "list": 50,
            },
        }

    @api.get("/context")
    def context(review_id: str, material_id: str):
        gate()
        return checked(lambda: service.context(review_id, material_id))

    @api.get("")
    def listing(review_id: str | None = None):
        gate()
        return checked(lambda: service.listing(review_id))

    async def command(request, fn, code=200):
        gate()
        try:
            raw = await request.body()
            if len(raw) > 65536:
                raise ValueError
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                {
                    "detail": "请提供不超过 64 KiB 的有效 JSON。",
                    "error": {
                        "code": "EXPERIMENT_INVALID_INPUT",
                        "safe_message": "请提供不超过 64 KiB 的有效 JSON。",
                        "retryable": False,
                    },
                },
                status_code=422,
            )
        return await run_in_threadpool(checked, lambda: JSONResponse(fn(body), status_code=code))

    @api.post("")
    async def create(request: Request):
        return await command(request, service.create, 201)

    @api.get("/{eid}")
    def get(eid: str):
        gate()
        return checked(lambda: service.get(eid))

    @api.get("/{eid}/export")
    def export(eid: str):
        gate()

        def response():
            data = service.export(eid)
            return Response(
                data,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="experiment-{eid}.json"',
                    "ETag": '"' + hashlib.sha256(data).hexdigest() + '"',
                },
            )

        return checked(response)

    @api.get("/{eid}/production")
    def production(eid: str):
        gate()

        def read():
            e = service.get(eid)
            pid = e["proposal"]["product_id"]
            job = store.get(e["result_job_id"]) if e["result_job_id"] else None
            board = job["storyboard"] if job else None
            choice = board.get("creative") if board else None
            style_valid = bool(
                choice
                and any(
                    s["job_id"] == job["id"]
                    and s["board_revision"] == job["storyboard_revision"]
                    and s["board_hash"] == sha(board)
                    for s in e["styles"]
                )
            )
            with store.connect() as c:
                active = c.execute(
                    "SELECT active_job_id FROM customer_projects WHERE product_id=?", (pid,)
                ).fetchone()[0]
            return {
                "product_id": pid,
                "job_id": job["id"] if job else None,
                "job_status": job["status"] if job else None,
                "active_job_id": active,
                "board_revision": job["storyboard_revision"] if job else None,
                "style_id": choice.get("style_id") if choice else None,
                "style_confirm_needed": bool(job and not style_valid),
                "customer_url": "/create?project=" + pid,
                "studio_url": "/studio?job=" + job["id"] if job else None,
            }

        return checked(read)

    @api.post("/{eid}/select")
    async def select(eid: str, request: Request):
        return await command(request, lambda value: service.select(eid, value))

    @api.post("/{eid}/apply")
    async def apply(eid: str, request: Request):
        return await command(request, lambda value: service.apply(eid, value))

    @api.post("/{eid}/attach")
    async def attach(eid: str, request: Request):
        return await command(request, lambda value: service.attach(eid, value))

    @api.post("/{eid}/style-confirm")
    async def style(eid: str, request: Request):
        return await command(request, lambda value: service.style_confirm(eid, value))

    @api.post("/{eid}/await-data")
    async def await_data(eid: str, request: Request):
        return await command(request, lambda value: service.await_data(eid, value))

    @api.post("/{eid}/evaluate")
    async def evaluate(eid: str, request: Request):
        return await command(request, lambda value: service.evaluate(eid, value))

    return api
