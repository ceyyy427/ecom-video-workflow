import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_qianchuan_auth import MemorySecrets, OAuthFixture

from ecom_video.db import Conflict, Store
from ecom_video.distribution import Distribution
from ecom_video.media import digest
from ecom_video.platforms.qianchuan_http import ProviderError
from ecom_video.qianchuan_auth import QianchuanAuth
from ecom_video.qianchuan_tasks import QianchuanTasks
from ecom_video.qianchuan_worker import execute


class NativeFixture(OAuthFixture):
    def __init__(self):
        super().__init__()
        self.uploads = 0
        self.creates = 0
        self.pending = False
        self.uncertain = False

    def upload(self, token, aid, path, is_aigc):
        self.uploads += 1
        return {
            "video_id": "v012ABC",
            "material_id": "987",
            "video_cover_id": "tos-cover",
            "md5": hashlib.md5(path.read_bytes()).hexdigest(),
            "request_id": "upload123",
        }

    def material(self, *args):
        if self.pending:
            return None
        return {
            "video_id": args[2],
            "material_id": args[4],
            "md5": args[3],
            "image_mode": "VIDEO_VERTICAL",
            "request_id": "verify123",
        }

    def create(self, token, payload):
        self.creates += 1
        assert payload["creative_setting"]["smart_select_material"] is False
        assert len(payload["programmatic_creative_media_list"]["video_material"]) == 1
        if self.uncertain:
            raise ProviderError(uncertain=True)
        return {"ad_id": "456", "request_id": "create123", "source": "qianchuan_api"}


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_QIANCHUAN_WRITES", "1")
    store = Store(tmp_path / "workflow.db")
    dist = Distribution(tmp_path, store)
    aid = dist.add_account("账户", "qianchuan", "123")["id"]
    jid = store.create_job("杯子", "杯子展示", 1)["id"]
    file = tmp_path / "video.mp4"
    file.write_bytes(b"video-fixture")
    with store.transaction() as c:
        c.execute("UPDATE jobs SET status='ready' WHERE id=?", (jid,))
        c.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            ("v", jid, "video", "video.mp4", digest(file), file.stat().st_size, 1),
        )
    provider = NativeFixture()
    secrets = MemorySecrets()
    auth = QianchuanAuth(tmp_path, store, secrets=secrets, provider=provider)
    auth.configure("99", "appsecret", "http://127.0.0.1:8765/api/qianchuan/oauth/callback", "1000")
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(auth.start(aid)["url"]).query)["state"][0]
    auth.callback(state, "code")
    service = QianchuanTasks(tmp_path, store, auth=auth)
    params = {
        "name": "杯子计划",
        "product_id": "333",
        "aweme_id": "444",
        "title": "展示杯子外观",
        "budget": "100",
        "roi2_goal": "1.5",
        "is_aigc": False,
    }
    task = service.create(jid, aid, params)
    return service, task, provider


def advance_to_approval(native):
    service, task, provider = native
    service.upload_confirm(task["id"], "核验人", "有权上传该视频", True)
    execute(service, service.claim())
    assert service.get(task["id"])["status"] == "material_pending"
    service.recheck(task["id"])
    execute(service, service.claim())
    return service.get(task["id"])


def test_upload_material_then_explicit_ad_approval(native):
    service, task, provider = native
    assert service.claim() is None
    task = advance_to_approval(native)
    assert task["status"] == "awaiting_approval" and provider.creates == 0
    assert service.claim() is None
    with pytest.raises(Conflict):
        service.approve(task["id"], "wrong", "人", "同意", True)
    service.approve(task["id"], task["snapshot_hash"], "负责人", "核对参数且理解可能产生费用", True)
    with pytest.raises(Conflict):
        service.approve(task["id"], task["snapshot_hash"], "负责人", "重复", True)
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(lambda _: service.claim(), range(2)))
    assert len([x for x in claimed if x]) == 1
    execute(service, next(x for x in claimed if x))
    assert service.get(task["id"])["status"] == "submitted"
    assert provider.uploads == provider.creates == 1
    assert service.claim() is None


def test_unknown_create_is_never_retried(native):
    service, task, provider = native
    task = advance_to_approval(native)
    provider.uncertain = True
    service.approve(task["id"], task["snapshot_hash"], "人", "同意产生费用", True)
    execute(service, service.claim())
    assert service.get(task["id"])["status"] == "unknown"
    assert service.claim() is None and provider.creates == 1
    with pytest.raises(Conflict):
        service.create(task["job_id"], task["account_id"], task["parameters"])
    service.resolve(task["id"], "found", "456", "核验人", "平台查询已找到该计划", True)
    assert service.get(task["id"])["status"] == "submitted"


def test_expired_approval_and_tampering_never_dispatch(native):
    service, task, provider = native
    task = advance_to_approval(native)
    service.approve(task["id"], task["snapshot_hash"], "人", "同意", True)
    with service.store.transaction() as c:
        c.execute("UPDATE qianchuan_tasks SET prepared_until=0")
    execute(service, service.claim())
    assert provider.creates == 0 and service.get(task["id"])["status"] == "failed"


