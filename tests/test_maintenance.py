import hashlib
import json
import sqlite3
import subprocess
import sys
import time

import pytest

from ecom_video.db import SCHEMA_VERSION, Store


def dataset(tmp_path):
    root = tmp_path / "data"
    store = Store(root / "workflow.db")
    job = store.create_job("维护测试", "这是已保存的文稿。", 3)
    relative = f"jobs/{job['id']}/assets/a.png"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"registered-original")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with store.transaction() as c:
        c.execute(
            "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
            ("asset1", job["id"], "商品.png", relative, "image", sha, path.stat().st_size, 0, "{}"),
        )
    return root, store, job, relative


def test_check_is_read_only_and_no_secrets(tmp_path, monkeypatch):
    from ecom_video.maintenance import check

    root = tmp_path / "not-created"
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "private-value-never-print")
    result = check(root)
    assert not root.exists()
    assert result["database"]["status"] == "not_created"
    assert "private-value-never-print" not in json.dumps(result)
    assert result["voice"]["live_verified"] is False
    assert "checks" in result and "ready" in result


def test_roundtrip_preserves_database_files_and_excludes_secrets(tmp_path):
    from ecom_video.maintenance import backup, restore, verify

    root, _, _, relative = dataset(tmp_path)
    (root / "secret.env").write_text("SECRET=do-not-copy")
    (root / "cache").mkdir()
    (root / "cache/private.log").write_text("not an asset")
    bundle = tmp_path / "snapshot"
    result = backup(root, bundle)
    assert result["files"] == 1
    assert verify(bundle)["valid"]
    target = tmp_path / "restored"
    restore(bundle, target)
    assert (target / relative).read_bytes() == (root / relative).read_bytes()
    assert not (target / "secret.env").exists()
    assert not (target / "cache").exists()
    for name in (root / "workflow.db", target / "workflow.db"):
        with sqlite3.connect(name) as c:
            assert c.execute("SELECT status,script FROM jobs").fetchall() == [
                ("draft", "这是已保存的文稿。")
            ]
            assert c.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
    with pytest.raises(ValueError, match="存在"):
        restore(bundle, target)


