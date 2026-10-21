import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ecom_video.db import Conflict, Store
from ecom_video.distribution import Distribution
from ecom_video.reporting import Reporting

HEADER = "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    store = Store(tmp_path / "workflow.db")
    account = Distribution(tmp_path, store).add_account("fixture 账户", "qianchuan", "123")
    from ecom_video.review_snapshots import Reviews

    return Reviews(tmp_path, store), Reporting(tmp_path, store), account["id"]


def command(aid, request_id="freeze-001", start="2026-10-01", end="2026-10-03"):
    return {
        "request_id": request_id,
        "account_id": aid,
        "start_date": start,
        "end_date": end,
        "actor": "AUTOMATED FIXTURE 复盘核对",
    }


def ingest(reports, aid, text, start="2026-10-01", end="2026-10-01"):
    return reports.import_csv(
        aid, start, end, (HEADER + text).encode(), "AUTOMATED FIXTURE 数据导入", True
    )


def test_freeze_preserves_missing_zero_empty_days_and_metric_basis(env):
    reviews, reports, aid = env
    first = ingest(reports, aid, "2026-10-01,123,0,0,0,,0,,\n", end="2026-10-02")
    frozen = reviews.create(command(aid))
    data = frozen["snapshot"]
    assert data["missing_dates"] == ["2026-10-03"]
    assert data["totals"]["spend"] is None and data["observed_totals"]["spend"] == "0"
    assert data["ratios"]["payment_roi"] is None
    rows = data["material_daily"]
    assert [r["availability"] for r in rows] == ["reported", "covered_empty", "missing_report"]
    assert rows[0]["metrics"]["spend"] == "0" and rows[0]["metrics"]["orders"] is None
    assert rows[1]["metrics"]["spend"] is None
    assert rows[0]["batch_id"] == first["id"]
    assert data["metric_contract"]["attribution_window"] is None
    assert data["metric_contract"]["causal_inference"] is False
    assert data["metric_contract"]["definitions"]["payment_roi"]["denominator"] == "spend"
    assert data["metric_contract"]["currency"] == "CNY"


def test_freeze_uses_fixed_decimal_context_and_weighted_raw_metrics(env):
    from decimal import ROUND_UP, localcontext

    reviews, reports, aid = env
    ingest(
        reports,
        aid,
        "2026-10-01,123,3,10,1,1,1,10,1\n2026-10-01,456,6,100,1,1,2,100,1\n",
    )
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.rounding = ROUND_UP
        data = reviews.create(command(aid, end="2026-10-01"))["snapshot"]
    assert data["ratios"]["payment_roi"] == "0.333333"
    assert data["ratios"]["ctr"] == "0.018182"
    assert data["totals"]["spend"] == "9"
    assert data["metric_contract"]["rounding"]["mode"] == "ROUND_HALF_EVEN"


def test_source_byte_and_row_limits_fail_atomically(env, monkeypatch):
    import ecom_video.review_snapshots as module

    reviews, reports, aid = env
    ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 1)
    with pytest.raises(Conflict, match="上限"):
        reviews.create(command(aid))
    monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 128 * 1024**2)
    monkeypatch.setattr(module, "MAX_ROWS", 0)
    with pytest.raises(ValueError, match="20000"):
        reviews.create(command(aid))
    with reviews.store.connect() as c:
        assert c.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 0


def test_reimport_creates_new_snapshot_and_old_bytes_never_change(env):
    reviews, reports, aid = env
    first = ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    old = reviews.create(command(aid, end="2026-10-01"))
    old_bytes = reviews.export(old["review_id"])
    latest = ingest(reports, aid, "2026-10-01,123,15,100,5,1,20,50,10\n")
    assert reviews.create(command(aid, end="2026-10-01")) == old
    fresh = reviews.create(command(aid, "freeze-002", end="2026-10-01"))
    assert fresh["snapshot"]["totals"]["spend"] == "15"
    assert fresh["snapshot_hash"] != old["snapshot_hash"]
    assert old["snapshot"]["batches"][0]["id"] == first["id"]
    assert fresh["snapshot"]["batches"][0]["id"] == latest["id"]
    assert reviews.export(old["review_id"]) == old_bytes
    assert reviews.get(old["review_id"]) == old


def test_day_selects_latest_complete_batch_not_latest_row_per_material(env):
    reviews, reports, aid = env
    ingest(
        reports,
        aid,
        "2026-10-01,123,10,100,5,1,20,50,10\n2026-10-02,123,20,100,5,1,20,50,10\n",
        end="2026-10-02",
    )
    latest = ingest(reports, aid, "2026-10-01,456,5,100,5,1,20,50,10\n")
    data = reviews.create(command(aid, end="2026-10-02"))["snapshot"]
    assert data["totals"]["spend"] == "25"
    rows = {(r["date"], r["material_id"]): r for r in data["material_daily"]}
    assert rows[("2026-10-01", "123")]["availability"] == "not_reported"
    assert rows[("2026-10-01", "123")]["metrics"]["spend"] is None
    assert rows[("2026-10-01", "456")]["batch_id"] == latest["id"]
    assert data["materials"][0]["interval_totals"]["spend"] is None


