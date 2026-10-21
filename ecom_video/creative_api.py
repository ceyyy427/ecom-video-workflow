import re
import threading
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field

from .alignment import AlignmentService, confirmed_alignment
from .creative import Brief, Strict, recommend
from .db import Conflict


class AlignInput(Strict):
    asset_id: str


class WordTime(Strict):
    start: float = Field(ge=0, le=120)
    end: float = Field(ge=0, le=120)


class SentenceTimes(Strict):
    words: list[WordTime] = Field(min_length=1, max_length=100)


class TimingEdits(Strict):
    sentences: list[SentenceTimes] = Field(min_length=1, max_length=30)


class ConfirmInput(Strict):
    confirmed: bool
    reviewer: str = Field(min_length=1, max_length=120)
    result: TimingEdits | None = None


class SelectInput(Strict):
    revision: int = Field(ge=0)
    board: dict


def router(root, store):
    api = APIRouter()
    service = AlignmentService(root, store)

    @api.post("/api/jobs/{jid}/creative/recommend")
    def recommendations(jid: str, brief: Brief):
        return recommend(store.get(jid), brief)

    preview_lock = threading.Lock()

    @api.post("/api/jobs/{jid}/creative/previews")
    def preview(jid: str, brief: Brief):
        from .remotion_renderer import style_previews

        job = store.get(jid)
        if not preview_lock.acquire(blocking=False):
            raise Conflict("风格预览正在生成，请稍后重试")
        try:
            return style_previews(job, root, recommend(job, brief))
        finally:
            preview_lock.release()

    @api.get("/api/jobs/{jid}/creative/previews/{key}/{style}")
    def preview_file(jid: str, key: str, style: str):
        from .creative import CATALOG

        store.get(jid)
        if not re.fullmatch("[a-f0-9]{64}", key) or style not in {s["id"] for s in CATALOG}:
            raise KeyError(key)
        file = Path(root) / "previews" / jid / key / (style + ".png")
        if not file.is_file():
            raise KeyError(key)
        return FileResponse(file)

    @api.post("/api/jobs/{jid}/alignments")
    def align(jid: str, data: AlignInput):
        return service.start(jid, data.asset_id)

    @api.get("/api/jobs/{jid}/alignments/{aid}")
    def get(jid: str, aid: str):
        return service.get(jid, aid)

    @api.delete("/api/jobs/{jid}/alignments/{aid}")
    def stop(jid: str, aid: str):
        return service.cancel(jid, aid)

    @api.post("/api/jobs/{jid}/alignments/{aid}/confirm")
    def confirm(jid: str, aid: str, data: ConfirmInput):
        if not data.confirmed:
            raise ValueError("请听核并确认配音时间戳")
        return service.confirm(
            jid, aid, data.result.model_dump() if data.result else None, data.reviewer.strip()
        )

    @api.put("/api/jobs/{jid}/creative")
    def select(jid: str, data: SelectInput):
        job = store.get(jid)
        if not data.board.get("creative"):
            raise ValueError("请选择三个推荐方向中的一个")
        with store.connect() as c:
            confirmed_alignment(c, job, job["assets"], data.board)
        return store.save_storyboard(jid, data.board, data.revision)

    @api.post("/api/jobs/{jid}/creative/apply-alignment/{aid}")
    def apply(jid: str, aid: str):
        job = store.get(jid)
        row = service.get(jid, aid)
        if job["status"] != "draft" or row["status"] != "confirmed":
            raise Conflict("请先听核确认对齐")
        from .storyboard import default_board

        board = job["storyboard"] or default_board(job)
        # Derive cuts at the next sentence onset; preserve original audio and its leading pause.
        sentences = row["result"]["sentences"]
        from .alignment import input_hash

        asset = next(
            (
                a
                for a in job["assets"]
                if a["kind"] == "audio" and input_hash(job, a) == row["fingerprint"]
            ),
            None,
        )
        if not asset:
            raise Conflict("对齐输入已变化")
        boundaries = (
            [0]
            + [round(s["start"] * 30) / 30 for s in sentences[1:]]
            + [__import__("math").ceil(asset["metadata"]["duration"] * 30) / 30]
        )
        for i, shot in enumerate(board["shots"]):
            shot["duration"] = round((boundaries[i + 1] - boundaries[i]) * 30) / 30
        if any(not 1 <= s["duration"] <= 15 for s in board["shots"]):
            raise ValueError("对齐后的单句需在 1–15 秒内，请在脚本中拆分或合并语义拍后重新对齐")
        board["narration"]["mode"] = "uploaded"
        board["narration"]["asset_id"] = asset["id"]
        if board.get("creative"):
            board["creative"]["alignment_id"] = aid
        return {"board": board, "revision": job["storyboard_revision"], "alignment_id": aid}

    return api
