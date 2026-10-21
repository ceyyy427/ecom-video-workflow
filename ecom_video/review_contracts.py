"""Bounded review input and explicit metric/provenance definitions. No I/O."""

import os
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from .agent_contracts import Identifier, Strict
from .reporting import dates

MAX_ROWS = 20000
MAX_MATERIALS = 500
MAX_CELLS = 15500
MAX_PAYLOAD = 8 * 1024**2
MAX_SOURCE_BYTES = 128 * 1024**2
ALGORITHM_VERSION = "material-daily-freeze-v1"
FEATURE_VERSION = "submitted-creative-v1"
RequestId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]


class FreezeInput(Strict):
    request_id: RequestId
    account_id: Identifier
    start_date: str
    end_date: str
    actor: str = Field(min_length=1, max_length=120)

    @field_validator("actor")
    @classmethod
    def actor_valid(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid actor")
        return value.strip()

    @model_validator(mode="after")
    def range_valid(self):
        dates(self.start_date, self.end_date)
        return self


class LabelInput(Strict):
    request_id: RequestId
    label_key: Literal["hook_type", "visual_tone", "product_category"]
    value: str = Field(min_length=1, max_length=80)
    origin: Literal["human", "model"]
    actor: str = Field(min_length=1, max_length=120)
    evidence_field: Literal["hook_text", "style_id", "format", "shot_count", "narration_mode"]
    confirmed: bool
    model_name: str | None = Field(default=None, min_length=1, max_length=120)
    model_version: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def provenance(self):
        for v in [self.value, self.actor, self.model_name, self.model_version]:
            if v is not None and (not v.strip() or any(ord(c) < 32 for c in v)):
                raise ValueError("Invalid label")
        if self.origin == "human" and (not self.confirmed or self.model_name or self.model_version):
            raise ValueError("Human confirmation required")
        if self.origin == "model" and (
            self.confirmed or not self.model_name or not self.model_version
        ):
            raise ValueError("Model provenance required; unverified")
        return self


def parse(model, value):
    try:
        return model.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise ValueError("输入不符合冻结复盘契约，请检查字段、日期和来源标记。") from None


def enabled():
    return os.environ.get("ECOM_REVIEW_SNAPSHOTS_ENABLED") == "1"


def identifier(value):
    try:
        return TypeAdapter(Identifier).validate_python(value)
    except ValidationError:
        raise ValueError("记录 ID 格式无效。") from None


def metric_contract(account):
    definitions = {
        "ctr": ("clicks", "impressions", "1"),
        "cpc": ("spend", "clicks", "1"),
        "cpm": ("spend", "impressions", "1000"),
        "cpa": ("spend", "orders", "1"),
        "payment_roi": ("revenue", "spend", "1"),
        "order_per_click": ("orders", "clicks", "1"),
        "completion_rate": ("completed_views", "video_views", "1"),
    }
    return {
        "version": "payment-material-metrics-v1",
        "basis_id": "payment_material_v1",
        "algorithm_version": ALGORITHM_VERSION,
        "currency": account["currency"],
        "timezone": account["timezone"],
        "basis": "素材支付口径，沿用已导入报表契约；支付 ROI=支付金额/花费，不是 ROI2 或利润率",
        "basis_verification": "import_contract_declared;not_independently_verified_against_platform",
        "attribution_window": None,
        "attribution_window_status": "unknown_unless_source_declared",
        "causal_inference": False,
        "comparability": "not_assessed;no_winner_or_causal_conclusion",
        "number_encoding": "decimal_strings;counts_are_integers",
        "rounding": {"decimal_places": 6, "mode": "ROUND_HALF_EVEN"},
        "missing_policy": "unknown_stays_null;missing_material_day_not_zero;empty_covered_day_unknown",
        "aggregation": "sum_raw_metrics_then_divide;not_average_of_ratios",
        "zero_denominator": "null",
        "definitions": {
            key: {"numerator": a, "denominator": b, "factor": factor}
            for key, (a, b, factor) in definitions.items()
        },
    }
