"""D0 restore / D1 silent content acceptance in fresh external directories; no approvals."""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "验收参数或证据无效：须使用仓库外全新目录及有效本机清单，参见 --help。\n")


def fingerprints(path):
    """Deterministic row fingerprints; no private rows are included in the report."""
    from ecom_video.maintenance import readonly

    with readonly(path) as c:
        names = [
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        result = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = len(c.execute(f"PRAGMA table_info({quoted})").fetchall())
            order = ",".join(str(i + 1) for i in range(columns))
            h, count = hashlib.sha256(), 0
            for row in c.execute(f"SELECT * FROM {quoted} ORDER BY {order}"):
                h.update(repr(tuple(row)).encode())
                h.update(b"\n")
                count += 1
            result[name] = {"rows": count, "sha256": h.hexdigest()}
        return c.execute("PRAGMA user_version").fetchone()[0], result


def validate_inputs(args):
    work = args.workspace
    if not work.is_absolute() or work.exists() or work.is_symlink():
        raise ValueError("workspace must be new and absolute")
    work = work.resolve()
    if any((p / ".git").exists() for p in (work, *work.parents)):
        raise ValueError("workspace cannot be in a repository")
    manifest = args.manifest
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 256 * 1024:
        raise ValueError("invalid manifest")
    from ecom_video.operations.resources import no_duplicate_keys

    data = json.loads(manifest.read_bytes(), object_pairs_hook=no_duplicate_keys)
    if not isinstance(data, dict) or set(data) - {
        "cases",
        "legacy_backup_path",
        "benchmark_group_id",
    }:
        raise ValueError("invalid fields")
    if not isinstance(data.get("cases"), list) or len(data["cases"]) > 10:
        raise ValueError("invalid cases")
    bundle = Path(data["legacy_backup_path"])
    if not bundle.is_absolute() or not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("backup must be a real absolute directory")
    bundle = bundle.resolve()
    if work == bundle or work.is_relative_to(bundle) or bundle.is_relative_to(work):
        raise ValueError("workspace must not overlap input")
    from ecom_video.media import digest

    for case in data["cases"]:
        if not isinstance(case, dict) or not case.get("usage_scope"):
            raise ValueError("case usage required")
        paths, hashes = case["asset_paths"], case["asset_sha256"]
        if not isinstance(paths, list) or len(paths) != len(hashes) or len(paths) > 30:
            raise ValueError("invalid material list")
        for path, sha in zip(paths, hashes, strict=True):
            p = Path(path)
            if not p.is_absolute() or not p.is_file() or p.is_symlink() or digest(p) != sha:
                raise ValueError("material fingerprint mismatch")
    if args.stage == "content":
        from ecom_video.operations.acceptance import validate_cases

        validate_cases(data["cases"])
    return work, bundle


def run_foundation(work, bundle, mode):
    from concurrent.futures import ThreadPoolExecutor

    from ecom_video.agent_service import AgentService
    from ecom_video.db import SCHEMA_VERSION, Store
    from ecom_video.maintenance import restore, verify
    from ecom_video.media import digest
    from ecom_video.operations.resources import load_resources
    from ecom_video.operations.tools import propose_read

    resources = load_resources()
    verified = verify(bundle)
    # Existing parent is required; no recursive mkdir outside the explicit workspace.
    work.mkdir(mode=0o700)
    (work / ".domestic-foundation-acceptance").write_text("isolated D0; no customer approvals\n")
    restore(bundle, work / "restored")
    root = work / "restored"
    before_version, before = fingerprints(root / "workflow.db")
    source_manifest = json.loads((bundle / "backup.json").read_text())
    before_files = {r["path"]: r["sha256"] for r in source_manifest["files"]}
    store = Store(root / "workflow.db")
    after_version, after = fingerprints(root / "workflow.db")
    unchanged = all(after.get(t) == fp for t, fp in before.items() if t != "schema_migrations")
    if not unchanged or after_version != SCHEMA_VERSION:
        raise ValueError("old tables changed")
    for path, sha in before_files.items():
        if digest(root / path) != sha:
            raise ValueError("old file changed")
    with store.connect() as c:
        job_ids = [r[0] for r in c.execute("SELECT id FROM jobs")]
        plan_ids = [r[0] for r in c.execute("SELECT id FROM idea_plans")]
    for jid in job_ids:
        store.get(jid)
    from ecom_video.idea_plans import IdeaPlans

    plans = IdeaPlans(root, store)
    for pid in plan_ids:
        plan = plans.get(pid)
        if plan["status"] == "ready" and plan["repair_needed"]:
            raise ValueError("old preview is damaged")
    Store(root / "workflow.db")
    if fingerprints(root / "workflow.db")[1] != after:
        raise ValueError("repeat initialization changed rows")
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_AGENT_EXECUTION_ENABLED"] = "0"
    os.environ["ECOM_AGENT_ENABLED"] = "1"
    os.environ["ECOM_OPERATIONS_ENABLED"] = "1"
    bridge_root = work / "read-bridge-fixture"
    service = AgentService(bridge_root, Store(bridge_root / "workflow.db"))
    cmd = {
        "schema_version": 1,
        "request_id": "d0-engineering-read-only",
        "operation": "project.read",
        "input": {"project_id": "0" * 32, "expected_revision": 0, "expected_product_revision": 0},
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: propose_read(service, cmd).model_dump(), range(4)))
    with service.store.connect() as c:
        single = c.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1
        events = c.execute("SELECT count(*) FROM agent_events").fetchone()[0] == 2
        empty = all(
            c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            for table in (
                "jobs",
                "reviews",
                "script_approvals",
                "agent_executions",
                "qianchuan_tasks",
            )
        )
    if not (single and events and empty and all(r == results[0] for r in results)):
        raise ValueError("idempotency failed")
    report = {
        "phase": "D0",
        "stage": "foundation",
        "status": "passed",
        "mode": mode,
        "schema_before": before_version,
        "schema_after": after_version,
        "tables_checked": len(before) - 1,
        "domain_tables_unchanged": unchanged,
        "new_tables": sorted(set(after) - set(before)),
        "migration_registry_changed": before.get("schema_migrations")
        != after.get("schema_migrations"),
        "files_checked": len(before_files),
        "files_unchanged": True,
        "old_jobs_readable": len(job_ids),
        "old_preview_plans_readable": len(plan_ids),
        "repeat_initialization_unchanged": True,
        "replay_single_receipt": True,
        "approvals_added": 0,
        "model_calls": 0,
        "cloud_calls": 0,
        "platform_writes": 0,
        "fork_url": "https://github.com/" + resources.fork_repository,
        "fork_commit": resources.fork_commit,
        "upstream_commit": resources.upstream_commit,
        "resource_files": len(resources.entries),
        "backup_verified": verified,
        "customer_signoff": False,
    }
    (work / "table-fingerprints.json").write_text(
        json.dumps({"before": before, "after": after}, indent=2) + "\n"
    )
    (work / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--stage", choices=["foundation", "content"], required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=["engineering", "customer"], required=True)
    args = parser.parse_args(argv)
    try:
        work, bundle = validate_inputs(args)
        if args.stage == "foundation":
            report = run_foundation(work, bundle, args.mode)
        else:
            from ecom_video.operations.acceptance import run_content

            report = run_content(work, bundle, json.loads(args.manifest.read_bytes()), args.mode)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        parser.error("invalid inputs or validation failure")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
