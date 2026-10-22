from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field

from .creative import Strict
from .local_voice import LocalVoiceError


class LocalSpeech(Strict):
    revision: int = Field(ge=0)
    product_revision: int = Field(ge=0)
    draft_id: str = Field(min_length=1, max_length=64)
    engine: Literal["mlx-audio"]
    speed: float = Field(default=1, ge=0.8, le=1.2)
    preview: bool = True
    replace_voice_id: str | None = Field(default=None, min_length=1, max_length=64)
    local_engine_confirmed: Literal[True]


def router(service):
    api = APIRouter()

    @api.get("/api/voice/voicestudio/status")
    def status():
        return service.status()

    @api.post("/api/customer-projects/{pid}/voice/voicestudio", status_code=201)
    def generate(pid: str, data: LocalSpeech):
        try:
            return service.generate(pid, data)
        except LocalVoiceError as exc:
            raise HTTPException(503, str(exc)) from None

    return api
