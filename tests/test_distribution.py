import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from ecom_video.db import Conflict, Store
from ecom_video.distribution import Distribution
from ecom_video.media import digest


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "workflow.db")
    job = store.create_job("杯子", "展示杯子", 1)
    file = tmp_path / "video.mp4"
    file.write_bytes(b"test fixture video")
    with store.transaction() as c:
        c.execute("UPDATE jobs SET status='ready' WHERE id=?", (job["id"],))
        c.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            ("v", job["id"], "video", "video.mp4", digest(file), file.stat().st_size, 1),
        )
    dist = Distribution(tmp_path, store)
    account = dist.add_account("测试账户", "qianchuan", "1234567890123456789")
    return dist, job["id"], account["id"]


def make(setup):
    dist, jid, aid = setup
    return dist.create(jid, aid, "杯子推广", "100.00", "1.5")


def test_approval_binds_snapshot_and_exports_once(setup):
    dist, _, _ = setup
    task = make(setup)
    assert task["status"] == "awaiting_approval"
    assert dist.claim() is None
    with pytest.raises(Conflict):
        dist.approve(task["id"], "wrong", "张三", "确认", True)
    dist.approve(task["id"], task["snapshot_hash"], "张三", "预算及成片已确认", True)
    with pytest.raises(Conflict):
        dist.approve(task["id"], task["snapshot_hash"], "张三", "确认", True)
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(lambda _: dist.claim(), range(2)))
    assert sum(x is not None for x in claimed) == 1
    dist.export(next(x for x in claimed if x))
    result = dist.get(task["id"])
    assert result["status"] == "awaiting_manual"
    with zipfile.ZipFile(dist.package(task["id"])) as z:
        payload = json.loads(z.read("投放确认.json"))
        assert payload["snapshot_hash"] == task["snapshot_hash"]
        assert payload["approval"]["reviewer"] == "张三"
        assert z.read("video.mp4") == b"test fixture video"
    result = dist.receipt(task["id"], "submitted", "987", "李四", "平台已创建，等待审核", True)
    assert result["status"] == "submitted"
    assert result["receipt"]["source"] == "human_recorded"
    assert dist.claim() is None


def test_tampering_and_gates(setup):
    dist, jid, aid = setup
    task = make(setup)
    (dist.root / "video.mp4").write_bytes(b"changed")
    with pytest.raises(Conflict):
        dist.approve(task["id"], task["snapshot_hash"], "张三", "确认", True)
    with dist.store.transaction() as c:
        c.execute("UPDATE jobs SET status='rejected' WHERE id=?", (jid,))
    with pytest.raises(Conflict):
        dist.create(jid, aid, "test", "100", "1")


def test_receipt_requires_export_and_crash_is_not_retried(setup):
    dist, _, _ = setup
    task = make(setup)
    with pytest.raises(Conflict):
        dist.receipt(task["id"], "active", "987", "张三", "已投放", True)
    dist.approve(task["id"], task["snapshot_hash"], "张三", "确认", True)
    claimed = dist.claim()
    with dist.store.transaction() as c:
        c.execute("UPDATE distribution_tasks SET lease_until=0 WHERE id=?", (task["id"],))
    assert dist.claim() is None
    assert dist.get(task["id"])["status"] == "failed"
    with pytest.raises(Conflict):
        dist.export(claimed)
