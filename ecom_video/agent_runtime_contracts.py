"""P14 fixed local policy and human/control contracts; no transports."""

from typing import Literal

from pydantic import Field

from .agent_contracts import Policy as Policy
from .agent_contracts import Strict
from .creative import StyleId


class Control(Strict):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    policy_id: Literal["local-v1"]


class StyleChoice(Control):
    style_id: StyleId
    direction_basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


def execution_enabled():
    import os

    return (
        os.environ.get("ECOM_AGENT_ENABLED") == "1"
        and os.environ.get("ECOM_AGENT_EXECUTION_ENABLED") == "1"
    )
