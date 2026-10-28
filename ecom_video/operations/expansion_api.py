"""Local research, fact-bound strategy and cover drafts."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import Field

from .contracts import Identifier, Strict
from .media_pack import content_matrix, image_pack
from .records import Records
from .research import analyze_market, create_strategy, gross_margin, strategy_state


class StrategyInput(Strict):
    product_id: Identifier
    expected_revision: int = Field(ge=0)
    audience: str = Field(min_length=1, max_length=120)
    tone: str = Field(min_length=1, max_length=120)
    research_id: Identifier | None = None


class ImageInput(Strict):
    strategy_id: Identifier
    asset_id: Identifier | None = None


class MatrixInput(Strict):
    plan_id: Identifier


class MarginInput(Strict):
    sale_price: str | None = None
    cost: str | None = None
    shipping: str | None = None
    payment_fee: str | None = None
    other_cost: str | None = None
    platform_rate: str | None = None
    currency: str | None = None
    rate_effective_from: str | None = None
    rate_effective_until: str | None = None
    as_of: str | None = None


def router(root, store):
    api = APIRouter(prefix="/api/operations")
    records = Records(root, store)

    @api.post("/research", status_code=201)
    async def research(
        platform: Annotated[str, Form()],
        declared_scope: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ):
        return analyze_market(records, await file.read(2 * 1024**2 + 1), declared_scope, platform)

    @api.post("/margin")
    def margin(data: MarginInput):
        return gross_margin(data.model_dump())

    @api.post("/strategies", status_code=201)
    def strategy(data: StrategyInput):
        return create_strategy(
            records,
            data.product_id,
            data.expected_revision,
            data.audience,
            data.tone,
            data.research_id,
        )

    @api.get("/strategies/{oid}")
    def strategy_read(oid: str):
        return strategy_state(records, oid)

    @api.post("/image-packs", status_code=201)
    def image(data: ImageInput):
        return image_pack(records, data.strategy_id, data.asset_id)

    @api.post("/content-matrices", status_code=201)
    def matrix(data: MatrixInput):
        return content_matrix(records, data.plan_id)

    return api
