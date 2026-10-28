"""D0 local reads reuse P13 receipts. No new executor or HTTP route is registered."""

import os

from pydantic import ValidationError

from ..agent_contracts import INPUTS, AgentError, Result, parse_command
from .contracts import ObjectRef, OpsResult, ToolSpec

READ_IDS = ("project.read", "project.check", "creative.recommend", "reports.dashboard")


def read_tools():
    return [
        ToolSpec(
            id=name,
            input_schema=INPUTS[name].model_json_schema(),
            output_schema=Result.model_json_schema(),
            effects=["local_read"],
            requires_human=["facts", "script"] if name == "creative.recommend" else [],
        )
        for name in READ_IDS
    ]


def capabilities():
    return {
        "schema_version": 1,
        "phase": "D0",
        "enabled": os.environ.get("ECOM_OPERATIONS_ENABLED") == "1",
        "execution_enabled": False,
        "cloud_calls_enabled": False,
        "platform_writes_enabled": False,
        "tools": [t.model_dump() for t in read_tools()],
        "human_gates": ["facts", "script", "style", "voice_alignment", "film_review"],
    }


def failure(code, message):
    return OpsResult(
        status="failed", error=AgentError(code=code, stage="admission", safe_message=message)
    )


def propose_read(service, value):
    if not capabilities()["enabled"]:
        return failure("OPERATIONS_DISABLED", "D0 本机读取桥接未启用")
    try:
        command = parse_command(value)
        if command.operation not in READ_IDS:
            raise ValueError("not a D0 read")
    except (ValidationError, ValueError, TypeError):
        return failure("INVALID_INPUT", "命令不符合 D0 本机读取白名单")
    try:
        result = Result.model_validate(service.create(command.model_dump()))
    except Exception:
        return failure("INTERNAL_ERROR", "本机读取未完成，请按请求标识核对已有回执")
    status = "completed" if result.status == "proposed" else "failed"
    if result.error and result.error.outcome_uncertain:
        status = "unknown"
    return OpsResult(
        status=status,
        output_refs=[ObjectRef(**r.model_dump()) for r in result.output_refs],
        error=result.error,
        usage=result.usage,
        legacy_result=result,
        checkpoint_ref=ObjectRef(kind="agent_run", id=result.run_id) if result.run_id else None,
        warnings=["读取完成不代表已制作或人工审核通过"] if status == "completed" else [],
    )
