"""D0 admission rejects unsafe input while preserving both older v1 contracts."""

import copy
import hashlib
import importlib.util
import json

import pytest
from pydantic import ValidationError

PID = "a" * 32


def brief():
    return {
        "schema_version": "SuiteBrief.v1",
        "project_id": PID,
        "platform": "douyin",
        "objective": "product_showcase",
        "audience": "周末出行的人",
        "tone": "自然克制",
        "product_ref": {"kind": "product", "id": "b" * 32, "revision": 0},
        "sku_color_policy": {"product_id": "b" * 32, "mode": "single", "colors": ["藏蓝"]},
        "evidence_refs": [{"kind": "fact_review", "id": "c" * 32, "revision": 1}],
        "material_refs": [{"kind": "asset", "id": "d" * 32, "sha256": "e" * 64}],
        "duration_s": 24,
        "constraints": {"local_first": True, "platform_writes": False},
    }


def test_operations_contracts_are_available_without_initializing_a_runtime():
    assert importlib.util.find_spec("ecom_video.operations") is not None


def test_suite_brief_strict_refs_and_product_color_policy():
    from ecom_video.operations.contracts import SuiteBrief

    parsed = SuiteBrief.model_validate(brief())
    assert parsed.duration_s == 24 and parsed.product_ref.id == "b" * 32
    for update in (
        {"schema_version": 1},
        {"api_key": "DO_NOT_RECORD"},
        {"project_id": "../../var"},
        {"material_refs": [{"kind": "asset", "id": "d" * 32, "path": "/etc/passwd"}]},
        {"material_refs": [{"kind": "job", "id": "d" * 32}]},
        {"material_refs": brief()["material_refs"] * 2},
        {"product_ref": {"kind": "job", "id": "b" * 32}},
        {"sku_color_policy": {"product_id": "f" * 32, "mode": "single", "colors": ["藏蓝"]}},
        {"sku_color_policy": {"product_id": "b" * 32, "mode": "single", "colors": ["藏蓝", "白"]}},
        {"duration_s": True},
        {"duration_s": 300},
        {"constraints": {"local_first": False}},
        {"constraints": {"platform_writes": True}},
        {"confirmed": True},
    ):
        with pytest.raises(ValidationError):
            SuiteBrief.model_validate({**brief(), **update})


def test_adapting_old_content_brief_and_commands_keeps_old_protocol_exactly():
    from ecom_video.agent_contracts import parse_command
    from ecom_video.content_plan import ContentBrief
    from ecom_video.operations.contracts import adapt_content_brief

    old = {"idea": "外套口袋怎么用", "subject": "软壳衣", "audience": "通勤", "tone": "自然"}
    before = ContentBrief.model_validate(old).model_dump()
    new = adapt_content_brief(before, platform="xiaohongshu", project_id=PID)
    assert new.schema_version == "SuiteBrief.v1" and new.duration_s == 24
    assert new.audience == "通勤" and new.tone == "自然"
    assert ContentBrief.model_validate(old).model_dump() == before
    command = {
        "schema_version": 1,
        "request_id": "compat-1",
        "operation": "project.read",
        "input": {"project_id": PID, "expected_revision": 0, "expected_product_revision": 0},
    }
    assert parse_command(command).model_dump() == command
    with pytest.raises(ValidationError):
        ContentBrief.model_validate({**old, "target_seconds": 30})


