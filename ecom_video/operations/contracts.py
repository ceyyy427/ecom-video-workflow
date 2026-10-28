"""D0 versioned data contracts; no provider, execution or approval side effects."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from ..agent_contracts import AgentError, Identifier, Reference, Result, Strict, Usage
from ..content_plan import ContentBrief
from ..creative import signature

Text = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ReadTool = Literal["project.read", "project.check", "creative.recommend", "reports.dashboard"]


class ObjectRef(Reference):
    kind: Literal[
        "project",
        "product",
        "job",
        "asset",
        "fact_review",
        "script_draft",
        "report_batch",
        "review_snapshot",
        "hypothesis",
        "source_unit",
        "creative_brief",
        "creative_plan",
        "agent_run",
    ]


def require_refs(refs, kinds):
    keys = [(r.kind, r.id) for r in refs]
    if len(set(keys)) != len(keys) or any(r.kind not in kinds for r in refs):
        raise ValueError("引用类型或唯一性不符合协议")


class ColorPolicy(Strict):
    product_id: Identifier
    mode: Literal["single", "same_product_multi_color"]
    colors: list[Text] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.colors)) != len(self.colors) or (
            self.mode == "single" and len(self.colors) != 1
        ):
            raise ValueError("单色只可选一个颜色，不得重复登记配色")
        return self


class Constraints(Strict):
    local_first: Literal[True] = True
    platform_writes: Literal[False] = False


class SuiteBrief(Strict):
    schema_version: Literal["SuiteBrief.v1"] = "SuiteBrief.v1"
    project_id: Identifier | None = None
    platform: Literal["douyin", "xiaohongshu"]
    objective: Literal["product_showcase", "scenario_share", "detail_explain", "knowledge", "note"]
    audience: Text
    tone: Text
    product_ref: ObjectRef | None = None
    sku_color_policy: ColorPolicy | None = None
    evidence_refs: list[ObjectRef] = Field(default_factory=list, max_length=50)
    material_refs: list[ObjectRef] = Field(default_factory=list, max_length=30)
    duration_s: int = Field(ge=15, le=30)
    constraints: Constraints = Field(default_factory=Constraints)
    content_brief: ContentBrief | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.duration_s not in {15, *range(20, 31)}:
            raise ValueError("本版支持 15 秒或 20–30 秒目标")
        if self.product_ref and self.product_ref.kind != "product":
            raise ValueError("商品引用类型不正确")
        if self.sku_color_policy and (
            not self.product_ref or self.sku_color_policy.product_id != self.product_ref.id
        ):
            raise ValueError("配色策略须绑定同一商品")
        require_refs(self.material_refs, {"asset"})
        require_refs(
            self.evidence_refs, {"fact_review", "source_unit", "review_snapshot", "report_batch"}
        )
        return self


class SourceVersion(Strict):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")


class VoiceProfile(Strict):
    provider: Literal["none", "upload", "voicestudio", "volcengine"]


class CreativeOption(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    narrative: Literal["product_showcase", "scenario_share", "detail_explain", "knowledge", "note"]
    hook: Text
    script_refs: list[ObjectRef] = Field(max_length=30)
    storyboard_ref: ObjectRef | None
    voice_profile: VoiceProfile
    render_recipe: Literal["kinetic", "lab", "evidence", "collage", "cinema", "social"]
    evidence_refs: list[ObjectRef] = Field(max_length=50)
    feasibility: Literal["ready_to_plan", "needs_materials", "code_diagram_only"]

    @model_validator(mode="after")
    def coherent(self):
        require_refs(self.script_refs, {"script_draft"})
        require_refs(
            self.evidence_refs, {"fact_review", "source_unit", "review_snapshot", "report_batch"}
        )
        if self.storyboard_ref and self.storyboard_ref.kind != "job":
            raise ValueError("分镜须引用已有任务版本")
        return self


class PlanTask(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    tool_id: ReadTool
    depends_on: list[str] = Field(max_length=80)


class CostPolicy(Strict):
    max_cost_cny: Literal["0"]


class SuitePlan(Strict):
    schema_version: Literal["SuitePlan.v1"]
    plan_id: Identifier
    revision: int = Field(ge=0)
    basis: Sha256
    brief_ref: ObjectRef
    six_options: list[CreativeOption] = Field(min_length=6, max_length=6)
    tasks: list[PlanTask] = Field(max_length=80)
    gaps: list[Text] = Field(max_length=30)
    cost_policy: CostPolicy
    source_versions: list[SourceVersion] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def coherent(self):
        if self.brief_ref.kind != "creative_brief":
            raise ValueError("方案必须引用版本化创作需求")
        if len({o.id for o in self.six_options}) != 6:
            raise ValueError("六个方向 ID 不可重复")
        ids = {t.id for t in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("任务 ID 不可重复")
        if any(
            set(t.depends_on) - ids or len(t.depends_on) != len(set(t.depends_on))
            for t in self.tasks
        ):
            raise ValueError("任务引用不存在或重复")
        done = set()
        while len(done) < len(self.tasks):
            available = {t.id for t in self.tasks if t.id not in done and set(t.depends_on) <= done}
            if not available:
                raise ValueError("任务依赖不能成环")
            done |= available
        if signature(self.model_dump(exclude={"basis"})) != self.basis:
            raise ValueError("方案内容与冻结依据不一致")
        return self


class ToolSpec(Strict):
    id: ReadTool
    version: Literal[1] = 1
    input_schema: dict
    output_schema: dict
    effects: list[Literal["local_read"]] = Field(min_length=1, max_length=1)
    transport: Literal["local"] = "local"
    requires_human: list[Literal["facts", "script"]] = Field(default_factory=list, max_length=2)
    timeout_s: Literal[15] = 15
    retries: Literal[0] = 0
    resource_class: Literal["sqlite_read"] = "sqlite_read"
    license_ref: Literal["project"] = "project"


class OpsResult(Strict):
    schema_version: Literal["OpsResult.v1"] = "OpsResult.v1"
    status: Literal["completed", "needs_human", "failed", "unknown"]
    output_refs: list[ObjectRef] = Field(default_factory=list, max_length=100)
    evidence_refs: list[ObjectRef] = Field(default_factory=list, max_length=100)
    warnings: list[Text] = Field(default_factory=list, max_length=30)
    error: AgentError | None = None
    usage: Usage = Field(default_factory=Usage)
    checkpoint_ref: ObjectRef | None = None
    legacy_result: Result | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.status in {"failed", "unknown"} and not self.error:
            raise ValueError("失败或结果不明须有结构化错误")
        if self.status in {"completed", "needs_human"} and self.error:
            raise ValueError("完成或人工等待不能同时标记错误")
        if self.status == "unknown" and (not self.error.outcome_uncertain or self.error.retryable):
            raise ValueError("结果不明不能自动重试")
        if self.error and self.error.outcome_uncertain and self.status != "unknown":
            raise ValueError("结果不明须使用独立状态")
        if self.checkpoint_ref and self.checkpoint_ref.kind != "agent_run":
            raise ValueError("检查点须引用运行回执")
        if self.legacy_result:
            legacy = self.legacy_result
            expected = "completed" if legacy.status == "proposed" else "failed"
            if legacy.error and legacy.error.outcome_uncertain:
                expected = "unknown"
            if self.status != expected or self.error != legacy.error or self.usage != legacy.usage:
                raise ValueError("桥接状态、错误与用量须保持原回执语义")
        return self


def adapt_content_brief(value, *, platform, project_id=None):
    """Reference the old 24-second request; its wire format remains untouched."""
    old = ContentBrief.model_validate(value)
    return SuiteBrief(
        platform=platform,
        project_id=project_id,
        objective="knowledge" if old.mode == "code" else "product_showcase",
        audience=old.audience or "待填写目标人群",
        tone=old.tone or "待填写希望气质",
        duration_s=old.target_seconds,
        content_brief=old,
    )
