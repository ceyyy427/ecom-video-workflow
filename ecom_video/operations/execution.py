"""Compile an adopted domestic direction into P13/P14; never own execution or approvals."""

import os
from typing import Literal

from pydantic import Field, ValidationError

from ..agent_contracts import ERRORS, AgentError, Policy, Problem, Result
from ..agent_runtime_contracts import execution_enabled
from ..agent_service import AgentService
from ..customer import Customers
from ..idea_adoption import selected_plan
from ..idea_media import check_materials
from ..idea_plans import IdeaPlans
from .contracts import Identifier, ObjectRef, OpsResult, Sha256, Strict, SuitePlan

WARNINGS = [
    "这里只准备原本机执行计划；方向、听核、分镜及成片确认仍按实际版本处理",
    "文稿若经编辑，原逐句选卡仅作参考；执行器不会强套旧语义映射",
]


class ExecutionInput(Strict):
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    plan_id: Identifier
    plan_basis: Sha256
    option_id: Literal[
        "swiss-motion", "blueprint", "dataviz", "paper-popup", "dark-keynote", "kino-montage"
    ]
    project_id: Identifier
    expected_revision: int = Field(ge=0)
    expected_product_revision: int = Field(ge=0)
    policy: Policy


def enabled():
    return execution_enabled() and os.getenv("ECOM_DOMESTIC_EXECUTION", "1") != "0"


def linked_plan(root, store, data):
    row = IdeaPlans(root, store).get(data.plan_id)
    selected = selected_plan(store, data.project_id)
    if (
        row["basis"] != data.plan_basis
        or not selected
        or any(
            selected[k] != v
            for k, v in {
                "plan_id": data.plan_id,
                "basis": data.plan_basis,
                "option_id": data.option_id,
            }.items()
        )
    ):
        raise Problem("STALE_INPUT")
    if row["plan"]["version"] != "domestic-creative-v1":
        raise Problem("DOMAIN_REJECTED")
    SuitePlan.model_validate(row["plan"]["suite_plan"])
    check_materials(root, row["plan"]["materials"])
    return row


def command(data):
    return {
        "schema_version": 1,
        "request_id": data.request_id,
        "operation": "project.produce",
        "input": {
            "project_id": data.project_id,
            "expected_revision": data.expected_revision,
            "expected_product_revision": data.expected_product_revision,
            "policy": data.policy.model_dump(),
        },
    }


def compile_plan(root, store, value):
    data = ExecutionInput.model_validate(value)
    row = linked_plan(root, store, data)
    p = Customers(root, store).get(data.project_id)
    if (
        p["revision"] != data.expected_revision
        or p["product"]["revision"] != data.expected_product_revision
    ):
        raise Problem("STALE_INPUT")
    if p["product"]["status"] != "script_confirmed":
        raise Problem("HUMAN_CONFIRMATION_REQUIRED")
    draft = next(
        d for d in p["product"]["script_drafts"] if d["id"] == p["product"]["current_draft_id"]
    )
    option = next(o for o in row["plan"]["options"] if o["id"] == data.option_id)
    warnings = ["这里只准备原本机执行计划；方向、听核、分镜及成片确认仍按实际版本处理"]
    if "\n".join(s["text"] for s in draft["payload"]) != option["script"]:
        warnings.append("文稿已人工编辑，原逐句选卡仅作参考；执行器不会强套旧语义映射")
    return {
        "command": command(data),
        "evidence_refs": [
            ObjectRef(kind="creative_plan", id=data.plan_id, sha256=data.plan_basis).model_dump()
        ],
        "warnings": warnings,
    }


def failure(code):
    _, stage, message = ERRORS[code]
    if code == "HUMAN_CONFIRMATION_REQUIRED":
        return OpsResult(status="needs_human", warnings=[message])
    return OpsResult(
        status="failed",
        error=AgentError(code=code, stage=stage, safe_message=message),
    )


def propose_execution(root, store, value):
    try:
        data = ExecutionInput.model_validate(value)
        if not enabled():
            return failure("AGENT_DISABLED")
        linked_plan(root, store, data)
        with store.connect() as c:
            prior = c.execute(
                "SELECT 1 FROM agent_runs WHERE request_id=?", (data.request_id,)
            ).fetchone()
        # Replay is owned by the original transaction, even after production advances revisions.
        compiled = (
            compile_plan(root, store, data.model_dump())
            if not prior
            else {
                "command": command(data),
                "evidence_refs": [
                    ObjectRef(
                        kind="creative_plan", id=data.plan_id, sha256=data.plan_basis
                    ).model_dump()
                ],
                "warnings": ["复用原运行回执；当前执行状态和人工关卡请查看原运行"],
            }
        )
        result = Result.model_validate(AgentService(root, store).create(compiled["command"]))
        return OpsResult(
            status="completed"
            if result.status == "proposed"
            else "unknown"
            if result.error and result.error.outcome_uncertain
            else "failed",
            output_refs=[ObjectRef(**r.model_dump()) for r in result.output_refs],
            evidence_refs=[ObjectRef(**r) for r in compiled["evidence_refs"]],
            warnings=WARNINGS,
            error=result.error,
            usage=result.usage,
            legacy_result=result,
            checkpoint_ref=ObjectRef(kind="agent_run", id=result.run_id) if result.run_id else None,
        )
    except Problem as exc:
        return failure(exc.code)
    except KeyError:
        return failure("NOT_FOUND")
    except (ValidationError, ValueError, TypeError):
        return failure("INVALID_INPUT")


def safe_fallback(error, status):
    if error.get("outcome_uncertain") or status == "unknown":
        return {
            "action": "stop",
            "automatic_retry": False,
            "reason": "结果不明，先核对原运行，不能重发",
        }
    return {
        "action": "needs_human",
        "automatic_retry": False,
        "reason": "保留原运行、素材和文稿；在原工作台补齐确认/依赖后恢复，失效输入须创建新计划",
    }
