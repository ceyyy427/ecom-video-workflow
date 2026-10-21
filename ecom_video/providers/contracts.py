"""Future provider boundary, deliberately without transport or credential lookup."""

from typing import Literal, Protocol

from pydantic import Field

from ..agent_contracts import Reference, Strict


class ProviderRequest(Strict):
    kind: Literal["text", "vision", "tts", "render"]
    input_refs: list[Reference] = Field(min_length=1, max_length=100)
    credential_ref: str | None = Field(
        default=None, pattern=r"^(env|keychain):[A-Za-z0-9_-]{1,100}$"
    )
    deadline_s: int = Field(ge=1, le=1800)
    max_calls: int = Field(ge=1, le=100)
    max_cost_cny: str = Field(pattern=r"^(0|[1-9][0-9]{0,5})(\.[0-9]{1,6})?$")


class ProviderResult(Strict):
    provider: str
    version: str
    output_refs: list[Reference]
    evidence_level: Literal["fixture", "local_verified", "provider_verified"]
    timing_source: Literal["none", "measured", "estimated", "provider_cues"]
    calls: int = Field(ge=0)
    outcome_uncertain: bool = False


class Provider(Protocol):
    def invoke(self, request: ProviderRequest) -> ProviderResult: ...
