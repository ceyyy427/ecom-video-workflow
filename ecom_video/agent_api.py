"""Thin P13 HTTP adapter; existing Host/Origin/session checks still apply."""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .agent_contracts import Problem, http_status, rejection
from .agent_runtime import Runtime
from .agent_runtime_contracts import execution_enabled
from .agent_service import AgentService, capabilities


def respond(fn):
    try:
        return fn()
    except Problem as exc:
        result = rejection(exc.code)
    except Exception:
        result = rejection("INTERNAL_ERROR")
    return JSONResponse(result, status_code=http_status(result))


def router(root, store):
    api = APIRouter(prefix="/api/agent")
    service = AgentService(root, store)
    runtime = Runtime(root, store)

    @api.get("/executions")
    def executions(project_id: str):
        from .agent_service import validate_id

        if not execution_enabled():
            raise HTTPException(404)

        def read():
            validate_id(project_id)
            with store.connect() as c:
                ids = [
                    r[0]
                    for r in c.execute(
                        "SELECT run_id FROM agent_executions WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
                        (project_id,),
                    )
                ]
            return [runtime.get(rid) for rid in ids]

        return respond(read)

    @api.get("/runs/{rid}/execution")
    def execution(rid: str):
        if not execution_enabled():
            raise HTTPException(404)
        return respond(lambda: runtime.get(rid))

    @api.post("/runs/{rid}/{action}")
    async def control(rid: str, action: str, request: Request):
        if not execution_enabled() or action not in (
            "execute",
            "pause",
            "resume",
            "cancel",
            "style",
        ):
            raise HTTPException(404)
        try:
            value = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(rejection("INVALID_INPUT"), status_code=422)
        return await run_in_threadpool(
            respond,
            lambda: (
                runtime.choose(rid, value)
                if action == "style"
                else runtime.control(rid, action, value)
            ),
        )

    @api.get("/capabilities")
    def catalog():
        return capabilities()

    @api.post("/runs")
    async def create(request: Request):
        try:
            value = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            result = rejection("INVALID_INPUT")
            return JSONResponse(result, status_code=422)
        try:
            result = await run_in_threadpool(service.create, value)
        except Exception:
            result = rejection("INTERNAL_ERROR")
        status = 201 if not result.get("error") else http_status(result)
        return JSONResponse(result, status_code=status)

    @api.get("/runs/{rid}")
    def get(rid: str):
        return respond(lambda: service.get(rid))

    @api.get("/runs/{rid}/events")
    def events(rid: str, request: Request):
        def read():
            query = request.query_params
            if set(query) - {"after_seq", "limit"} or any(len(query.getlist(k)) > 1 for k in query):
                raise Problem("INVALID_INPUT")
            try:
                after, limit = int(query.get("after_seq", "0")), int(query.get("limit", "100"))
            except ValueError:
                raise Problem("INVALID_INPUT") from None
            return service.events(rid, after, limit)

        return respond(read)

    return api
