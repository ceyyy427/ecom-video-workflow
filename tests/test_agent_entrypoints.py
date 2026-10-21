"""CLI/API parity, disabled default, output hygiene and existing local boundaries."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from test_agent_contracts import command
from test_customer import client, project

ROOT = Path(__file__).resolve().parents[1]


def cli(data, *args, payload=None, enabled=True):
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "ECOM_AGENT_ENABLED": "1" if enabled else "0",
    }
    return subprocess.run(
        [sys.executable, "-B", "-m", "ecom_video.agent_cli", "--data", str(data), *args],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=20,
    )


def test_help_invalid_input_disabled_and_missing_reads_do_not_create_database(tmp_path):
    root = tmp_path / "not-created"
    r = cli(root, "--help")
    assert r.returncode == 0 and "capabilities" in r.stdout
    assert not root.exists()
    r = cli(root, "run", "--input", "-", payload={"api_key": "NEVER_PRINT_SECRET"})
    assert r.returncode == 2
    assert json.loads(r.stdout)["error"]["code"] == "INVALID_INPUT"
    assert "NEVER_PRINT_SECRET" not in r.stdout + r.stderr and not root.exists()
    r = cli(root, "run", "--input", "-", payload=command("a" * 32), enabled=False)
    assert r.returncode == 1 and json.loads(r.stdout)["error"]["code"] == "AGENT_DISABLED"
    assert not root.exists()
    r = cli(root, "get", "a" * 32)
    assert r.returncode == 1 and json.loads(r.stdout)["error"]["code"] == "NOT_FOUND"
    assert not root.exists()
    r = cli(root, "events", "a" * 32, "--after-seq", str(2**63))
    assert r.returncode == 2 and json.loads(r.stdout)["error"]["code"] == "INVALID_INPUT"
    assert not root.exists()
    r = cli(root, "--unknown=NEVER_PRINT_SECRET")
    assert r.returncode == 2 and "NEVER_PRINT_SECRET" not in r.stdout + r.stderr


def test_default_disabled_capabilities_do_not_offer_execution(tmp_path, monkeypatch):
    monkeypatch.delenv("ECOM_AGENT_ENABLED", raising=False)
    c = client(tmp_path)
    cap = c.get("/api/agent/capabilities")
    assert cap.status_code == 200 and cap.json()["enabled"] is False
    r = c.post("/api/agent/runs", json=command("a" * 32))
    assert r.status_code == 403 and r.json()["error"]["code"] == "AGENT_DISABLED"
    assert c.post("/api/agent/runs/" + "a" * 32 + "/execute", json={}).status_code == 404
    assert c.post("/api/agent/runs/" + "a" * 32 + "/resume", json={}).status_code == 404


def test_api_cli_parity_and_records_survive_fresh_process(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    c = client(tmp_path)
    p = project(c)
    cmd = command(p["id"], p["revision"])
    cmd["input"]["expected_product_revision"] = p["product"]["revision"]
    r = c.post("/api/agent/runs", json=cmd)
    assert r.status_code == 201, r.text
    result = r.json()
    r = cli(tmp_path, "run", "--input", "-", payload=cmd)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == result
    r = cli(tmp_path, "get", result["run_id"])
    assert r.returncode == 0 and json.loads(r.stdout) == result
    api_events = c.get("/api/agent/runs/" + result["run_id"] + "/events").json()
    r = cli(tmp_path, "events", result["run_id"])
    assert r.returncode == 0 and json.loads(r.stdout) == api_events
    # Input inspection is intentionally not an OS path API.
    assert "path" not in result["data"]
    fresh = client(tmp_path)
    assert fresh.get("/api/agent/runs/" + result["run_id"]).json() == result
    assert "provider_transports" in json.loads(cli(tmp_path, "capabilities").stdout)


def test_agent_errors_are_structured_and_legacy_errors_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    c = client(tmp_path)
    for payload in (
        {},
        [],
        {**command("a" * 32), "confirmed": True},
        {**command("a" * 32), "operation": "voice.synthesize"},
    ):
        r = c.post("/api/agent/runs", json=payload)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"
    r = c.post("/api/agent/runs", content="not-json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"
    r = c.post("/api/agent/runs", json=command("a" * 32))
    assert r.status_code == 404 and r.json()["status"] == "failed" and r.json()["run_id"]
    rid = r.json()["run_id"]
    assert c.get("/api/agent/runs/" + rid).status_code == 200
    assert c.get("/api/agent/runs/" + rid + "/events?after_seq=-1").status_code == 422
    assert c.get("/api/agent/runs/not-an-id").json()["error"]["code"] == "INVALID_INPUT"
    assert c.post("/api/jobs", json={}).status_code == 422
    assert "detail" in c.post("/api/jobs", json={}).json()
    r = c.post("/api/agent/runs", json=command("a" * 32), headers={"origin": "https://evil.test"})
    assert r.status_code == 403
    c.headers.pop("X-Workflow-Token")
    assert c.post("/api/agent/runs", json=command("a" * 32)).status_code == 403
    assert c.get("/api/agent/capabilities", headers={"Host": "evil.test"}).status_code == 400


def test_reports_tool_preserves_unknowns_limits_output_and_never_syncs(tmp_path, monkeypatch):
    from test_reporting import HEADER

    from ecom_video.distribution import Distribution
    from ecom_video.reporting import Reporting

    monkeypatch.setenv("ECOM_AGENT_ENABLED", "1")
    c = client(tmp_path)
    store = c.app.state.store
    dist = Distribution(tmp_path, store)
    account = dist.add_account("fixture", "qianchuan", "123")
    reports = Reporting(tmp_path, store)
    reports.import_csv(
        account["id"],
        "2026-10-01",
        "2026-10-01",
        (HEADER + "2026-10-01,123,0,0,0,,0,,\n2026-10-01,456,1,2,1,,0,,\n").encode(),
        "fixture",
        True,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("P13 must not synchronize reports")

    monkeypatch.setattr(Reporting, "enqueue", forbidden)
    cmd = {
        "schema_version": 1,
        "request_id": "report-1",
        "operation": "reports.dashboard",
        "input": {
            "account_id": account["id"],
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
            "material_limit": 1,
        },
    }
    r = c.post("/api/agent/runs", json=cmd)
    assert r.status_code == 201, r.text
    out = r.json()["data"]
    assert out["status"] == "partial" and out["totals"]["spend"] is None
    assert out["totals"]["orders"] is None and out["ratios"]["payment_roi"] is None
    assert out["observed_totals"]["spend"] == "1"
    assert out["truncated"] is True and out["material_count"] == 2 and len(out["materials"]) == 1
    assert r.json()["output_refs"][0]["kind"] == "report_batch"
    assert "reports/" not in r.text and "auth_account_id" not in r.text
    assert cli(tmp_path, "run", "--input", "-", payload=cmd).returncode == 0
    assert c.get("/api/reports/syncs", params={"account_id": account["id"]}).json() == []
    for start, end in [
        ("2026-10-02", "2026-10-01"),
        ("2026-02-30", "2026-03-01"),
        ("2026-01-01", "2026-03-01"),
    ]:
        bad = copy.deepcopy(cmd)
        bad["input"].update(start_date=start, end_date=end)
        assert c.post("/api/agent/runs", json=bad).status_code == 422
