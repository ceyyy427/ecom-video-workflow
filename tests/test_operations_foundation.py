"""D0 bridge uses old immutable read receipts; no executor or new approval."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_agent_contracts import command

ROOT = Path(__file__).resolve().parents[1]


def test_default_catalog_only_admits_existing_reads_and_disables_new_execution(monkeypatch):
    from ecom_video.operations.tools import capabilities, read_tools

    monkeypatch.delenv("ECOM_OPERATIONS_ENABLED", raising=False)
    cap = capabilities()
    assert cap["enabled"] is False and cap["execution_enabled"] is False
    assert cap["cloud_calls_enabled"] is False and cap["platform_writes_enabled"] is False
    assert {t.id for t in read_tools()} == {
        "project.read",
        "project.check",
        "creative.recommend",
        "reports.dashboard",
    }


def test_d0_read_bridge_is_idempotent_and_has_no_domain_effects(tmp_path, monkeypatch):
    from ecom_video.agent_service import AgentService
    from ecom_video.db import Store
    from ecom_video.operations.tools import propose_read

    monkeypatch.setenv("ECOM_OPERATIONS_ENABLED", "1")
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    store = Store(tmp_path / "workflow.db")
    service = AgentService(tmp_path, store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(
            pool.map(lambda _: propose_read(service, command("a" * 32)).model_dump(), range(4))
        )
    assert all(o == outputs[0] for o in outputs)
    assert outputs[0]["status"] == "failed" and outputs[0]["error"]["code"] == "NOT_FOUND"
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 2
        for table in ["jobs", "reviews", "script_approvals", "agent_executions", "qianchuan_tasks"]:
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    before = store.path.read_bytes()
    for invalid in (
        {**command("a" * 32), "operation": "platform.publish"},
        {**command("a" * 32), "confirmed": True},
        {**command("a" * 32), "operation": "project.produce"},
    ):
        assert propose_read(service, invalid).error.code == "INVALID_INPUT"
    assert store.path.read_bytes() == before
    monkeypatch.setenv("ECOM_OPERATIONS_ENABLED", "0")
    assert propose_read(service, command("a" * 32)).error.code == "OPERATIONS_DISABLED"


def test_acceptance_rejects_future_stage_and_preexisting_workspace_without_writes(tmp_path):
    help_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/accept_domestic_suite.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert help_result.returncode == 0, help_result.stderr
    for args in (
        [
            "--stage",
            "video",
            "--workspace",
            str(tmp_path / "new"),
            "--manifest",
            "missing",
            "--mode",
            "engineering",
        ],
        [
            "--stage",
            "foundation",
            "--workspace",
            str(tmp_path),
            "--manifest",
            "missing",
            "--mode",
            "engineering",
        ],
    ):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts/accept_domestic_suite.py"), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r.returncode == 2, r.stderr
    assert not (tmp_path / "new").exists() and not list(tmp_path.iterdir())


def test_foundation_acceptance_restores_real_backup_without_making_approvals(tmp_path):
    from ecom_video.db import Store
    from ecom_video.maintenance import backup

    source = tmp_path / "source"
    store = Store(source / "workflow.db")
    job = store.create_job("AUTOMATED FIXTURE D0 旧草稿", "只读取，不自动审批")
    bundle = tmp_path / "backup"
    backup(source, bundle)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [], "legacy_backup_path": str(bundle)}))
    work = tmp_path / "acceptance"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/accept_domestic_suite.py"),
            "--stage",
            "foundation",
            "--workspace",
            str(work),
            "--manifest",
            str(manifest),
            "--mode",
            "engineering",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    report = json.loads((work / "acceptance.json").read_text())
    assert report["status"] == "passed" and report["domain_tables_unchanged"]
    assert report["files_unchanged"] and report["replay_single_receipt"]
    assert report["old_jobs_readable"] == 1 and report["approvals_added"] == 0
    assert store.get(job["id"])["status"] == "draft"
    assert not store.get(job["id"])["reviews"]


def test_read_bridge_does_not_expose_unexpected_exception_text(tmp_path, monkeypatch):
    from ecom_video.agent_service import AgentService
    from ecom_video.db import Store
    from ecom_video.operations.tools import propose_read

    monkeypatch.setenv("ECOM_OPERATIONS_ENABLED", "1")
    service = AgentService(tmp_path, Store(tmp_path / "workflow.db"))

    def unavailable(value):
        raise RuntimeError("NEVER_PRINT_SECRET")

    monkeypatch.setattr(service, "create", unavailable)
    out = propose_read(service, command("a" * 32))
    assert out.error.code == "INTERNAL_ERROR"
    assert "NEVER_PRINT_SECRET" not in out.model_dump_json()


def test_successful_read_preserves_unconfirmed_project_and_legacy_receipt(tmp_path, monkeypatch):
    from test_customer import client, project

    from ecom_video.agent_service import AgentService
    from ecom_video.customer import Customers
    from ecom_video.operations.tools import propose_read

    monkeypatch.setenv("ECOM_OPERATIONS_ENABLED", "1")
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    c = client(tmp_path)
    p = project(c)
    service = AgentService(tmp_path, c.app.state.store)
    before = Customers(tmp_path, service.store).get(p["id"])
    cmd = command(p["id"], p["revision"])
    cmd["input"]["expected_product_revision"] = p["product"]["revision"]
    out = propose_read(service, cmd)
    assert out.status == "completed" and out.legacy_result.status == "proposed"
    assert out.output_refs and out.warnings
    assert service.get(out.checkpoint_ref.id) == out.legacy_result.model_dump()
    assert Customers(tmp_path, service.store).get(p["id"]) == before
