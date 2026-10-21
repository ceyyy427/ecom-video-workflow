import pytest

from ecom_video.db import Conflict, Store
from ecom_video.distribution import Distribution
from ecom_video.reporting import Reporting, number

HEADER = "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"


@pytest.fixture
def reports(tmp_path):
    store = Store(tmp_path / "workflow.db")
    dist = Distribution(tmp_path, store)
    account = dist.add_account("广告主", "qianchuan", "1234567890123456789")
    return Reporting(tmp_path, store), account["id"]


def ingest(reports, lines, start="2026-10-01", end="2026-10-01"):
    repo, aid = reports
    return repo.import_csv(aid, start, end, (HEADER + lines).encode(), "测试员", True)


def test_weighted_metrics_and_reimport_snapshot(reports):
    repo, aid = reports
    lines = "2026-10-01,123,10,100,10,2,30,50,20\n2026-10-01,456,90,900,30,3,120,100,10\n"
    first = ingest(reports, lines)
    assert ingest(reports, lines)["id"] == first["id"]
    dash = repo.dashboard(aid, "2026-10-01", "2026-10-01")
    assert dash["totals"]["spend"] == "100"
    assert dash["ratios"]["ctr"] == "0.04"
    assert dash["ratios"]["payment_roi"] == "1.5"
    assert dash["ratios"]["completion_rate"] == "0.2"
    ingest(reports, "2026-10-01,123,5,100,5,1,20,50,10\n")
    dash = repo.dashboard(aid, "2026-10-01", "2026-10-01")
    assert len(dash["materials"]) == 1
    assert dash["totals"]["spend"] == "5"
    assert len(repo.batches(aid)) == 2


def test_missing_vs_zero_and_date_coverage(reports):
    repo, aid = reports
    ingest(reports, "2026-10-01,123,0,0,0,,0,,\n")
    dash = repo.dashboard(aid, "2026-10-01", "2026-10-01")
    assert dash["totals"]["spend"] == "0"
    assert dash["totals"]["orders"] is None
    assert dash["ratios"]["payment_roi"] is None
    dash = repo.dashboard(aid, "2026-10-01", "2026-10-02")
    assert dash["status"] == "partial"
    assert dash["missing_dates"] == ["2026-10-02"]
    assert dash["totals"]["spend"] is None
    assert dash["observed_totals"]["spend"] == "0"


def test_invalid_batch_atomic_and_source_saved(reports):
    repo, aid = reports
    good = ingest(reports, "2026-10-01,123,10,100,5,1,20,50,10\n")
    assert (repo.root / good["path"]).is_file()
    for row in [
        "2026-10-01,123,NaN,100,5,1,20,50,10\n",
        "2026-10-02,123,10,100,5,1,20,50,10\n",
        "2026-10-01,1e8,10,100,5,1,20,50,10\n",
        "2026-10-01,123,10,100,5,1,20,50,51\n",
    ]:
        with pytest.raises(ValueError):
            ingest(reports, row)
    with pytest.raises(ValueError):
        ingest(reports, "2026-10-01,123,10,100,5,1,20,50,10\n" * 2)
    assert len(repo.batches(aid)) == 1
    with pytest.raises(ValueError):
        number("1e100000", money=True)
    with pytest.raises(ValueError):
        number("1.5")
    with pytest.raises(ValueError):
        number("-1")


def test_range_overwrite_and_account_isolation(reports):
    repo, aid = reports
    ingest(
        reports,
        "2026-10-01,123,10,100,5,1,20,50,10\n2026-10-02,123,20,200,10,2,40,100,20\n",
        end="2026-10-02",
    )
    ingest(reports, "2026-10-01,123,5,100,5,1,20,50,10\n")
    dash = repo.dashboard(aid, "2026-10-01", "2026-10-02")
    assert dash["totals"]["spend"] == "25"
    other = Distribution(repo.root, repo.store).add_account("另一个", "qianchuan", "456")
    assert repo.dashboard(other["id"], "2026-10-01", "2026-10-02")["status"] == "empty"


def test_sync_lease_and_truncation_never_ingested(reports):
    repo, aid = reports
    sync = repo.enqueue(aid, "2026-10-01", "2026-10-01", "张三")
    with pytest.raises(Conflict):
        repo.enqueue(aid, "2026-10-01", "2026-10-01", "张三")
    claimed = repo.claim()
    assert claimed["id"] == sync["id"]
    with repo.store.transaction() as c:
        c.execute("UPDATE report_syncs SET lease_until=0")
    assert repo.claim() is None
    assert repo.syncs(aid)[0]["status"] == "failed"


def test_large_valid_metrics_do_not_crash_ratios(reports):
    repo, aid = reports
    lines = "".join(
        f"2026-10-01,{i + 1},{'0.000001' if i == 0 else '0'},1,1,1,999999999999999,1,1\n"
        for i in range(100)
    )
    ingest(reports, lines)
    dashboard = repo.dashboard(aid, "2026-10-01", "2026-10-01")
    assert dashboard["ratios"]["payment_roi"] == "99999999999999900000000"


def test_covered_empty_day_makes_interval_metrics_unknown(reports):
    repo, aid = reports
    ingest(reports, "2026-10-01,123,10,100,5,1,20,50,10\n", end="2026-10-02")
    dashboard = repo.dashboard(aid, "2026-10-01", "2026-10-02")
    assert dashboard["missing_dates"] == []
    assert dashboard["daily"][1]["covered"] is True
    assert dashboard["daily"][1]["totals"]["spend"] is None
    assert dashboard["status"] == "partial"
    assert dashboard["totals"]["spend"] is None
    assert dashboard["ratios"]["payment_roi"] is None
    assert dashboard["observed_totals"]["spend"] == "10"
