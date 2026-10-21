"""User-triggered cloud speech endpoints; browser never sends credentials or arbitrary text."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from .creative import Strict, StyleId
from .volc_voice import CONFIG_ERROR, VoiceError, status


class GenerateVoice(Strict):
    revision: int = Field(ge=0)
    product_revision: int = Field(ge=0)
    draft_id: str = Field(min_length=1, max_length=64)
    external_consent: Literal[True]
    speaker: (
        Literal["zh_female_vv_uranus_bigtts", "zh_female_gaolengyujie_uranus_bigtts"] | None
    ) = None
    style_id: StyleId | None = None
    direction_basis: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    replace_voice_id: str | None = Field(default=None, min_length=1, max_length=64)


class PreviewVoice(GenerateVoice):
    style_id: StyleId
    direction_basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    replace_voice_id: None = None


class UseVoice(Strict):
    revision: int = Field(ge=0)
    product_revision: int = Field(ge=0)
    draft_id: str = Field(min_length=1, max_length=64)


class ShotVersion(UseVoice):
    job_id: str = Field(min_length=1, max_length=64)
    board_revision: int = Field(ge=0)


class GenerateShot(ShotVersion):
    speaker: (
        Literal["zh_female_vv_uranus_bigtts", "zh_female_gaolengyujie_uranus_bigtts"] | None
    ) = None
    external_consent: Literal[True]


class AdoptShot(ShotVersion):
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


def router(service, shots):
    api = APIRouter()

    @api.get("/api/voice/volcengine/status")
    def get_status():
        return status()

    @api.post("/api/customer-projects/{pid}/voice/volcengine", status_code=201)
    def generate(pid: str, data: GenerateVoice):
        try:
            return service.generate(
                pid,
                data.revision,
                data.product_revision,
                data.draft_id,
                data.speaker,
                style_id=data.style_id,
                direction_basis=data.direction_basis,
                replace_voice_id=data.replace_voice_id,
            )
        except VoiceError as exc:
            raise HTTPException(
                503 if str(exc) == CONFIG_ERROR else 502,
                str(exc),
                headers={"X-Voice-Error-Code": exc.code},
            ) from None

    @api.post("/api/customer-projects/{pid}/voice/preview", status_code=201)
    def preview(pid: str, data: PreviewVoice):
        try:
            return service.generate(
                pid,
                data.revision,
                data.product_revision,
                data.draft_id,
                data.speaker,
                style_id=data.style_id,
                direction_basis=data.direction_basis,
                preview=True,
            )
        except VoiceError as exc:
            raise HTTPException(
                503 if str(exc) == CONFIG_ERROR else 502,
                str(exc),
                headers={"X-Voice-Error-Code": exc.code},
            ) from None

    @api.get("/api/customer-projects/{pid}/voice/takes/{aid}")
    def take_file(pid: str, aid: str):
        return FileResponse(service.take_file(pid, aid))

    @api.post("/api/customer-projects/{pid}/voice/takes/{aid}/use")
    def use(pid: str, aid: str, data: UseVoice):
        return service.use_take(pid, aid, data.revision, data.product_revision, data.draft_id)

    @api.post("/api/customer-projects/{pid}/voice/shots/{shot_id}/takes", status_code=201)
    def generate_shot(pid: str, shot_id: str, data: GenerateShot):
        try:
            return shots.generate(pid, shot_id, data.model_dump())
        except VoiceError as exc:
            raise HTTPException(
                503 if str(exc) == CONFIG_ERROR else 502,
                str(exc),
                headers={"X-Voice-Error-Code": exc.code},
            ) from None

    @api.get("/api/customer-projects/{pid}/voice/shots/takes/{tid}/{kind}")
    def shot_file(pid: str, tid: str, kind: str):
        return FileResponse(shots.file(pid, tid, kind))

    @api.post("/api/customer-projects/{pid}/voice/shots/takes/{tid}/use")
    def use_shot(pid: str, tid: str, data: AdoptShot):
        return shots.apply(pid, tid, data.model_dump())

    return api
