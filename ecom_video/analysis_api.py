from fastapi import APIRouter
from fastapi.responses import FileResponse

from .creative import Strict
from .media_analysis import Analysis


class AnalyzeInput(Strict):
    refresh: bool = False
    force_inference: bool = False


def router(root, store):
    api = APIRouter(prefix="/api/customer-projects")
    svc = Analysis(root, store)

    @api.get("/{pid}/assets/{mid}/analysis")
    def get(pid: str, mid: str):
        return svc.get(pid, mid)

    @api.post("/{pid}/assets/{mid}/analysis", status_code=202)
    def start(pid: str, mid: str, data: AnalyzeInput | None = None):
        return svc.start(
            pid,
            mid,
            refresh=bool(data and data.refresh),
            force_inference=bool(data and data.force_inference),
        )

    @api.delete("/{pid}/assets/{mid}/analysis")
    def cancel(pid: str, mid: str):
        return svc.cancel(pid, mid)

    @api.get("/{pid}/assets/{mid}/analysis/{aid}/frames/{clip}/{index}")
    def frame(pid: str, mid: str, aid: str, clip: str, index: int):
        return FileResponse(svc.frame(pid, mid, aid, clip, index))

    return api