@pytest.mark.parametrize("change", ["tamper", "missing", "unlisted"])
def test_corrupt_backup_never_restores(tmp_path, change):
    from ecom_video.maintenance import backup, restore, verify

    root, _, _, relative = dataset(tmp_path)
    bundle = tmp_path / "snapshot"
    backup(root, bundle)
    if change == "tamper":
        (bundle / relative).write_bytes(b"bad")
    elif change == "missing":
        (bundle / relative).unlink()
    else:
        manifest = json.loads((bundle / "backup.json").read_text())
        manifest["files"] = []
        (bundle / "backup.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(bundle)
    with pytest.raises(ValueError):
        restore(bundle, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("bad", ["../outside.txt", "/outside.txt", "jobs/../secret.env"])
def test_backup_rejects_escaping_paths(tmp_path, bad):
    from ecom_video.maintenance import backup

    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute("UPDATE assets SET path=?", (bad,))
    with pytest.raises(ValueError):
        backup(root, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_backup_rejects_symlink_missing_or_changed_asset(tmp_path):
    from ecom_video.maintenance import backup

    root, _, _, relative = dataset(tmp_path)
    path = root / relative
    path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"registered-original")
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        backup(root, tmp_path / "snapshot")
    path.unlink()
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        backup(root, tmp_path / "snapshot")


def test_pending_task_blocks_backup(tmp_path):
    from ecom_video.maintenance import backup

    root, store, job, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
    with pytest.raises(ValueError, match="任务"):
        backup(root, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_future_schema_is_never_migrated(tmp_path):
    from ecom_video.maintenance import backup, check

    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute("PRAGMA user_version=999")
    assert check(root)["database"]["status"] == "unsupported"
    with pytest.raises(ValueError, match="版本"):
        backup(root, tmp_path / "snapshot")
    with sqlite3.connect(root / "workflow.db") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 999


def test_backup_must_be_outside_source(tmp_path):
    from ecom_video.maintenance import backup

    root, _, _, _ = dataset(tmp_path)
    with pytest.raises(ValueError):
        backup(root, root / "backups/snapshot")
    assert not (root / "backups").exists()


def test_check_api_and_guide_preserve_business_rows(tmp_path):
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app

    root, store, job, _ = dataset(tmp_path)
    with TestClient(create_app(root), base_url="http://localhost") as client:
        response = client.get("/api/system/check")
        assert response.status_code == 200
        assert response.json()["database"]["schema"] == SCHEMA_VERSION
        assert "deliveryCheck" in client.get("/guide").text
        assert client.get("/api/system/check", headers={"Host": "evil.example"}).status_code == 400
    assert store.get(job["id"])["status"] == "draft"


def test_single_sentence_and_analysis_evidence_are_included(tmp_path):
    from ecom_video.maintenance import references

    with sqlite3.connect(":memory:") as c:
        c.execute("CREATE TABLE voice_patches(files TEXT)")
        c.execute(
            "INSERT INTO voice_patches VALUES(?)",
            (
                json.dumps(
                    {
                        "old": {"path": "customers/p/voice-patches/a/old.wav", "sha256": "old"},
                        "new": {"path": "customers/p/voice-patches/a/new.wav", "sha256": "new"},
                    }
                ),
            ),
        )
        c.execute(
            "CREATE TABLE media_analyses(id TEXT,media_id TEXT,status TEXT,result TEXT,created_at REAL)"
        )
        c.execute(
            "INSERT INTO media_analyses VALUES(?,'media','ready',?,1)",
            ("a", json.dumps({"segments": [{"frames": ["00-0.jpg"]}]})),
        )
        assert references(c, {"voice_patches", "media_analyses"}) == {
            "customers/p/voice-patches/a/old.wav": "old",
            "customers/p/voice-patches/a/new.wav": "new",
            "analyses/a/00-0.jpg": None,
        }


def test_active_compute_lease_blocks_backup(tmp_path):
    from ecom_video.maintenance import backup

    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute("INSERT INTO resource_leases VALUES('speech','token',?)", (time.time() + 60,))
    with pytest.raises(ValueError, match="任务"):
        backup(root, tmp_path / "snapshot")


def test_legacy_database_is_backed_up_without_migration(tmp_path):
    from ecom_video.maintenance import PROJECT, backup, restore

    root = tmp_path / "legacy"
    root.mkdir()
    with sqlite3.connect(root / "workflow.db") as c:
        c.executescript((PROJECT / "ecom_video/migrations/001_initial.sql").read_text())
        c.execute("PRAGMA user_version=1")
    backup(root, tmp_path / "snapshot")
    restore(tmp_path / "snapshot", tmp_path / "restored")
    with sqlite3.connect(tmp_path / "restored/workflow.db") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1


def test_cli_reports_specific_failure_without_traceback(tmp_path):
    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute("UPDATE jobs SET status='queued'")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ecom_video.maintenance",
            "backup",
            "--data",
            str(root),
            "--to",
            str(tmp_path / "snapshot"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and not result.stderr
    body = json.loads(result.stdout)
    assert "先在页面暂停/取消" in body["message"]
    assert body["code"] == "maintenance_blocked"


def test_check_does_not_create_wal_sidecars(tmp_path):
    from ecom_video.maintenance import check

    root, _, _, _ = dataset(tmp_path)
    before = {p.relative_to(root) for p in root.rglob("*")}
    assert check(root)["database"]["status"] == "ok"
    assert {p.relative_to(root) for p in root.rglob("*")} == before


def test_cleaned_old_analysis_frames_do_not_break_backup(tmp_path):
    from ecom_video.maintenance import backup, restore

    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        # Standalone schema fixture: only column behavior matters for reference selection.
        c.execute("DROP TABLE media_analyses")
        c.execute(
            "CREATE TABLE media_analyses(id TEXT,media_id TEXT,status TEXT,result TEXT,created_at REAL)"
        )
        raw = json.dumps({"segments": [{"frames": ["00-0.jpg"]}]})
        c.execute("INSERT INTO media_analyses VALUES('old','asset','partial',?,1)", (raw,))
        c.execute("INSERT INTO media_analyses VALUES('new','asset','partial',?,2)", (raw,))
    frame = root / "analyses/new/00-0.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"current frame")
    result = backup(root, tmp_path / "snapshot")
    assert result["files"] == 2
    restore(tmp_path / "snapshot", tmp_path / "restored")
    assert (tmp_path / "restored/analyses/new/00-0.jpg").read_bytes() == b"current frame"
    with sqlite3.connect(tmp_path / "restored/workflow.db") as c:
        assert c.execute("SELECT count(*) FROM media_analyses").fetchone()[0] == 2


def test_frozen_analysis_survives_deleted_library_media(tmp_path):
    from ecom_video.maintenance import backup, restore

    root, store, _, _ = dataset(tmp_path)
    with store.transaction() as c:
        c.execute(
            "UPDATE assets SET metadata=?",
            (
                json.dumps(
                    {
                        "content_analysis": {
                            "analysis_id": "removed",
                            "segments": [{"frames": ["00-0.jpg"]}],
                        }
                    }
                ),
            ),
        )
    frame = root / "analyses/removed/00-0.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"frozen evidence")
    assert backup(root, tmp_path / "snapshot")["files"] == 2
    restore(tmp_path / "snapshot", tmp_path / "restored")
    assert (tmp_path / "restored/analyses/removed/00-0.jpg").read_bytes() == b"frozen evidence"


def test_check_sees_committed_wal_without_modifying_it(tmp_path):
    from ecom_video.maintenance import check, digest

    root, _, job, _ = dataset(tmp_path)
    with sqlite3.connect(root / "workflow.db") as c:
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute("UPDATE jobs SET status='queued' WHERE id=?", (job["id"],))
        c.commit()
        before = {p.name: digest(p) for p in root.glob("workflow.db*")}
        assert check(root)["database"]["pending"]["jobs"] == 1
        assert {p.name: digest(p) for p in root.glob("workflow.db*")} == before
