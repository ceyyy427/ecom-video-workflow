import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from ecom_video.agent_service import AgentService
from ecom_video.db import Store


def policy(**changes):
    return {
        "policy_id": "local-v1",
        "max_steps": 40,
        "max_elapsed_s": 1800,
        "max_model_calls": 40,
        "max_cost_cny": "0",
        **changes,
    }


def setup_run(tmp_path, monkeypatch, *, approve=True, settings=None, limits=None):
    from test_customer import approve as human_approve
    from test_customer import client, picture, project

    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    monkeypatch.setenv("ECOM_AGENT_EXECUTION_ENABLED", "1")
    c = client(tmp_path)
    p = picture(c, project(c))
    if settings:
        p = c.put(
            "/api/customer-projects/" + p["id"],
            json={"revision": p["revision"], "settings": {**p["settings"], **settings}},
        ).json()
    if approve:
        p = human_approve(c, p)
    s = c.app.state.store
    command = {
        "schema_version": 1,
        "request_id": "produce-001",
        "operation": "project.produce",
        "input": {
            "project_id": p["id"],
            "expected_revision": p["revision"],
            "expected_product_revision": p["product"]["revision"],
            "policy": limits or policy(),
        },
    }
    proposal = AgentService(tmp_path, s).create(command)
    assert proposal["status"] == "proposed", proposal
    from ecom_video.agent_runtime import Runtime

    runtime = Runtime(tmp_path, s)
    return c, p, proposal, runtime


def control(proposal, revision=0):
    return {
        "plan_hash": proposal["data"]["plan_hash"],
        "revision": revision,
        "policy_id": "local-v1",
    }


def start(proposal, runtime):
    return runtime.control(proposal["run_id"], "execute", control(proposal))


def choose(p, proposal, runtime):
    return runtime.choose(
        proposal["run_id"],
        {
            "revision": runtime.get(proposal["run_id"])["revision"],
            "plan_hash": proposal["data"]["plan_hash"],
            "policy_id": "local-v1",
            "style_id": "cinema",
            "direction_basis": p["direction_basis"],
            "reviewer": "AUTOMATED FIXTURE style reviewer",
            "confirmed": True,
        },
    )


def test_policy_is_strict_and_zero_cloud_only():
    from ecom_video.agent_runtime_contracts import Policy

    for change in [
        {"max_steps": 0},
        {"max_elapsed_s": True},
        {"max_model_calls": 501},
        {"max_cost_cny": "1"},
        {"endpoint": "https://example.org"},
    ]:
        with pytest.raises(ValidationError):
            Policy.model_validate(policy(**change))
    assert Policy.model_validate(policy()).max_cost_cny == "0"


def test_resource_lease_is_cross_connection_fenced_and_expires(tmp_path):
    from ecom_video.resource_leases import Lease

    s = Store(tmp_path / "workflow.db")
    a = Lease(s, "test", ttl=1)
    b = Lease(Store(tmp_path / "workflow.db"), "test", ttl=1)
    assert a.acquire(now=100)
    assert not b.acquire(now=100.5)
    assert b.acquire(now=102)
    assert not a.renew(now=102)
    a.release()
    assert not Lease(s, "test").acquire(now=102.1)
    b.release()
    assert Lease(s, "test").acquire(now=103)


def test_execution_stops_for_manual_facts_without_domain_dispatch(tmp_path, monkeypatch):
    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch, approve=False)
    start(proposal, runtime)
    assert runtime.tick()
    execution = runtime.get(proposal["run_id"])
    assert execution["status"] == "waiting_human"
    assert execution["waiting_for"] == "facts_script"
    assert c.get("/api/customer-projects/" + p["id"]).json()["job"] is None
    assert AgentService(tmp_path, c.app.state.store).get(proposal["run_id"]) == proposal


