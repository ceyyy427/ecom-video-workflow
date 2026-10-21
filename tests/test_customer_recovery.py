import hashlib
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecom_video.api import create_app
from ecom_video.db import Store


def fixture_data(tmp_path):
    root = tmp_path / "data"
    store = Store(root / "workflow.db")
    job = store.create_job("客户恢复验收", "保留旧稿和审核。", 2)
    relative = f"jobs/{job['id']}/assets/voice.wav"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"original-fixture-voice")
    with store.transaction() as c:
        c.execute(
            "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "fixture-voice",
                job["id"],
                "voice.wav",
                relative,
                "audio",
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_size,
                0,
                "{}",
            ),
        )
    return root, store, job, relative


def wait(client, operation):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        result = client.get("/api/maintenance/operations/" + operation).json()
        if result["state"] not in ("running", "queued"):
            return result
        time.sleep(0.02)
    raise AssertionError("operation did not finish")


@pytest.fixture
def client(tmp_path):
    root, store, job, relative = fixture_data(tmp_path)
    with TestClient(create_app(root), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        yield c, root, store, job, relative


def test_page_backup_restore_preserves_media_and_old_data(client):
    c, root, store, job, relative = client
    assert c.get("/maintenance").status_code == 200
    before = store.get(job["id"])
    r = c.post("/api/maintenance/backups", json={"confirmed": True})
    assert r.status_code == 202, r.text
    done = wait(c, r.json()["id"])
    assert done["state"] == "complete", done
    bid = done["result"]["backup_id"]
    assert (
        c.post(f"/api/maintenance/backups/{bid}/verify", json={"confirmed": True}).status_code
        == 200
    )
    download = c.get(f"/api/maintenance/backups/{bid}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    r = c.post(f"/api/maintenance/backups/{bid}/restore", json={"confirmed": True})
    done = wait(c, r.json()["id"])
    assert done["state"] == "complete", done
    restored = Path(done["result"]["data_directory"])
    assert restored != root
    assert (restored / relative).read_bytes() == (root / relative).read_bytes()
    assert (Path(done["result"]["directory"]) / "启动恢复副本.command").exists()
    assert Store(restored / "workflow.db").get(job["id"]) == before
    assert store.get(job["id"]) == before


def test_maintenance_blocks_writes_and_worker_claims(client):
    from ecom_video.maintenance_lock import hold
    from ecom_video.worker import Worker

    c, root, store, job, _ = client
    with hold(root, exclusive=True):
        assert (
            c.post(
                "/api/jobs", json={"title": "blocked", "script": "不能插队", "seconds": 1}
            ).status_code
            == 423
        )
        assert c.get("/api/maintenance/status").status_code == 200
        assert Worker(root).run_once() is False
    assert (
        c.post("/api/jobs", json={"title": "ok", "script": "已解除", "seconds": 1}).status_code
        == 201
    )


def test_busy_jobs_and_active_writer_prevent_backup(client):
    from ecom_video.maintenance_lock import hold

    c, root, store, job, _ = client
    with hold(root):
        assert c.post("/api/maintenance/backups", json={"confirmed": True}).status_code == 409
    with store.transaction() as db:
        db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
    r = c.post("/api/maintenance/backups", json={"confirmed": True})
    assert r.status_code == 409
    assert not c.get("/api/maintenance/status").json()["backups"]


def test_zip_paths_and_symlinks_rejected(tmp_path):
    from ecom_video.customer_archives import unpack_backup

    for name in ("../escape", "/absolute", "jobs/../secret", "jobs\\secret", "workflow.db"):
        path = tmp_path / "bad.zip"
        with zipfile.ZipFile(path, "w") as z:
            item = zipfile.ZipInfo(name)
            item.external_attr = 0o120777 << 16
            z.writestr(item, b"target")
        target = tmp_path / "restored"
        with pytest.raises(ValueError):
            unpack_backup(path, target)
        assert not target.exists()


def test_no_origin_token_no_backup_and_no_arbitrary_paths(client):
    c, _, _, _, _ = client
    assert (
        c.post(
            "/api/maintenance/backups",
            json={"confirmed": True},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/maintenance/backups", json={"confirmed": True, "destination": "/tmp/override"}
        ).status_code
        == 422
    )
    assert c.post("/api/maintenance/backups", json={}).status_code == 422
    assert c.post(
        "/api/maintenance/backups/../../missing/restore", json={"confirmed": True}
    ).status_code in (404, 422)


def upload_package(c, tmp_path):
    from ecom_video.customer_setup import PROJECT, build_package

    package = tmp_path / "upgrade.zip"
    result = build_package(PROJECT, package)
    r = c.post(
        "/api/maintenance/packages",
        data={"confirmed": "true", "sha256": result["sha256"]},
        files={"file": ("upgrade.zip", package.read_bytes(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    return r.json()["package_id"]


def test_upgrade_backups_first_and_keeps_current_job(client, tmp_path):
    c, root, store, job, relative = client
    before = store.get(job["id"])
    pid = upload_package(c, tmp_path)
    r = c.post(
        "/api/maintenance/upgrades",
        json={"confirmed": True, "trusted_code": True, "package_id": pid},
    )
    assert r.status_code == 202, r.text
    done = wait(c, r.json()["id"])
    assert done["state"] == "complete", done
    result = done["result"]
    assert result["state"] == "prepared_not_activated"
    assert result["backup_id"] in {
        x["backup_id"] for x in c.get("/api/maintenance/status").json()["backups"]
    }
    assert (Path(result["data_directory"]) / relative).read_bytes() == (
        root / relative
    ).read_bytes()
    assert Store(Path(result["data_directory"]) / "workflow.db").get(job["id"]) == before
    assert store.get(job["id"]) == before
    assert (Path(result["directory"]) / "启动新版本.command").exists()


def test_invalid_upgrade_keeps_pre_upgrade_backup(client, tmp_path):
    c, root, store, job, _ = client
    data = b"not-a-release"
    r = c.post(
        "/api/maintenance/packages",
        data={"confirmed": "true", "sha256": hashlib.sha256(data).hexdigest()},
        files={"file": ("bad.zip", data, "application/zip")},
    )
    pid = r.json()["package_id"]
    r = c.post(
        "/api/maintenance/upgrades",
        json={"confirmed": True, "trusted_code": True, "package_id": pid},
    )
    done = wait(c, r.json()["id"])
    assert done["state"] == "failed"
    assert done["backup_id"] in {
        x["backup_id"] for x in c.get("/api/maintenance/status").json()["backups"]
    }
    assert store.get(job["id"])["status"] == "draft"


def test_backup_import_and_corruption_guard(client):
    c, root, store, job, _ = client
    done = wait(c, c.post("/api/maintenance/backups", json={"confirmed": True}).json()["id"])
    bid = done["result"]["backup_id"]
    archive = c.get("/api/maintenance/backups/" + bid + "/download").content
    r = c.post(
        "/api/maintenance/import",
        data={"confirmed": "true"},
        files={"file": ("backup.zip", archive, "application/zip")},
    )
    imported = wait(c, r.json()["id"])
    assert imported["state"] == "complete", imported
    assert imported["result"]["backup_id"] != bid
    from ecom_video.customer_recovery import Recovery

    folder = Recovery(root).backup_folder(bid)
    (folder / "backup.zip").write_bytes(b"corrupt")
    assert c.get("/api/maintenance/backups/" + bid + "/download").status_code == 422


def test_readable_interrupted_operation_does_not_stay_running(client):
    from ecom_video.customer_recovery import Recovery

    c, root, _, _, _ = client
    service = Recovery(root)
    oid = "r-" + "e" * 32
    service.write(
        service.path("operations", oid).with_suffix(".json"),
        {"id": oid, "state": "running", "kind": "backup", "message": "before exit"},
    )
    r = c.get("/api/maintenance/operations/" + oid)
    assert r.json()["state"] == "interrupted"


def test_import_cleans_upload_on_failure_and_busy_refusal(client):
    from ecom_video.maintenance_lock import hold

    c, root, _, _, _ = client
    incoming = root.parent / (root.name + "-maintenance") / "incoming"
    r = c.post(
        "/api/maintenance/import",
        data={"confirmed": "true"},
        files={"file": ("bad.zip", b"bad", "application/zip")},
    )
    assert wait(c, r.json()["id"])["state"] == "failed"
    assert not list(incoming.iterdir())
    with hold(root):
        r = c.post(
            "/api/maintenance/import",
            data={"confirmed": "true"},
            files={"file": ("bad.zip", b"bad", "application/zip")},
        )
        assert r.status_code == 409
    assert not list(incoming.iterdir())


def test_backup_unpack_checks_free_space_before_creating_target(tmp_path, monkeypatch):
    import json
    import shutil

    from ecom_video import customer_archives

    package = tmp_path / "backup.zip"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("backup.json", json.dumps({"files": []}))
        z.writestr("workflow.db", b"fixture")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100, 100, 0))
    with pytest.raises(ValueError):
        customer_archives.unpack_backup(package, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_upload_rejects_low_disk_before_spooling_or_incoming(client, monkeypatch):
    import shutil

    c, root, _, _, _ = client
    monkeypatch.setattr(shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100, 100, 0))
    r = c.post(
        "/api/maintenance/import",
        data={"confirmed": "true"},
        files={"file": ("backup.zip", b"payload", "application/zip")},
    )
    assert r.status_code == 507
    assert not list((root.parent / (root.name + "-maintenance") / "incoming").iterdir())


def test_completion_between_record_read_and_lock_check_is_not_interruption(client, monkeypatch):
    from ecom_video import customer_recovery

    c, root, _, _, _ = client
    service = customer_recovery.Recovery(root)
    oid = "r-" + "a" * 32
    path = service.path("operations", oid).with_suffix(".json")
    service.write(path, {"id": oid, "state": "running", "kind": "backup", "message": "in progress"})
    original = customer_recovery.acquire

    def completed_before_lock_check(*args, **kwargs):
        service.write(
            path, {"id": oid, "state": "complete", "kind": "backup", "message": "finished"}
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(customer_recovery, "acquire", completed_before_lock_check)
    assert c.get("/api/maintenance/operations/" + oid).json()["state"] == "complete"


@pytest.mark.parametrize(
    "bad_release", [{"version": "0.1.0"}, {"schema_max": 1}, {"maintenance_protocol": 0}]
)
def test_release_downgrade_or_incompatible_contract_never_extracts(tmp_path, bad_release):
    import json

    from ecom_video.customer_archives import unpack_release
    from ecom_video.customer_setup import PROJECT, build_package

    good = tmp_path / "good.zip"
    build_package(PROJECT, good)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        manifest = json.loads(src.read("PACKAGE.json"))
        manifest["release"].update(bad_release)
        for item in src.infolist():
            dst.writestr(
                item,
                json.dumps(manifest).encode()
                if item.filename == "PACKAGE.json"
                else src.read(item),
            )
    with pytest.raises(ValueError):
        unpack_release(
            bad,
            tmp_path / "application",
            hashlib.sha256(bad.read_bytes()).hexdigest(),
            14,
            "0.12.0",
        )
    assert not (tmp_path / "application").exists()


def test_all_worker_types_yield_to_maintenance(client):
    from ecom_video.agent_runtime import Runtime
    from ecom_video.analysis_worker import Worker as AnalysisWorker
    from ecom_video.maintenance_lock import hold
    from ecom_video.platform_worker import tick

    c, root, store, _, _ = client
    with hold(root, exclusive=True):
        assert AnalysisWorker(root).once() is False
        assert Runtime(root, store).tick() is False
        assert tick(root, store) is False
