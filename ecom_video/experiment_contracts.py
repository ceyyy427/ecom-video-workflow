"""Strict, bounded local experiment commands. No model or platform capabilities."""

import os
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .agent_contracts import Identifier, Strict
from .creative import StyleId
from .customer_api import ShotChanges
from .review_contracts import RequestId

Metric = Literal[
    "spend",
    "impressions",
    "clicks",
    "orders",
    "revenue",
    "video_views",
    "completed_views",
    "ctr",
    "cpc",
    "cpm",
    "cpa",
    "payment_roi",
    "order_per_click",
    "completion_rate",
]


def enabled():
    return os.environ.get("ECOM_EXPERIMENTS_ENABLED") == "1"


class Actor(Strict):
    actor: str = Field(min_length=1, max_length=80)

    @field_validator("actor")
    @classmethod
    def actor_valid(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid actor")
        return value.strip()


class Edits(ShotChanges):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True, exclude_unset=True):
            raise ValueError("Empty changes")
        return self


class VisualChange(Strict):
    kind: Literal["visual"]
    shot_id: str = Field(min_length=1, max_length=64)
    changes: Edits


class Scene(Strict):
    text: str = Field(min_length=1, max_length=100)
    fact_ids: list[Identifier] = Field(max_length=30)
    attribution: Literal["neutral", "exact_quote", "human_rewrite"] | None = None


class ScriptChange(Strict):
    kind: Literal["script"]
    scenes: list[Scene] = Field(min_length=1, max_length=30)


class Policy(Strict):
    min_reported_days: int = Field(default=1, ge=1, le=31)
    min_impressions: int = Field(default=100, ge=0, le=1000000000)


class Proposal(Actor):
    request_id: RequestId
    review_id: Identifier
    material_id: str = Field(pattern=r"^[0-9]{1,64}$")
    parent_job_id: Identifier
    hypothesis: str = Field(min_length=1, max_length=1000)
    target_metric: Metric
    change_set: Annotated[VisualChange | ScriptChange, Field(discriminator="kind")]
    comparison_policy: Policy

    @field_validator("hypothesis")
    @classmethod
    def hypothesis_valid(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid hypothesis")
        return value.strip()


class Action(Actor):
    request_id: RequestId
    expected_revision: int = Field(ge=0)


class Confirm(Action):
    confirmed: bool

    @model_validator(mode="after")
    def confirmation(self):
        if not self.confirmed:
            raise ValueError("Human confirmation required")
        return self


class Select(Confirm):
    decision: Literal["selected", "rejected"]
    note: str = Field(min_length=1, max_length=1000)


class Attach(Action):
    job_id: Identifier


class Style(Confirm):
    job_id: Identifier
    board_revision: int = Field(ge=0)
    style_id: StyleId


class Evaluate(Action):
    next_review_id: Identifier
    new_material_id: str = Field(pattern=r"^[0-9]{1,64}$")


def parse(model, value):
    try:
        return model.model_validate(value)
    except (ValueError, TypeError):
        raise ValueError("输入不符合创意迭代契约，请检查字段、版本与人工确认。") from None
