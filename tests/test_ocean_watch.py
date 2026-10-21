from copy import deepcopy

import pytest

from ecom_video.platforms.ocean_watch import ENDPOINT, FIELDS, OceanWatch

ACCOUNT = {"platform": "qianchuan", "advertiser_id": "1234567890123456789", "auth_account_id": ""}
DAY = "2026-10-01"


def response():
    return {
        "mode": "qianchuan_material_report",
        "endpoint": ENDPOINT,
        "advertiser_id": ACCOUNT["advertiser_id"],
        "date_range": {"start_date": DAY, "end_date": DAY},
        "fields": list(FIELDS),
        "truncated": False,
        "row_count": 1,
        "displayed_count": 1,
        "request_ids": ["request-123"],
        "rows": [
            {
                "material_id": "9876543210123456789",
                "stat_cost": "100.50",
                "show_cnt": 1000,
                "click_cnt": 40,
                "pay_order_count": 3,
                "pay_order_amount": 300,
                "total_play": 500,
                "access_token": "must-not-persist",
            }
        ],
    }


def test_read_contract_and_whitelist(tmp_path, monkeypatch):
    adapter = OceanWatch(tmp_path)

    def run(args):
        assert args[:2] == ["qc-reports", "materials"]
        assert "--submit" not in args and "--top" in args
        return response()

    monkeypatch.setattr(adapter, "_run", run)
    result = adapter.fetch_day(ACCOUNT, DAY)
    assert result["rows"][0]["spend"] == "100.5"
    assert result["rows"][0]["completed_views"] is None
    assert "must-not-persist" not in str(result)
    assert result["rows"][0]["material_id"] == "9876543210123456789"
    assert adapter.capabilities()["platform_write"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"truncated": True},
        {"advertiser_id": "999"},
        {"displayed_count": 0},
        {"fields": []},
        {"date_range": {"start_date": DAY, "end_date": "2026-10-02"}},
    ],
)
def test_reject_partial_or_wrong_scope(tmp_path, monkeypatch, change):
    adapter = OceanWatch(tmp_path)
    payload = deepcopy(response())
    payload.update(change)
    monkeypatch.setattr(adapter, "_run", lambda args: payload)
    with pytest.raises(ValueError):
        adapter.fetch_day(ACCOUNT, DAY)
