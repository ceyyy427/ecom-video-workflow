"""P13: local read-only proposal tools with immutable, transactional receipts.

No executor, provider invocation, approval, platform write or model call is exposed.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .agent_contracts import (
    COMMAND,
    ERRORS,
    INPUTS,
    MAX_EVENT_SEQ,
    AgentError,
    Identifier,
    Problem,
    Result,
    parse_command,
    rejection,
)
from .agent_runtime_contracts import execution_enabled
from .db import Conflict

log = logging.getLogger(__name__)
MAX_COMMAND_BYTES = 64 * 1024
MAX_RESULT_BYTES = 256 * 1024
HUMAN_GATES = ["facts", "script", "style", "voice_alignment", "film_review"]
DESCRIPTIONS = {
    "project.produce": "提出有界本机制作计划，需显式启动并保留全部人工确认。",
    "project.read": "读取项目概要、当前事实与文稿引用，不启动制作。",
    "project.check": "读取制作条件与人工确认缺口，不解码媒体或核验商品事实。",
    "creative.recommend": "读取已确认文稿的三个方向，仍由用户选择风格。",
    "reports.dashboard": "读取账户×素材×日报表的描述性指标，不同步数据或执行投放。",
}


def enabled():
    return os.environ.get("ECOM_AGENT_ENABLED") == "1"


def capabilities():
    result = {
        "schema_version": 1,
        "phase": "P14" if execution_enabled() else "P13",
        "enabled": enabled(),
        "execution_enabled": execution_enabled(),
        "cloud_calls_enabled": False,
        "platform_writes_enabled": False,
        "model_policy": "local_first",
        "human_gates": HUMAN_GATES,
        "tools": [
            {
                "name": name,
                "version": 1,
                "effect": "read",
                "requires_confirmations": ["facts", "script"]
                if name == "creative.recommend"
                else [],
                "description": DESCRIPTIONS[name],
                "input_schema": schema.model_json_schema(),
                "result_schema": Result.model_json_schema(),
            }
            for name, schema in INPUTS.items()
            if name != "project.produce" or execution_enabled()
        ],
        "command_schema": COMMAND.json_schema(),
        "provider_transports": [],
        "limits": {"command_bytes": MAX_COMMAND_BYTES, "result_bytes": MAX_RESULT_BYTES},
    }
    if execution_enabled():
        from .agent_runtime_contracts import Control, Policy, StyleChoice

        result["execution_contracts"] = {
            "policy": Policy.model_json_schema(),
            "control": Control.model_json_schema(),
            "human_style": StyleChoice.model_json_schema(),
            "pause_semantics": "stop_new_dispatch;inflight_local_step_may_finish",
            "deadline_semantics": "wall_clock_including_human_wait_and_pause",
        }
    return result


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_id(value):
    try:
        return TypeAdapter(Identifier).validate_python(value)
    except ValidationError:
        raise Problem("INVALID_INPUT") from None


class AgentService:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    def create(self, value):
        try:
            command = parse_command(value)
        except (ValidationError, TypeError, ValueError):
            return rejection("INVALID_INPUT")
        if not enabled():
            return rejection("AGENT_DISABLED")
        if command.operation == "project.produce" and not execution_enabled():
            return rejection("AGENT_DISABLED")
        serialized = encoded(command.model_dump())
        if len(serialized.encode()) > MAX_COMMAND_BYTES:
            return rejection("INVALID_INPUT")
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        # All four tools are bounded local reads. This short transaction also
        # prevents domain edits between checking revision and recording the read.
        with self.store.transaction() as c:
            prior = c.execute(
                "SELECT command_hash,result FROM agent_runs WHERE request_id=?",
                (command.request_id,),
            ).fetchone()
            if prior:
                if prior["command_hash"] != fingerprint:
                    return rejection("REQUEST_CONFLICT")
                return json.loads(prior["result"])
            rid, now = uuid.uuid4().hex, time.time()
            result = Result(
                run_id=rid,
                request_id=command.request_id,
                status="proposed",
                operation=command.operation,
                created_at=now,
            )
            try:
                data, refs, revision = self._evaluate(command)
                result = Result(
                    **{
                        **result.model_dump(),
                        "data": data,
                        "output_refs": refs,
                        "revision": revision,
                    }
                )
                if len(encoded(result.model_dump()).encode()) > MAX_RESULT_BYTES:
                    raise Problem("OUTPUT_LIMIT")
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, Problem)
                    else "NOT_FOUND"
                    if isinstance(exc, KeyError)
                    else "STALE_INPUT"
                    if isinstance(exc, Conflict)
                    else "DOMAIN_REJECTED"
                    if isinstance(exc, ValueError)
                    else "INTERNAL_ERROR"
                )
                _, stage, message = ERRORS[code]
                if code == "INTERNAL_ERROR":
                    stage = "read"
                result = Result(
                    **{
                        **result.model_dump(),
                        "status": "failed",
                        "data": {},
                        "output_refs": [],
                        "error": AgentError(
                            code=code, stage=stage, safe_message=message
                        ).model_dump(),
                    }
                )
                # Never log exception text: domain/provider errors may contain secrets.
                log.warning("Agent proposal failed run_id=%s code=%s", rid, code)
            public = result.model_dump()
            c.execute(
                "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)",
                (
                    rid,
                    command.request_id,
                    fingerprint,
                    serialized,
                    result.status,
                    encoded(public),
                    now,
                ),
            )
            if command.operation == "project.produce" and result.status == "proposed":
                from .agent_runtime import create_execution

                create_execution(c, rid, result.data, now)
            for event, payload in (
                ("request_accepted", {"operation": command.operation, "command_hash": fingerprint}),
                (
                    "proposal_ready" if result.status == "proposed" else "tool_failed",
                    {
                        "status": result.status,
                        "error_code": result.error.code if result.error else None,
                    },
                ),
            ):
                c.execute(
                    "INSERT INTO agent_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
                    (rid, event, encoded(payload), now),
                )
        return public

    def get(self, rid):
        validate_id(rid)
        if not enabled():
            raise Problem("AGENT_DISABLED")
        with self.store.connect() as c:
            row = c.execute("SELECT result FROM agent_runs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise Problem("NOT_FOUND")
        return json.loads(row["result"])

    def events(self, rid, after_seq=0, limit=100):
        self.get(rid)
        if (
            type(after_seq) is not int
            or not 0 <= after_seq <= MAX_EVENT_SEQ
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise Problem("INVALID_INPUT")
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT seq,type,payload,created_at FROM agent_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (rid, after_seq, limit),
            ).fetchall()
        events = [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
        return {
            "run_id": rid,
            "events": events,
            "next_seq": events[-1]["seq"] if events else after_seq,
        }

    def _evaluate(self, command):
        if command.operation == "reports.dashboard":
            return self._report(command.input)
        from .customer import Customers

        p = Customers(self.root, self.store).get(command.input.project_id)
        if (
            p["revision"] != command.input.expected_revision
            or p["product"]["revision"] != command.input.expected_product_revision
        ):
            raise Problem("STALE_INPUT")
        product = p["product"]
        refs = [{"kind": "project", "id": p["id"], "revision": p["revision"]}]
        for key, kind in (
            ("current_review_id", "fact_review"),
            ("current_draft_id", "script_draft"),
        ):
            if product[key]:
                refs.append({"kind": kind, "id": product[key], "revision": product["revision"]})
        if p["job"]:
            refs.append({"kind": "job", "id": p["job"]["id"]})
        if command.operation == "project.produce":
            from .agent_runtime import build_plan

            data = build_plan(p, command.input.policy.model_dump())
        elif command.operation == "creative.recommend":
            if not p["recommendations"]:
                raise Problem("HUMAN_CONFIRMATION_REQUIRED")
            data = {**p["recommendations"], "selection_requires_human": True}
        elif command.operation == "project.check":
            data = {
                "check_scope": "metadata_only;no_decode_or_source_integrity_verification",
                "preparation_blockers": p["preparation_blockers"],
                "inputs_changed": p["inputs_changed"],
                "alignment_status": p["alignment"]["status"] if p["alignment"] else None,
                "human_gates": HUMAN_GATES,
                "execution_enabled": False,
            }
        else:
            draft = next(
                (d for d in product["script_drafts"] if d["id"] == product["current_draft_id"]),
                None,
            )
            review = next(
                (r for r in product["fact_reviews"] if r["id"] == product["current_review_id"]),
                None,
            )
            fact_ids = set(review["fact_ids"] if review else [])
            data = {
                "project_id": p["id"],
                "title": product["title"],
                "revision": p["revision"],
                "product_revision": product["revision"],
                "product_status": product["status"],
                "confirmed_facts": [
                    {k: f[k] for k in ("id", "text", "source_id", "locator")}
                    for f in product["facts"]
                    if f["id"] in fact_ids
                ],
                "current_draft": {"id": draft["id"], "scenes": draft["payload"]} if draft else None,
                "media": [
                    {k: a[k] for k in ("id", "name", "kind", "role", "sha256")} for a in p["media"]
                ],
                "job": {k: p["job"][k] for k in ("id", "status", "storyboard_revision")}
                if p["job"]
                else None,
            }
        return data, refs, p["revision"]

    def _report(self, spec):
        from .reporting import Reporting

        report = Reporting(self.root, self.store).dashboard(
            spec.account_id, spec.start_date, spec.end_date
        )
        refs = [
            {"kind": "report_batch", "id": b["id"], "sha256": b["sha256"]}
            for b in report["batches"]
        ]
        data = {
            k: report[k]
            for k in (
                "start_date",
                "end_date",
                "status",
                "missing_dates",
                "totals",
                "observed_totals",
                "ratios",
                "daily",
                "basis",
                "attribution",
                "notes",
                "generated_at",
            )
        }
        data.update(
            account={k: report["account"][k] for k in ("id", "platform", "currency", "timezone")},
            materials=report["materials"][: spec.material_limit],
            material_count=len(report["materials"]),
            truncated=len(report["materials"]) > spec.material_limit,
            snapshot_policy="observed_at_proposal;not_a_P15_review_snapshot",
        )
        return data, refs, None
