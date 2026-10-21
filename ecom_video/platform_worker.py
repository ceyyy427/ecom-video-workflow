"""Persistent local export and read-only platform-report queue."""

import argparse
import time
from contextlib import suppress
from pathlib import Path

from .db import Conflict, Store
from .distribution import Distribution, encode
from .maintenance_lock import worker_guard
from .platforms.ocean_watch import OceanWatch
from .qianchuan_tasks import QianchuanTasks
from .qianchuan_worker import execute
from .reporting import Reporting, dates


def sync_native(reports, task, auth):
    account = reports.distribution.account(task["account_id"])
    token = auth.token(task["account_id"])
    if not auth.provider.authorized(token, account["advertiser_id"]):
        raise Conflict("平台未授权该广告主")
    responses = [
        auth.provider.report_day(token, account["advertiser_id"], day)
        for day in dates(task["start_date"], task["end_date"], 7)
    ]
    return reports.ingest(
        task["account_id"],
        task["start_date"],
        task["end_date"],
        [row for response in responses for row in response["rows"]],
        encode(responses).encode(),
        "qianchuan_api",
        task["actor"],
        {
            "scope": "complete_account_material_daily_snapshot",
            "endpoint": "/v1.0/qianchuan/report/material/get/",
            "request_ids": [rid for response in responses for rid in response["request_ids"]],
        },
        sync=task,
    )


@worker_guard(lambda root, store, native=None: root)
def tick(root, store, native=None):
    native = native if native is not None else QianchuanTasks(root, store)
    native_task = native.claim()
    if native_task:
        execute(native, native_task)
    dist, reports = Distribution(root, store), Reporting(root, store)
    task = dist.claim()
    if task:
        # Export persists a sanitized failure; never log arbitrary payloads.
        with suppress(Exception):
            dist.export(task)
    sync = reports.claim()
    if sync:
        try:
            with store.connect() as c:
                grant = c.execute(
                    "SELECT 1 FROM qianchuan_grants WHERE account_id=?", (sync["account_id"],)
                ).fetchone()
            if grant:
                # An invalid native grant fails closed; never silently switch credentials.
                sync_native(reports, sync, native.auth)
            else:
                OceanWatch(root).sync(reports, sync)
        except Exception:
            reports.fail_sync(sync)
    return bool(native_task or task or sync)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    root = Path(parser.parse_args().data).resolve()
    store = Store(root / "workflow.db")
    while True:
        if not tick(root, store):
            time.sleep(0.5)


if __name__ == "__main__":
    main()
