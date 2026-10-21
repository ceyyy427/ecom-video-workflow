"""P13 contracts and immutable proposal receipts. No model or production data."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_customer import approve, client, picture, project

from ecom_video.db import Store


def command(pid, revision=0, request_id="proposal-1", operation="project.read"):
    return {
        "schema_version": 1,
        "request_id": request_id,
        "operation": operation,
        "input": {"project_id": pid, "expected_revision": revision, "expected_product_revision": 0},
    }


@pytest.fixture
def service(tmp_path, monkeypatch):
    from ecom_video.agent_service import AgentService

    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    return AgentService(tmp_path, Store(tmp_path / "workflow.db"))


def test_catalog_contains_only_four_local_read_tools():
    from ecom_video.agent_service import capabilities

    cap = capabilities()
    assert {t["name"] for t in cap["tools"]} == {
        "project.read",
        "project.check",
        "creative.recommend",
        "reports.dashboard",
    }
    assert all(t["effect"] == "read" for t in cap["tools"])
    assert cap["execution_enabled"] is False and cap["cloud_calls_enabled"] is False
    assert cap["model_policy"] == "local_first"
    assert cap["human_gates"] == ["facts", "script", "style", "voice_alignment", "film_review"]
    for tool in cap["tools"]:
        assert tool["input_schema"]["additionalProperties"] is False
        assert "requires_confirmations" in tool
    creative = next(t for t in cap["tools"] if t["name"] == "creative.recommend")
    assert creative["requires_confirmations"] == ["facts", "script"]


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "jobs.submit"},
        {"operation": "platform.publish"},
        {"reviewer": "forged"},
        {"api_key": "NEVER_PERSIST_SECRET"},
        {"url": "https://evil.test"},
        {"schema_version": 2},
        {"schema_version": True},
        {"request_id": "bad\ncommand"},
        {"input": {"project_id": "../outside", "expected_revision": 0}},
        {"input": {"project_id": "a" * 32, "expected_revision": True}},
        {"input": {"project_id": "a" * 32, "expected_revision": 0, "path": "/etc/passwd"}},
    ],
)
def test_strict_commands_reject_unregistered_input(change):
    from ecom_video.agent_contracts import parse_command

    with pytest.raises(ValidationError):
        parse_command({**command("a" * 32), **change})


def test_provider_contract_is_data_only_and_hides_credentials():
    from ecom_video.providers.contracts import ProviderRequest

    r = ProviderRequest(
        kind="vision",
        input_refs=[{"kind": "asset", "id": "a" * 32}],
        credential_ref=None,
        deadline_s=5,
        max_calls=1,
        max_cost_cny="0",
    )
    assert r.kind == "vision"
    with pytest.raises(ValidationError):
        ProviderRequest(**{**r.model_dump(), "api_key": "secret"})
    with pytest.raises(ValidationError):
        ProviderRequest(**{**r.model_dump(), "endpoint": "https://evil.test"})


def test_unknown_project_is_persisted_as_safe_failed_record(service):
    result = service.create(command("a" * 32))
    assert result["status"] == "failed" and result["error"]["code"] == "NOT_FOUND"
    assert result["error"]["retryable"] is False
    assert result["usage"] == {"model_calls": 0, "cloud_calls": 0, "platform_writes": 0}
    assert service.get(result["run_id"]) == result
    events = service.events(result["run_id"], 0, 100)
    assert [x["type"] for x in events["events"]] == ["request_accepted", "tool_failed"]
    seq = events["events"][0]["seq"]
    assert len(service.events(result["run_id"], seq, 100)["events"]) == 1
    assert service.events(result["run_id"], events["next_seq"], 100)["events"] == []


def test_feature_disabled_and_invalid_command_do_not_create_receipt(service, monkeypatch):
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "0")
    assert service.create(command("a" * 32))["error"]["code"] == "AGENT_DISABLED"
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    result = service.create({**command("a" * 32), "secret": "NEVER_PERSIST_SECRET"})
    assert result["error"]["code"] == "INVALID_INPUT" and result["run_id"] is None
    with service.store.connect() as c:
        assert c.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0


def test_concurrent_replay_is_single_immutable_record(service):
    cmd = command("a" * 32)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: service.create(cmd), range(6)))
    assert all(x == results[0] for x in results)
    different = service.create({**cmd, "operation": "project.check"})
    assert different["error"]["code"] == "REQUEST_CONFLICT" and different["run_id"] is None
    with service.store.connect() as c:
        assert c.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 2


def test_local_proposal_does_not_change_domain_or_approve(service, monkeypatch):
    from ecom_video.customer import Customers

    c = client(service.root)
    p = picture(c, project(c))
    p = approve(c, p)
    before = Customers(service.root, service.store).get(p["id"])
    with service.store.connect() as conn:
        counts = {
            t: conn.execute("SELECT count(*) FROM " + t).fetchone()[0]
            for t in ["jobs", "reviews", "script_approvals", "media_analyses", "report_syncs"]
        }

    def forbidden(*a, **kw):
        raise AssertionError("P13 must not dispatch domain actions")

    monkeypatch.setattr(Customers, "prepare", forbidden)
    monkeypatch.setattr(Customers, "plan", forbidden)
    for op in ("project.read", "project.check", "creative.recommend"):
        cmd = command(p["id"], p["revision"], op.replace(".", "-"), op)
        cmd["input"]["expected_product_revision"] = p["product"]["revision"]
        result = service.create(cmd)
        assert result["status"] == "proposed", result
        assert result["error"] is None and result["output_refs"]
        if op == "creative.recommend":
            assert len(result["data"]["options"]) == 3
            assert result["data"]["selection_requires_human"] is True
    after = Customers(service.root, service.store).get(p["id"])
    assert before == after
    with service.store.connect() as conn:
        assert all(
            conn.execute("SELECT count(*) FROM " + t).fetchone()[0] == n for t, n in counts.items()
        )
    cmd = command(p["id"], p["revision"] + 1, "stale")
    cmd["input"]["expected_product_revision"] = p["product"]["revision"]
    stale = service.create(cmd)
    assert stale["error"]["code"] == "STALE_INPUT"
    assert c.post("/api/customer-projects/" + p["id"] + "/plan", json={}).status_code == 422


def test_unconfirmed_script_cannot_get_style_recommendations(service):
    p = project(client(service.root))
    cmd = command(p["id"], p["revision"], operation="creative.recommend")
    cmd["input"]["expected_product_revision"] = p["product"]["revision"]
    r = service.create(cmd)
    assert r["error"]["code"] == "HUMAN_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("operation", ["project.read", "project.check", "creative.recommend"])
def test_product_version_changes_reject_new_proposals_but_keep_old_replay(service, operation):
    c = client(service.root)
    p = approve(c, picture(c, project(c)))
    cmd = command(p["id"], p["revision"], operation=operation)
    cmd["input"]["expected_product_revision"] = p["product"]["revision"]
    first = service.create(cmd)
    assert first["status"] == "proposed"
    # Only the product revision changes; the customer project revision is unchanged.
    prod = c.post(
        "/api/products/" + p["id"] + "/scripts",
        json={
            "revision": p["product"]["revision"],
            "scenes": [{"text": "奶白色杯身", "fact_ids": [p["product"]["facts"][0]["id"]]}],
        },
    )
    assert prod.status_code == 201
    assert prod.json()["revision"] > p["product"]["revision"]
    assert c.get("/api/customer-projects/" + p["id"]).json()["revision"] == p["revision"]
    assert service.create(cmd) == first, "immutable receipt replay must not re-evaluate"
    rejected = service.create({**cmd, "request_id": "after-product-change"})
    assert rejected["error"]["code"] == "STALE_INPUT"


def test_events_cursor_is_bounded_to_sqlite_integer(service):
    from ecom_video.agent_contracts import Problem

    rid = service.create(command("a" * 32))["run_id"]
    with pytest.raises(Problem) as caught:
        service.events(rid, 2**63)
    assert caught.value.code == "INVALID_INPUT"
    assert service.events(rid, 2**63 - 1)["events"] == []


def test_unexpected_failure_is_masked_in_receipt_events_and_logs(service, monkeypatch, caplog):
    def broken(*a, **kw):
        raise RuntimeError("NEVER_PERSIST_SECRET /Users/private/secret-config")

    monkeypatch.setattr(service, "_evaluate", broken)
    r = service.create(command("a" * 32))
    assert r["error"]["code"] == "INTERNAL_ERROR"
    encoded = json.dumps([r, service.events(r["run_id"], 0, 100)], ensure_ascii=False) + caplog.text
    assert "NEVER_PERSIST_SECRET" not in encoded and "secret-config" not in encoded


def test_v8_migration_preserves_old_tables_and_legacy_snapshot(tmp_path):
    folder = Path(__file__).resolve().parents[1] / "ecom_video/migrations"
    path = tmp_path / "workflow.db"
    with sqlite3.connect(path) as c:
        for sql in sorted(folder.glob("00[1-8]_*.sql")):
            c.executescript(sql.read_text())
        c.execute("PRAGMA user_version=8")
        # A real legacy frozen job must not gain new meanings during migration.
        c.execute(
            "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at,snapshot) VALUES(?,?,?,?,?,?,?,?)",
            ("old", "旧片", "旧文稿", 2, "needs_review", 1, 1, '{"script":"旧文稿","assets":[]}'),
        )
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {
            t: c.execute('SELECT * FROM "' + t + '"').fetchall()
            for t in tables
            if t not in ["schema_migrations", "sqlite_sequence"]
        }
    store = Store(path)
    with store.connect() as c:
        from ecom_video.db import SCHEMA_VERSION

        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert all(
            [tuple(r) for r in c.execute('SELECT * FROM "' + t + '"')] == rows
            for t, rows in before.items()
        )
        assert c.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
    assert store.get("old")["status"] == "needs_review"
    assert store.get("old")["snapshot"] == {"script": "旧文稿", "assets": []}
