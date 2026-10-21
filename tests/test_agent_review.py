import pytest
from test_agent_recovery import SimulatedCrash, expire
from test_agent_runtime import choose, control, setup_run, start


def test_cancel_after_submit_does_not_cancel_borrowed_prior_job(tmp_path, monkeypatch):
    from test_customer import prepare

    from ecom_video.agent_service import AgentService

    c, p, _, runtime = setup_run(tmp_path, monkeypatch)
    p = prepare(c, p)
    from test_agent_runtime import policy

    proposal = AgentService(tmp_path, runtime.store).create(
        {
            "schema_version": 1,
            "request_id": "borrowed-after-submit",
            "operation": "project.produce",
            "input": {
                "project_id": p["id"],
                "expected_revision": p["revision"],
                "expected_product_revision": p["product"]["revision"],
                "policy": policy(),
            },
        }
    )
    start(proposal, runtime)
    choose(p, proposal, runtime)
    for _ in range(3):
        runtime.tick()
    assert runtime.store.get(p["job"]["id"])["status"] == "queued"
    e = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "cancel", control(proposal, e["revision"]))
    assert runtime.store.get(p["job"]["id"])["status"] == "queued"


def test_orphaned_inference_is_unknown_and_never_repeated(tmp_path, monkeypatch):
    from ecom_video.agent_guard import reserve_call

    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    choose(p, proposal, runtime)
    runtime.tick()
    calls = []

    def interrupted(*args, **kwargs):
        reserve_call()
        calls.append("reserved")
        raise SimulatedCrash

    monkeypatch.setattr(runtime.customers, "plan", interrupted)
    with pytest.raises(SimulatedCrash):
        runtime.tick()
    expire(runtime, proposal["run_id"])
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["status"] == "unknown" and e["error"]["code"] == "OUTCOME_UNKNOWN"
    assert calls == ["reserved"] and e["usage"]["model_calls"] == 1
    assert next(s for s in e["steps"] if s["step_key"] == "plan")["status"] == "unknown"


def test_expired_compute_lease_is_checked_synchronously(tmp_path):
    from ecom_video.db import Conflict, Store
    from ecom_video.resource_leases import Lease

    lease = Lease(Store(tmp_path / "workflow.db"))
    assert lease.acquire(now=100)
    with pytest.raises(Conflict):
        lease.check()


def test_plan_receipt_fences_compute_token_in_domain_transaction(tmp_path, monkeypatch):
    from ecom_video.db import Conflict
    from ecom_video.resource_leases import Lease

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    e = runtime.claim()
    lease = Lease(runtime.store)
    lease.acquire()
    with runtime.store.transaction() as c:
        c.execute("UPDATE resource_leases SET token=? WHERE name=?", ("new-owner", lease.name))
    with runtime.store.transaction() as c, pytest.raises(Conflict):
        runtime.receipt(e, "plan", "job", resource=lease).guard(c)


def test_proposed_plan_cannot_pause_then_resume_without_deadline(tmp_path, monkeypatch):
    from ecom_video.agent_contracts import Problem

    _, _, proposal, runtime = setup_run(tmp_path, monkeypatch)
    with pytest.raises(Problem, match="DOMAIN_REJECTED"):
        runtime.control(proposal["run_id"], "pause", control(proposal))


def test_pause_allows_inflight_plan_to_commit_then_resume_without_repeat(tmp_path, monkeypatch):
    from ecom_video.agent_contracts import Problem
    from ecom_video.agent_guard import reserve_call

    _, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    choose(p, proposal, runtime)
    runtime.tick()
    original = runtime.customers.plan

    def pause_during_plan(*args, **kwargs):
        reserve_call()
        e = runtime.get(proposal["run_id"])
        runtime.control(proposal["run_id"], "pause", control(proposal, e["revision"]))
        e = runtime.get(proposal["run_id"])
        with pytest.raises(Problem, match="DOMAIN_REJECTED"):
            runtime.control(proposal["run_id"], "resume", control(proposal, e["revision"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.customers, "plan", pause_during_plan)
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["status"] == "paused"
    assert runtime.effect(proposal["run_id"], "plan") is not None
    assert not e["inflight_step"]
    runtime.control(proposal["run_id"], "resume", control(proposal, e["revision"]))
    runtime.tick()
    e = runtime.get(proposal["run_id"])
    assert e["status"] == "running" and e["usage"]["model_calls"] == 1


def test_waiting_film_poll_does_not_change_revision_or_append_duplicate_events(
    tmp_path, monkeypatch
):
    _, p, proposal, runtime = setup_run(tmp_path, monkeypatch)
    start(proposal, runtime)
    choose(p, proposal, runtime)
    for _ in range(3):
        runtime.tick()
    e = runtime.get(proposal["run_id"])
    with runtime.store.transaction() as c:
        c.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (e["job_id"],))
    runtime.tick()
    before = runtime.get(proposal["run_id"])
    with runtime.store.connect() as c:
        count = c.execute("SELECT count(*) FROM agent_events").fetchone()[0]
    for _ in range(3):
        runtime.tick()
    after = runtime.get(proposal["run_id"])
    assert after["revision"] == before["revision"] and after["waiting_for"] == "film_review"
    with runtime.store.connect() as c:
        assert c.execute("SELECT count(*) FROM agent_events").fetchone()[0] == count
