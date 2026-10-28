"""Organic observations/comments/creative iteration. No paid-data reinterpretation."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import Field

from .comments import analyze_comments, import_comments
from .contracts import Identifier, Strict
from .iterations import compare_iteration, hypotheses, select_hypothesis
from .observations import MetricContract, freeze_observations, import_csv
from .records import Records


class ImportInput(Strict):
    source_id: Identifier
    metric_contract: MetricContract


class FreezeInput(Strict):
    batch_ids: list[Identifier] = Field(min_length=1, max_length=30)


class HypothesisInput(Strict):
    snapshot_id: Identifier
    parent_job_id: Identifier
    insights_id: Identifier | None = None


class SelectionInput(Strict):
    hypothesis_id: Identifier
    candidate_id: str = Field(min_length=1, max_length=30)
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: bool


class CompareInput(Strict):
    iteration_id: Identifier
    later_snapshot_id: Identifier


def router(root, store):
    api = APIRouter(prefix="/api/operations")
    records = Records(root, store)

    @api.post("/observations/import", status_code=201)
    def import_data(data: ImportInput):
        return import_csv(records, data.source_id, data.metric_contract.model_dump())

    @api.post("/observations/freeze", status_code=201)
    def freeze(data: FreezeInput):
        return freeze_observations(records, data.batch_ids)

    @api.post("/comments/import", status_code=201)
    async def comment_import(
        account_id: Annotated[str, Form()],
        declaration: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ):
        return import_comments(records, account_id, await file.read(2 * 1024**2 + 1), declaration)

    @api.post("/comments/{oid}/analyze", status_code=201)
    def comment_analyze(oid: str):
        return analyze_comments(records, oid)

    @api.post("/hypotheses", status_code=201)
    def propose(data: HypothesisInput):
        return hypotheses(records, data.snapshot_id, data.parent_job_id, data.insights_id)

    @api.post("/iterations", status_code=201)
    def select(data: SelectionInput):
        return select_hypothesis(
            records, data.hypothesis_id, data.candidate_id, data.reviewer, data.confirmed
        )

    @api.post("/comparisons", status_code=201)
    def compare(data: CompareInput):
        return compare_iteration(records, data.iteration_id, data.later_snapshot_id)

    return api
