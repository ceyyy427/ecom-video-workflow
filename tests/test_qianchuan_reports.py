import pytest

from ecom_video.platform_worker import sync_native
from ecom_video.reporting import Reporting

pytest_plugins = ["test_qianchuan_tasks"]


def test_native_report_atomic_and_provenance(native):
    service, task, provider = native
    reports = Reporting(service.root, service.store)

    def day(token, aid, date):
        if date == "2026-10-13":
            raise ValueError("fixture failure")
        return {
            "date": date,
            "advertiser_id": aid,
            "request_ids": ["fixture"],
            "rows": [
                {
                    "date": date,
                    "material_id": "987",
                    "spend": "10",
                    "impressions": "100",
                    "clicks": "5",
                    "orders": "1",
                    "revenue": "20",
                }
            ],
        }

    provider.report_day = day
    reports.enqueue(task["account_id"], "2026-10-12", "2026-10-13", "tester")
    sync = reports.claim()
    with pytest.raises(ValueError):
        sync_native(reports, sync, service.auth)
    assert reports.batches(task["account_id"]) == []
    reports.fail_sync(sync)
    reports.enqueue(task["account_id"], "2026-10-12", "2026-10-12", "tester")
    sync_native(reports, reports.claim(), service.auth)
    batch = reports.batches(task["account_id"])[0]
    assert batch["source"] == "qianchuan_api"
    dash = reports.dashboard(task["account_id"], "2026-10-12", "2026-10-12")
    assert dash["totals"]["spend"] == "10"
