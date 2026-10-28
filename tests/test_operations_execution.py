"""D2 bridge uses the existing bounded executor, with no new approval authority."""

import json

from test_customer import approve, client
from test_operations_content import request_body


def adopted(tmp_path):
    from ecom_video.media import digest

    c = client(tmp_path)
    r = c.post("/api/operations/plans", json=request_body()).json()
    # Explicit engineering marker, never a customer preview or approval.
    marker = tmp_path / "engineering-preview-only.mp4"
    marker.write_bytes(b"AUTOMATED FIXTURE, not actual media")
    item = {k: {"path": marker.name, "sha256": digest(marker)} for k in ("video", "poster")}
    with c.app.state.store.transaction() as db:
        db.execute(
            "UPDATE idea_plans SET status='ready',previews=? WHERE id=?",
            (json.dumps({o["id"]: item for o in r["plan"]["options"]}), r["id"]),
        )
    o = r["plan"]["options"][0]
    p = c.post(
        f"/api/idea-plans/{r['id']}/adopt", json={"basis": r["basis"], "option_id": o["id"]}
    ).json()
    return c, r, o, p


def request(r, o, p):
    from test_agent_runtime import policy

    return {
        "request_id": "domestic-production-fixture",
        "plan_id": r["id"],
        "plan_basis": r["basis"],
        "option_id": o["id"],
        "project_id": p["id"],
        "expected_revision": p["revision"],
        "expected_product_revision": p["product"]["revision"],
        "policy": policy(),
    }


def test_compiler_binds_frozen_plan_and_keeps_human_gates(tmp_path, monkeypatch):
    from ecom_video.operations.execution import compile_plan, propose_execution

    c, r, o, p = adopted(tmp_path)
    for flag in ("ECOM_AGENT_ENABLED", "ECOM_AGENT_EXECUTION_ENABLED"):
        monkeypatch.setenv(flag, "1")
    missing = propose_execution(tmp_path, c.app.state.store, request(r, o, p))
    assert missing.status == "needs_human"
    assert not missing.legacy_result
    p = approve(c, p)
    cmd = compile_plan(tmp_path, c.app.state.store, request(r, o, p))
    assert cmd["command"]["operation"] == "project.produce"
    assert cmd["evidence_refs"][0]["id"] == r["id"]
    a = propose_execution(tmp_path, c.app.state.store, request(r, o, p))
    b = propose_execution(tmp_path, c.app.state.store, request(r, o, p))
    assert a.model_dump() == b.model_dump() and a.checkpoint_ref
    assert a.legacy_result.data["steps"][-1] == "human_film_review"
    from ecom_video.agent_runtime import Runtime

    runtime = Runtime(tmp_path, c.app.state.store)
    rid = a.checkpoint_ref.id
    execution = runtime.get(rid)
    bind = {
        "revision": execution["revision"],
        "plan_hash": execution["plan_hash"],
        "policy_id": "local-v1",
    }
    runtime.control(rid, "execute", bind)
    execution = runtime.get(rid)
    runtime.control(rid, "cancel", {**bind, "revision": execution["revision"]})
    assert runtime.get(rid)["status"] == "cancelled"
    assert (
        propose_execution(tmp_path, c.app.state.store, request(r, o, p)).model_dump()
        == a.model_dump()
    )
    with c.app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM agent_executions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM agent_choices").fetchone()[0] == 0


def test_native_http_proposal_rejects_stale_or_wrong_adoption_and_respects_disabled(
    tmp_path, monkeypatch
):
    c, r, o, p = adopted(tmp_path)
    p = approve(c, p)
    body = request(r, o, p)
    assert c.post("/api/operations/executions/propose", json=body).status_code == 403
    for flag in ("ECOM_AGENT_ENABLED", "ECOM_AGENT_EXECUTION_ENABLED"):
        monkeypatch.setenv(flag, "1")
    bad = {**body, "plan_basis": "0" * 64}
    assert c.post("/api/operations/executions/propose", json=bad).status_code == 409
    assert (
        c.post(
            "/api/operations/executions/propose",
            json={**body, "expected_revision": p["revision"] + 1},
        ).status_code
        == 409
    )
    bad = {**body, "policy": {**body["policy"], "max_cost_cny": "1"}}
    assert c.post("/api/operations/executions/propose", json=bad).status_code == 422
    result = c.post("/api/operations/executions/propose", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["legacy_result"]["operation"] == "project.produce"


def test_fallback_never_retries_uncertain_or_changed_inputs():
    from ecom_video.operations.execution import safe_fallback

    assert (
        safe_fallback({"code": "UNKNOWN", "outcome_uncertain": True}, "unknown")["action"] == "stop"
    )
    assert safe_fallback({"code": "STALE_INPUT"}, "failed")["action"] == "needs_human"
    assert safe_fallback({"code": "MODEL_NOT_READY"}, "waiting_human")["automatic_retry"] is False


def test_installed_copy_can_reuse_explicit_local_asr_cache_without_reconfiguring_original(
    tmp_path, monkeypatch
):
    from ecom_video.alignment import model_path

    monkeypatch.setenv("ECOM_ASR_MODEL_DIR", str(tmp_path))
    assert model_path() == tmp_path
    import pytest

    with pytest.raises(ValueError):
        model_path(verify=True)
    monkeypatch.setenv("ECOM_ASR_MODEL_DIR", "relative/path")
    with pytest.raises(ValueError):
        model_path()