def plan_payload():
    value = {
        "schema_version": "SuitePlan.v1",
        "plan_id": "1" * 32,
        "revision": 0,
        "brief_ref": {
            "kind": "creative_brief",
            "id": "2" * 32,
            "revision": None,
            "sha256": "3" * 64,
        },
        "six_options": [
            {
                "id": f"option-{i}",
                "narrative": "product_showcase",
                "hook": f"看第{i}处细节",
                "script_refs": [],
                "storyboard_ref": None,
                "voice_profile": {"provider": "none"},
                "render_recipe": style,
                "evidence_refs": [],
                "feasibility": "needs_materials",
            }
            for i, style in enumerate(["kinetic", "lab", "evidence", "collage", "cinema", "social"])
        ],
        "tasks": [{"id": "read", "tool_id": "project.read", "depends_on": []}],
        "gaps": ["待补资料"],
        "cost_policy": {"max_cost_cny": "0"},
        "source_versions": [
            {"repository": "ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit", "commit": "4" * 40}
        ],
    }
    value["basis"] = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def test_plan_basis_and_task_dependencies_cannot_be_forged():
    from ecom_video.operations.contracts import SuitePlan

    original = plan_payload()
    assert SuitePlan.model_validate(original).basis == original["basis"]
    for mutate in (
        lambda p: p["six_options"][0].update(hook="未经确认的新钩子"),
        lambda p: p["six_options"].pop(),
        lambda p: p["six_options"][1].update(id="option-0"),
        lambda p: p["tasks"][0].update(tool_id="platform.publish"),
        lambda p: p["tasks"][0].update(depends_on=["missing"]),
        lambda p: (
            p["tasks"].append({"id": "other", "tool_id": "project.check", "depends_on": ["read"]})
            or p["tasks"][0].update(depends_on=["other"])
        ),
    ):
        bad = copy.deepcopy(original)
        mutate(bad)
        # Recompute to exercise structural checks as well as the frozen digest.
        if (
            bad["six_options"] != original["six_options"]
            and len(bad["six_options"]) == 6
            and bad["six_options"][0]["hook"] != original["six_options"][0]["hook"]
        ):
            pass
        else:
            body = {k: v for k, v in bad.items() if k != "basis"}
            bad["basis"] = hashlib.sha256(
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        with pytest.raises(ValidationError):
            SuitePlan.model_validate(bad)


def test_results_cannot_claim_success_with_an_error_or_retry_uncertain_outcomes():
    from ecom_video.operations.contracts import OpsResult

    assert OpsResult(status="completed").usage.platform_writes == 0
    error = {
        "code": "OUTCOME_UNKNOWN",
        "stage": "execution",
        "safe_message": "待核对",
        "outcome_uncertain": True,
    }
    assert OpsResult(status="unknown", error=error).error.outcome_uncertain
    for data in (
        {"status": "failed"},
        {"status": "completed", "error": error},
        {"status": "unknown", "error": {**error, "retryable": True}},
        {"status": "completed", "usage": {"platform_writes": 1}},
        {"status": "completed", "confirmed": True},
    ):
        with pytest.raises(ValidationError):
            OpsResult.model_validate(data)


def test_old_brief_adapter_preserves_idea_facts_data_and_upload_ownership():
    from ecom_video.content_plan import ContentBrief
    from ecom_video.operations.contracts import adapt_content_brief

    old = ContentBrief.model_validate(
        {
            "idea": "解释口袋细节",
            "mode": "footage",
            "facts": [{"text": "拉链口袋", "source": "客户资料"}],
            "data": [{"label": "口袋", "value": 2.0, "unit": "处", "source": "已核对资料"}],
            "materials": [
                {"origin": "customer", "id": "d" * 32, "project_id": "f" * 32, "source_in": 1.5}
            ],
        }
    ).model_dump()
    new = adapt_content_brief(old, platform="douyin", project_id=PID)
    assert new.content_brief.model_dump() == old
    assert not new.material_refs  # D0 cannot claim these IDs are owned by the new project.


def test_old_result_and_new_result_statuses_cannot_disagree():
    from ecom_video.operations.contracts import OpsResult

    old = {
        "status": "failed",
        "error": {"code": "NOT_FOUND", "stage": "lookup", "safe_message": "未找到"},
    }
    with pytest.raises(ValidationError):
        OpsResult(status="completed", legacy_result=old)


@pytest.mark.parametrize(
    "change",
    [
        "object_id",
        "object_revision",
        "object_sha",
        "missing_outputs",
        "run_id",
        "missing_checkpoint",
        "receipt_without_run",
    ],
)
def test_legacy_receipt_binds_exact_output_objects_and_checkpoint(change):
    from ecom_video.operations.contracts import OpsResult

    legacy = {
        "status": "proposed",
        "run_id": "a" * 32,
        "output_refs": [{"kind": "project", "id": "d" * 32, "revision": 2, "sha256": "e" * 64}],
    }
    value = {
        "status": "completed",
        "output_refs": copy.deepcopy(legacy["output_refs"]),
        "checkpoint_ref": {"kind": "agent_run", "id": "a" * 32},
        "legacy_result": legacy,
    }
    # A normal serialized bridge result must still round-trip exactly.
    valid = OpsResult.model_validate(value)
    assert OpsResult.model_validate_json(valid.model_dump_json()) == valid
    if change == "object_id":
        value["output_refs"][0]["id"] = "b" * 32
    elif change == "object_revision":
        value["output_refs"][0]["revision"] = 3
    elif change == "object_sha":
        value["output_refs"][0]["sha256"] = "f" * 64
    elif change == "missing_outputs":
        value.pop("output_refs")
    elif change == "run_id":
        value["checkpoint_ref"]["id"] = "c" * 32
    elif change == "missing_checkpoint":
        value.pop("checkpoint_ref")
    elif change == "receipt_without_run":
        value["legacy_result"]["run_id"] = None
    with pytest.raises(ValidationError):
        OpsResult.model_validate(value)
