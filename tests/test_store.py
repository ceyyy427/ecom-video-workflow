from concurrent.futures import ThreadPoolExecutor

import pytest

from ecom_video.db import Conflict, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "workflow.db")


def queued(store):
    j = store.create_job("测试", "展示真实商品", 2)
    store.add_asset(
        j["id"],
        {
            "id": "asset-" + j["id"],
            "name": "test.png",
            "path": "test.png",
            "kind": "image",
            "sha256": "hash",
            "size": 10,
            "metadata": {},
        },
    )
    store.submit(j["id"])
    return j["id"]


def test_atomic_claim_and_idempotent_submit(store):
    jid = queued(store)
    store.submit(jid)
    with ThreadPoolExecutor(max_workers=8) as ex:
        claims = list(ex.map(lambda n: store.claim(str(n)), range(8)))
    assert len([c for c in claims if c]) == 1
    assert store.get(jid)["attempts"] == 1
    with pytest.raises(Conflict):
        store.update_draft(jid, "改", "修改脚本", 3)


def test_expired_worker_cannot_publish_or_heartbeat(store):
    jid = queued(store)
    first = store.claim("old", now=100)
    second = store.claim("new", now=200)
    assert second["id"] == jid
    assert first["lease_token"] != second["lease_token"]
    assert not store.heartbeat(jid, first["lease_token"], now=201)
    with pytest.raises(Conflict):
        store.advance(jid, first["lease_token"], "rendering", now=201)


def test_cancel_invalidates_lease(store):
    jid = queued(store)
    claim = store.claim("worker")
    store.cancel(jid)
    assert not store.heartbeat(jid, claim["lease_token"])
    assert store.get(jid)["status"] == "cancelled"
    with pytest.raises(Conflict):
        store.finish(jid, claim["lease_token"], "blocked", [], {})


def test_recovery_is_bounded(store):
    jid = queued(store)
    for now in (100, 200, 300):
        assert store.claim("worker", now=now)
    assert store.claim("worker", now=400) is None
    assert store.get(jid)["status"] == "failed"
    with pytest.raises(Conflict):
        store.retry(jid)


def test_requires_media_and_review_cannot_skip_pipeline(store):
    j = store.create_job("空", "脚本", 2)
    with pytest.raises(Conflict):
        store.submit(j["id"])
    with pytest.raises(Conflict):
        store.review(j["id"], "ready", "审核人", "检查过", True)