def test_cross_account_idempotence_and_concurrent_capture(env):
    reviews, reports, aid = env
    other = Distribution(reviews.root, reviews.store).add_account("other", "qianchuan", "456")
    ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    ingest(reports, other["id"], "2026-10-01,123,999,100,5,1,20,50,10\n")
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: reviews.create(command(aid, end="2026-10-01")), range(4)))
    assert len({r["review_id"] for r in results}) == 1
    assert results[0]["snapshot"]["totals"]["spend"] == "10"
    with pytest.raises(Conflict):
        reviews.create(command(other["id"], end="2026-10-01"))
    with reviews.store.connect() as c:
        assert c.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 1


def test_missing_or_tampered_report_evidence_rejected_atomically(env):
    reviews, reports, aid = env
    batch = ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    path = reviews.root / batch["path"]
    path.write_bytes(b"changed")
    with pytest.raises(Conflict):
        reviews.create(command(aid, end="2026-10-01"))
    with reviews.store.connect() as c:
        assert c.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 0


def test_frozen_read_survives_source_loss_but_verify_reports_it(env):
    reviews, reports, aid = env
    batch = ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    old = reviews.create(command(aid, end="2026-10-01"))
    (reviews.root / batch["path"]).unlink()
    assert reviews.get(old["review_id"]) == old
    verification = reviews.verify(old["review_id"])
    assert verification["snapshot_hash_valid"] and not verification["sources"][0]["available"]
    with pytest.raises(Conflict):
        reviews.source(old["review_id"], batch["id"])


def test_immutable_database_enforced_and_payload_hash_checked(env):
    reviews, _, aid = env
    frozen = reviews.create(command(aid))
    with reviews.store.connect() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE review_snapshots SET actor='changed'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM review_snapshots")
    digest = hashlib.sha256(
        json.dumps(
            frozen["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert digest == frozen["snapshot_hash"]


def test_same_read_transaction_blocks_interleaved_import(env, monkeypatch):
    import threading
    import time

    reviews, reports, aid = env
    ingest(reports, aid, "2026-10-01,123,10,100,5,1,20,50,10\n")
    reached = threading.Event()
    release = threading.Event()
    started = threading.Event()
    original = Reporting.dashboard

    def paused(self, *args, **kwargs):
        assert kwargs.get("connection") is not None
        reached.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Reporting, "dashboard", paused)

    def writer():
        assert reached.wait(5)
        started.set()
        return ingest(reports, aid, "2026-10-01,123,99,100,5,1,20,50,10\n")

    with ThreadPoolExecutor(2) as pool:
        capture = pool.submit(reviews.create, command(aid, end="2026-10-01"))
        writing = pool.submit(writer)
        assert started.wait(5)
        time.sleep(0.05)
        assert not writing.done()
        release.set()
        frozen = capture.result(5)
        writing.result(5)
    assert frozen["snapshot"]["totals"]["spend"] == "10"
    assert reviews.get(frozen["review_id"]) == frozen


def test_v10_migration_preserves_all_existing_records(tmp_path):
    db = tmp_path / "workflow.db"
    with sqlite3.connect(db) as c:
        for file in sorted(Path("ecom_video/migrations").glob("*.sql"))[:10]:
            c.executescript(file.read_text())
        c.execute("PRAGMA user_version=10")
        c.execute(
            "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at) VALUES('legacy','old','old',1,'draft',1,1)"
        )
    s = Store(db)
    assert s.get("legacy")["script"] == "old"
    with s.connect() as c:
        from ecom_video.db import SCHEMA_VERSION

        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert not c.execute("PRAGMA foreign_key_check").fetchall()


def test_metric_context_conflicts_disable_aggregation_and_keep_raw_values(env):
    reviews, reports, aid = env
    reports.ingest(
        aid,
        "2026-10-01",
        "2026-10-01",
        [{"date": "2026-10-01", "material_id": "123", "spend": "10", "revenue": "20"}],
        b"fixture-source",
        "qianchuan_api",
        "fixture",
        {"currency": "USD", "metric_basis": "roi2", "api_key": "never-export-fixture-secret"},
    )
    frozen = reviews.create(command(aid, end="2026-10-01"))
    assert frozen["snapshot"]["aggregation_allowed"] is False
    assert frozen["snapshot"]["totals"]["spend"] is None
    assert frozen["snapshot"]["material_daily"][0]["metrics"]["spend"] == "10"
    assert all(v is None for v in frozen["snapshot"]["material_daily"][0]["ratios"].values())
    assert (
        frozen["snapshot"]["material_daily"][0]["metric_context_status"] == "incompatible_sources"
    )
    assert frozen["snapshot"]["daily"][0]["totals"]["spend"] is None
    assert (
        frozen["snapshot"]["metric_contract"]["derived_metrics_status"]
        == "disabled_incompatible_sources"
    )
    assert "never-export-fixture-secret" not in reviews.export(frozen["review_id"]).decode()


def test_capture_limit_failure_rolls_back_features_and_snapshot(env, monkeypatch):
    from test_creative_features import ready

    from ecom_video import review_snapshots as module

    reviews, reports, aid = env
    jid, _, _ = ready(reviews.root, reviews.store)
    reports.bind(aid, "123", jid, "fixture")
    monkeypatch.setattr(module, "MAX_PAYLOAD", 10)
    with pytest.raises(ValueError):
        reviews.create(command(aid, end="2026-10-01"))
    with reviews.store.connect() as c:
        assert c.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM creative_features").fetchone()[0] == 0