def test_crash_after_dispatch_becomes_unknown_and_stale_worker_fenced(native):
    service, task, provider = native
    service.upload_confirm(task["id"], "人", "同意上传", True)
    claimed = service.claim()
    service.mark_dispatch(claimed)
    with service.store.transaction() as c:
        c.execute("UPDATE qianchuan_tasks SET lease_until=0")
    assert service.claim() is None
    assert service.get(task["id"])["status"] == "unknown"
    with pytest.raises(Conflict):
        service.mark_dispatch(claimed)
    assert provider.uploads == 0


def test_writes_disabled_and_config_change_invalidate(native, monkeypatch):
    service, task, provider = native
    monkeypatch.delenv("ECOM_QIANCHUAN_WRITES")
    with pytest.raises(Conflict):
        service.upload_confirm(task["id"], "人", "同意上传", True)
    assert provider.uploads == 0
    monkeypatch.setenv("ECOM_QIANCHUAN_WRITES", "1")
    task = advance_to_approval(native)
    service.auth.configure(
        "99", "newsecret", "http://127.0.0.1:8765/api/qianchuan/oauth/callback", "1000"
    )
    with pytest.raises(Conflict):
        service.approve(task["id"], task["snapshot_hash"], "人", "同意", True)


def test_changed_video_and_other_unknown_task_stop_queued_upload(native):
    service, task, provider = native
    second = service.create(task["job_id"], task["account_id"], task["parameters"])
    service.upload_confirm(second["id"], "人", "已确认", True)
    with service.store.transaction() as c:
        c.execute(
            "UPDATE qianchuan_tasks SET status='unknown',stage='upload' WHERE id=?", (task["id"],)
        )
    execute(service, service.claim())
    assert provider.uploads == 0


def test_changed_video_after_confirmation_never_uploads(native):
    service, task, provider = native
    service.upload_confirm(task["id"], "人", "已确认", True)
    (service.root / "video.mp4").write_bytes(b"changed")
    execute(service, service.claim())
    assert provider.uploads == 0 and service.get(task["id"])["status"] == "failed"


def test_platform_worker_executes_native_queue(native):
    from ecom_video.platform_worker import tick

    service, task, provider = native
    service.upload_confirm(task["id"], "人", "已确认", True)
    assert tick(service.root, service.store, native=service)
    assert provider.uploads == 1 and service.get(task["id"])["status"] == "material_pending"


def test_expiry_during_material_check_blocks_final_dispatch(native):
    service, task, provider = native
    task = advance_to_approval(native)
    service.approve(task["id"], task["snapshot_hash"], "人", "确认", True)
    original = provider.material

    def delayed(*args):
        with service.store.transaction() as c:
            c.execute("UPDATE qianchuan_tasks SET prepared_until=0")
        return original(*args)

    provider.material = delayed
    execute(service, service.claim())
    assert provider.creates == 0


def test_exact_preview_preserves_large_platform_ids(native):
    service, task, provider = native
    with service.store.transaction() as c:
        import json

        params = task["parameters"] | {
            "product_id": "9123456789012345678",
            "aweme_id": "8123456789012345678",
        }
        c.execute(
            "UPDATE qianchuan_tasks SET parameters=? WHERE id=?", (json.dumps(params), task["id"])
        )
    task = advance_to_approval(native)
    assert "9123456789012345678" in task["payload_preview"]
    assert "8123456789012345678" in task["payload_preview"]


def test_paused_sender_cannot_be_resolved_while_still_owns_dispatch(native, monkeypatch):
    import threading

    service, task, provider = native
    task = advance_to_approval(native)
    service.approve(task["id"], task["snapshot_hash"], "人", "确认", True)
    original = service.mark_dispatch
    marked, resume = threading.Event(), threading.Event()

    def pause_after_mark(task):
        original(task)
        marked.set()
        assert resume.wait(10)

    monkeypatch.setattr(service, "mark_dispatch", pause_after_mark)
    claimed = service.claim()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(execute, service, claimed)
        try:
            assert marked.wait(5)
            with service.store.transaction() as c:
                c.execute("UPDATE qianchuan_tasks SET lease_until=0 WHERE id=?", (task["id"],))
            assert service.claim() is None
            assert service.get(task["id"])["status"] == "creating"
            with pytest.raises(Conflict):
                service.resolve(task["id"], "not_created", "", "核验人", "平台此时尚未看到", True)
            assert provider.creates == 0
        finally:
            resume.set()
            future.result(timeout=5)
    # Once the sender terminates, recovery can safely expose unknown for manual reconciliation.
    assert provider.creates == 1
    service.claim()
    assert service.get(task["id"])["status"] == "unknown"
    service.resolve(task["id"], "found", "456", "核验人", "已找到计划", True)
    assert service.get(task["id"])["status"] == "submitted"
