import pytest


def test_immutable_operations_records_and_files_survive_backup_restore(tmp_path):
    from ecom_video.db import Store
    from ecom_video.maintenance import backup, restore
    from ecom_video.media import digest
    from ecom_video.operations.records import Records

    root = tmp_path / "data"
    s = Store(root / "workflow.db")
    records = Records(root, s)
    p = root / "operations/sources/source.csv"
    p.parent.mkdir(parents=True)
    p.write_text("views\n0\n")
    a = records.put(
        "source",
        {"sha256": digest(p), "file_name": "source.csv"},
        files=[{"path": p.relative_to(root).as_posix(), "sha256": digest(p)}],
    )
    assert records.put("source", a["payload"], files=a["files"])["id"] == a["id"]
    bundle = tmp_path / "backup"
    backup(root, bundle)
    target = tmp_path / "restored"
    restore(bundle, target)
    assert Records(target, Store(target / "workflow.db")).get(a["id"]) == a
    (target / p.relative_to(root)).write_text("corrupt")
    with pytest.raises(ValueError):
        Records(target, Store(target / "workflow.db")).get(a["id"])
