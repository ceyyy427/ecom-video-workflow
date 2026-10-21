"""Offline P13 acceptance. All data/receipts/evidence live below --data, never var/."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def forbidden(*args, **kwargs):
    raise AssertionError("P13 acceptance forbids network and production actions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if not args.offline or data == ROOT or data.is_relative_to(ROOT):
        parser.error("Use --offline and an empty data directory outside the repository")
    if data.exists() and any(data.iterdir()):
        parser.error("Data directory must be empty; preserve existing acceptance runs")
    data.mkdir(parents=True, exist_ok=True)
    guard = data / "offline-guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def forbidden(*a, **kw):\n"
        "    raise AssertionError('P13_OFFLINE_NETWORK_FORBIDDEN')\n"
        "socket.socket.connect = forbidden\n"
        "socket.socket.connect_ex = forbidden\n"
    )
    os.environ["ECOM_AGENT_ENABLED"] = "1"
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(guard) + os.pathsep + str(ROOT),
    }
    from fastapi.testclient import TestClient

    from ecom_video.agent_service import capabilities
    from ecom_video.api import create_app
    from ecom_video.db import SCHEMA_VERSION, Store

    dbroot = data / "runtime"
    with (
        patch("socket.socket.connect", forbidden),
        patch("socket.socket.connect_ex", forbidden),
        patch("ecom_video.customer.Customers.prepare", forbidden),
        patch("ecom_video.customer.Customers.plan", forbidden),
        patch("ecom_video.db.Store.submit", forbidden),
        patch("ecom_video.db.Store.review", forbidden),
        patch("ecom_video.reporting.Reporting.enqueue", forbidden),
        TestClient(create_app(dbroot), base_url="http://localhost") as c,
    ):
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        p = c.post("/api/customer-projects", json={"title": "P13 离线验收，非客户审核"}).json()
        store = c.app.state.store
        with store.connect() as conn:
            tables = [
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if r[0] not in ["agent_runs", "agent_events", "sqlite_sequence"]
            ]
            before = {
                t: [list(row) for row in conn.execute('SELECT * FROM "' + t + '"')] for t in tables
            }
        cmd = {
            "schema_version": 1,
            "request_id": "accept-p13",
            "operation": "project.check",
            "input": {
                "project_id": p["id"],
                "expected_revision": p["revision"],
                "expected_product_revision": p["product"]["revision"],
            },
        }
        path = data / "command.json"
        path.write_text(json.dumps(cmd))
        result = c.post("/api/agent/runs", json=cmd)
        assert result.status_code == 201, result.text
        result = result.json()
        assert result["status"] == "proposed" and result["data"]["preparation_blockers"]
        assert result["data"]["execution_enabled"] is False
        child = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "ecom_video.agent_cli",
                "--data",
                str(dbroot),
                "run",
                "--input",
                str(path),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert child.returncode == 0, child.stderr
        assert json.loads(child.stdout) == result
        rid = result["run_id"]
        assert c.get("/api/agent/runs/" + rid).json() == result
        events = c.get("/api/agent/runs/" + rid + "/events").json()
        assert [x["type"] for x in events["events"]] == ["request_accepted", "proposal_ready"]
        assert (
            c.get(f"/api/agent/runs/{rid}/events?after_seq={events['next_seq']}").json()["events"]
            == []
        )
        blocked = c.post(
            "/api/agent/runs",
            json={**cmd, "request_id": "needs-human", "operation": "creative.recommend"},
        )
        assert (
            blocked.status_code == 409
            and blocked.json()["error"]["code"] == "HUMAN_CONFIRMATION_REQUIRED"
        )
        bad = c.post("/api/agent/runs", json={**cmd, "api_key": "FIXTURE_MUST_NOT_PERSIST"})
        assert bad.status_code == 422 and "FIXTURE_MUST_NOT_PERSIST" not in bad.text
        assert (
            c.post(
                "/api/agent/runs", json=cmd, headers={"Origin": "https://untrusted.test"}
            ).status_code
            == 403
        )
        assert (
            c.get("/api/agent/capabilities", headers={"Host": "untrusted.test"}).status_code == 400
        )
        assert c.post(f"/api/agent/runs/{rid}/execute", json={}).status_code == 404
        with store.connect() as conn:
            after = {
                t: [list(row) for row in conn.execute('SELECT * FROM "' + t + '"')] for t in tables
            }
            assert before == after, "P13 altered domain rows"
            assert conn.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 2
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # Reinitialization is a fresh service/store, not just a cached Python result.
        fresh = Store(dbroot / "workflow.db")
        from ecom_video.agent_service import AgentService

        assert AgentService(dbroot, fresh).get(rid) == result
        assert not any(
            x in json.dumps(result) for x in ["api_key", "secret_ref", "auth_account_id"]
        )
    vendor = ROOT / "vendor/MoneyPrinterTurbo"
    report = {
        "phase": "P13",
        "data": str(data),
        "run_id": rid,
        "cli_api_parity": True,
        "fresh_process_persistence": True,
        "idempotent_replay": True,
        "structured_errors": True,
        "domain_rows_unchanged": True,
        "human_gate_retained": True,
        "network_blocked": True,
        "model_calls": 0,
        "platform_writes": 0,
        "execution_endpoint_present": False,
        "live_provider_verified": False,
        "vendor_source_sha256": hashlib.sha256(
            (vendor / "app/services/video.py").read_bytes()
        ).hexdigest(),
        "tool_names": [t["name"] for t in capabilities()["tools"]],
    }
    (data / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
