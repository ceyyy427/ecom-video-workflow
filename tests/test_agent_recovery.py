import json
import time

import pytest
from test_agent_runtime import choose, control, policy, setup_run, start


class SimulatedCrash(BaseException):
    pass


def expire(runtime, rid):
    with runtime.store.transaction() as c:
        c.execute(
            "UPDATE agent_executions SET lease_until=? WHERE run_id=?", (time.time() - 1, rid)
        )


def test_prepare_commit_survives_crash_before_coordinator_ack(tmp_path, monkeypatch):
    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    original = runtime.customers.prepare

    def after_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedCrash

    monkeypatch.setattr(runtime.customers, "prepare", after_commit)
    with pytest.raises(SimulatedCrash):
        runtime.tick()
    rid = proposal["run_id"]
    expire(runtime, rid)
    from ecom_video.agent_runtime import Runtime

    recovered = Runtime(tmp_path, runtime.store)
    recovered.tick()
    p = c.get("/api/customer-projects/" + p["id"]).json()
    assert len(p["versions"]) == 1
    assert recovered.get(rid)["waiting_for"] == "style"
    assert recovered.get(rid)["steps_used"] == 1


def test_before_domain_commit_is_safe_to_resume_with_budget_preserved(tmp_path, monkeypatch):
    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    original = runtime.customers.prepare
    monkeypatch.setattr(
        runtime.customers, "prepare", lambda *a, **k: (_ for _ in ()).throw(SimulatedCrash())
    )
    with pytest.raises(SimulatedCrash):
        runtime.tick()
    expire(runtime, proposal["run_id"])
    monkeypatch.setattr(runtime.customers, "prepare", original)
    runtime.tick()
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["waiting_for"] == "style" and e["steps_used"] == 2
    assert e["steps"][0]["attempts"] == 2


def test_cancel_fences_pending_domain_transaction(tmp_path, monkeypatch):
    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    original = runtime.customers.prepare

    def cancel_first(*args, **kwargs):
        e = runtime.get(proposal["run_id"])
        runtime.control(proposal["run_id"], "cancel", control(proposal, e["revision"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.customers, "prepare", cancel_first)
    runtime.tick()
    assert runtime.get(proposal["run_id"])["status"] == "cancelled"
    assert c.get("/api/customer-projects/" + p["id"]).json()["job"] is None
    with runtime.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_effects").fetchone()[0] == 0


def test_cancel_owned_draft_preserves_prior_script_approval_job(tmp_path, monkeypatch):
    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    approved = p["product"]["script_approvals"][0]["job_id"]
    start(proposal, runtime)
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "cancel", control(proposal, e["revision"]))
    assert runtime.store.get(e["job_id"])["status"] == "cancelled"
    assert runtime.store.get(approved)["status"] == "draft"


def test_local_call_budget_reserved_before_inference_and_not_reset(tmp_path, monkeypatch):
    from ecom_video.agent_contracts import Problem
    from ecom_video.agent_guard import reserve_call, scope

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch, limits=policy(max_model_calls=1))
    start(proposal, runtime)
    with scope(runtime.store, proposal["run_id"]):
        reserve_call()
        with pytest.raises(Problem, match="BUDGET_EXCEEDED"):
            reserve_call()
    assert runtime.get(proposal["run_id"])["usage"]["model_calls"] == 1
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "pause", control(proposal, e["revision"]))
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "resume", control(proposal, e["revision"]))
    assert runtime.get(proposal["run_id"])["usage"]["model_calls"] == 1


def test_missing_committed_child_is_unknown_not_replayed(tmp_path, monkeypatch):
    _, p, proposal, runtime = setup_run(tmp_path, monkeypatch, settings={"auto_select": True})
    start(proposal, runtime)
    runtime.tick()
    with runtime.store.transaction() as c:
        c.execute("DELETE FROM media_analyses")
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["status"] == "unknown" and e["error"]["outcome_uncertain"]


def test_expired_lease_holder_cannot_commit_after_reclaim(tmp_path, monkeypatch):
    from ecom_video.db import Conflict

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    old = runtime.claim()
    expire(runtime, proposal["run_id"])
    new = runtime.claim()
    assert old["lease_token"] != new["lease_token"]
    with runtime.store.transaction() as c, pytest.raises(Conflict):
        runtime.receipt(old, "prepare", "job").guard(c)


def test_submit_commit_crash_does_not_duplicate_or_auto_review(tmp_path, monkeypatch):
    _, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    choose(p, proposal, runtime)
    runtime.tick()
    runtime.tick()
    original = runtime.customers.submit

    def after_commit(*a, **k):
        original(*a, **k)
        raise SimulatedCrash

    monkeypatch.setattr(runtime.customers, "submit", after_commit)
    with pytest.raises(SimulatedCrash):
        runtime.tick()
    expire(runtime, proposal["run_id"])
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    job = runtime.store.get(e["job_id"])
    assert job["status"] == "queued" and job["attempts"] == 0
    with runtime.store.connect() as c:
        assert (
            c.execute("SELECT count(*) FROM agent_effects WHERE step_key='submit'").fetchone()[0]
            == 1
        )
        assert c.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0


def test_api_and_cli_execution_share_receipts_and_manual_style(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    rid = proposal["run_id"]
    base = "/api/agent/runs/" + rid
    assert (
        c.post(
            base + "/execute", json=control(proposal), headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    r = c.post(base + "/execute", json=control(proposal))
    assert r.status_code == 200, r.text
    assert c.get(base + "/execution").json()["status"] == "queued"
    file = tmp_path / "control.json"
    file.write_text(json.dumps(control(proposal, 1)))
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "ecom_video.agent_cli",
            "--data",
            str(tmp_path),
            "pause",
            rid,
            "--input",
            str(file),
        ],
        text=True,
        capture_output=True,
        env={**os.environ, "ECOM_AGENT_ENABLED": "1", "ECOM_AGENT_EXECUTION_ENABLED": "1"},
    )
    assert child.returncode == 0, child.stderr
    paused = json.loads(child.stdout)
    assert paused["status"] == "paused"
    r = c.post(
        base + "/style",
        json={
            **control(proposal, paused["revision"]),
            "style_id": "cinema",
            "direction_basis": p["direction_basis"],
            "reviewer": "AUTOMATED FIXTURE human choice",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    assert c.post(base + "/resume", json=control(proposal, r.json()["revision"])).status_code == 200
    assert c.get("/api/agent/executions", params={"project_id": p["id"]}).json()[0]["run_id"] == rid