def test_style_wait_pause_resume_and_exactly_one_preparation(tmp_path, monkeypatch):
    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    for _ in range(4):
        runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["waiting_for"] == "style"
    paused = runtime.control(proposal["run_id"], "pause", control(proposal, e["revision"]))
    assert paused["status"] == "paused"
    assert not runtime.tick()
    choose(p, proposal, runtime)
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "resume", control(proposal, e["revision"]))
    for _ in range(6):
        runtime.tick()
    p = c.get("/api/customer-projects/" + p["id"]).json()
    assert p["job"]["storyboard"]["creative"]["style_id"] == "cinema"
    assert p["job"]["status"] in ["queued", "validating", "rendering", "needs_review"]
    assert len(p["versions"]) == 1
    with c.app.state.store.connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM agent_effects WHERE run_id=? AND step_key='prepare'",
                (proposal["run_id"],),
            ).fetchone()[0]
            == 1
        )


def test_control_binds_hash_policy_and_revision(tmp_path, monkeypatch):
    from ecom_video.agent_contracts import Problem

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    with pytest.raises(Problem, match="STALE_INPUT"):
        runtime.control(proposal["run_id"], "execute", {**control(proposal), "plan_hash": "0" * 64})
    start(proposal, runtime)
    with pytest.raises(Problem, match="STALE_INPUT"):
        runtime.control(proposal["run_id"], "pause", control(proposal))


def test_concurrent_start_is_idempotent(tmp_path, monkeypatch):
    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: start(proposal, runtime), range(5)))
    assert {r["status"] for r in results} == {"queued"}
    assert {r["revision"] for r in results} == {1}


def test_old_script_input_cannot_resume_or_generate(tmp_path, monkeypatch):
    from ecom_video.agent_contracts import Problem

    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    runtime.tick()
    prod = c.get("/api/products/" + p["id"]).json()
    c.post("/api/products/" + p["id"] + "/scripts/generate", json={"revision": prod["revision"]})
    e = runtime.get(proposal["run_id"])
    with pytest.raises(Problem, match="STALE_INPUT"):
        runtime.control(proposal["run_id"], "resume", control(proposal, e["revision"]))
    runtime.tick()
    assert runtime.get(proposal["run_id"])["status"] == "failed"


def test_deadline_and_step_budget_fail_closed(tmp_path, monkeypatch):
    _, p, proposal, runtime = setup_run(tmp_path, monkeypatch, limits=policy(max_steps=1))
    start(proposal, runtime)
    choose(p, proposal, runtime)
    runtime.tick()
    runtime.tick()
    assert runtime.get(proposal["run_id"])["status"] == "failed"
    assert runtime.get(proposal["run_id"])["error"]["code"] == "BUDGET_EXCEEDED"
    with runtime.store.transaction() as c:
        c.execute(
            "UPDATE agent_executions SET status='queued',deadline=? WHERE run_id=?",
            (time.time() - 1, proposal["run_id"]),
        )
    runtime.tick()
    assert runtime.get(proposal["run_id"])["error"]["code"] == "DEADLINE_EXCEEDED"


def test_cancel_never_cancels_preexisting_job(tmp_path, monkeypatch):
    from test_customer import prepare

    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    original = prepare(c, p)["job"]["id"]
    # Fresh proposal binds the current production revision.
    p = c.get("/api/customer-projects/" + p["id"]).json()
    cmd = json.loads(
        json.dumps(
            {
                "schema_version": 1,
                "request_id": "existing",
                "operation": "project.produce",
                "input": {
                    "project_id": p["id"],
                    "expected_revision": p["revision"],
                    "expected_product_revision": p["product"]["revision"],
                    "policy": policy(),
                },
            }
        )
    )
    proposal = AgentService(tmp_path, runtime.store).create(cmd)
    start(proposal, runtime)
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "cancel", control(proposal, e["revision"]))
    assert runtime.store.get(original)["status"] == "draft"


def test_p13_records_survive_v10_migration(tmp_path):
    import sqlite3
    from pathlib import Path

    db = tmp_path / "workflow.db"
    migrations = Path("ecom_video/migrations")
    with sqlite3.connect(db) as c:
        for f in sorted(migrations.glob("*.sql"))[:9]:
            c.executescript(f.read_text())
        c.execute("PRAGMA user_version=9")
        c.execute(
            "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)",
            ("a" * 32, "old", "hash", "{}", "proposed", '{"legacy":true}', 1),
        )
    s = Store(db)
    with s.connect() as c:
        from ecom_video.db import SCHEMA_VERSION

        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert c.execute("SELECT result FROM agent_runs").fetchone()[0] == '{"legacy":true}'
