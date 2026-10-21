"""Strict, versioned data contracts; importing this module performs no I/O."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
MAX_EVENT_SEQ = 2**63 - 1


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ProjectInput(Strict):
    project_id: Identifier
    expected_revision: int = Field(ge=0)
    expected_product_revision: int = Field(ge=0)


class Policy(Strict):
    policy_id: Literal["local-v1"]
    max_steps: int = Field(ge=1, le=80)
    max_elapsed_s: int = Field(ge=30, le=14400)
    max_model_calls: int = Field(ge=0, le=500)
    max_cost_cny: Literal["0"]


class ProductionInput(ProjectInput):
    policy: Policy


class ReportInput(Strict):
    account_id: Identifier
    start_date: str
    end_date: str
    material_limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def date_range(self):
        a, b = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        if (a.isoformat(), b.isoformat()) != (self.start_date, self.end_date):
            raise ValueError("Invalid date format")
        if not 0 <= (b - a).days < 31:
            raise ValueError("Invalid date range")
        return self


class Request(Strict):
    schema_version: Literal[1]
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Integer schema version required")
        return value


class ReadProject(Request):
    operation: Literal["project.read"]
    input: ProjectInput


class CheckProject(Request):
    operation: Literal["project.check"]
    input: ProjectInput


class RecommendCreative(Request):
    operation: Literal["creative.recommend"]
    input: ProjectInput


class ReadReports(Request):
    operation: Literal["reports.dashboard"]
    input: ReportInput


class Produce(Request):
    operation: Literal["project.produce"]
    input: ProductionInput


Command = Annotated[
    ReadProject | CheckProject | RecommendCreative | ReadReports | Produce,
    Field(discriminator="operation"),
]
COMMAND = TypeAdapter(Command)
INPUTS = {
    "project.read": ProjectInput,
    "project.check": ProjectInput,
    "creative.recommend": ProjectInput,
    "reports.dashboard": ReportInput,
    "project.produce": ProductionInput,
}


def parse_command(value):
    return COMMAND.validate_python(value)


class Reference(Strict):
    kind: Literal["project", "job", "asset", "fact_review", "script_draft", "report_batch"]
    id: Identifier
    revision: int | None = Field(default=None, ge=0)
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None


class AgentError(Strict):
    code: str
    stage: Literal["admission", "lookup", "preflight", "read", "persistence", "execution"]
    retryable: bool = False
    outcome_uncertain: bool = False
    safe_message: str
    evidence_refs: list[Reference] = Field(default_factory=list)


class Usage(Strict):
    model_calls: Literal[0] = 0
    cloud_calls: Literal[0] = 0
    platform_writes: Literal[0] = 0


class Result(Strict):
    schema_version: Literal[1] = 1
    run_id: Identifier | None = None
    request_id: str | None = None
    status: Literal["proposed", "failed", "rejected"]
    revision: int | None = None
    operation: str | None = None
    output_refs: list[Reference] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
    error: AgentError | None = None
    usage: Usage = Field(default_factory=Usage)
    evidence_level: Literal["local_read"] = "local_read"
    created_at: float | None = None


ERRORS = {
    "INVALID_INPUT": (422, "admission", "命令不符合工具契约，请检查字段、版本及输入范围。"),
    "AGENT_DISABLED": (403, "admission", "P13 Agent 入口未启用，请由本机维护者设置开关。"),
    "NOT_FOUND": (404, "lookup", "请求的项目、账户或运行记录不存在。"),
    "REQUEST_CONFLICT": (409, "admission", "该 request_id 已用于另一份命令，请使用新的请求标识。"),
    "STALE_INPUT": (409, "preflight", "项目版本已更新，请读取当前版本并新建提案。"),
    "HUMAN_CONFIRMATION_REQUIRED": (409, "preflight", "请先通过既有页面确认当前事实与文稿。"),
    "DOMAIN_REJECTED": (422, "read", "当前资料状态不满足工具要求，请在既有页面检查项目。"),
    "OUTPUT_LIMIT": (413, "read", "提案数据超过输出上限，请缩小读取范围。"),
    "INTERNAL_ERROR": (500, "persistence", "本机提案处理未完成，请检查服务状态后重试。"),
    "BUDGET_EXCEEDED": (
        409,
        "execution",
        "本次运行的步骤或本机模型调用预算已用尽，请检查已有产物。",
    ),
    "DEADLINE_EXCEEDED": (409, "execution", "本次运行已超过时限，已停止继续派发。"),
    "LOCAL_TASK_FAILED": (409, "execution", "本机子任务未完成，请在原页面检查素材、模型或配音。"),
    "OUTCOME_UNKNOWN": (
        409,
        "execution",
        "上次步骤结果无法确定，未自动重试，请检查记录后重新提案。",
    ),
}


class Problem(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def rejection(code):
    _, stage, message = ERRORS[code]
    return Result(
        status="rejected", error=AgentError(code=code, stage=stage, safe_message=message)
    ).model_dump()


def http_status(result):
    return ERRORS[result["error"]["code"]][0] if result.get("error") else 200
