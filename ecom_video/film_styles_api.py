from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from .creative import Strict
from .film_styles import catalog, recommend


class StyleBrief(Strict):
    idea: str = Field(min_length=2, max_length=1000)
    audience: str = Field(default="", max_length=120)
    tone: str = Field(default="", max_length=120)
    mode: Literal["code", "footage"] = "code"
    preferred: str | None = Field(default=None, max_length=80)


def router():
    api = APIRouter()

    @api.get("/api/film-styles")
    def styles():
        return [{k: v for k, v in r.items() if k != "prompt"} for r in catalog()]

    @api.post("/api/film-styles/recommend")
    def directions(data: StyleBrief):
        return recommend(**data.model_dump())

    return api
