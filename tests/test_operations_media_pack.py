import json
import zipfile

import pytest


def video_job(records):
    from ecom_video.media import digest

    job = records.store.create_job("AUTOMATED FIXTURE", "外套细节")
    path = records.root / "jobs" / job["id"] / "output.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"engineering fixture, not real mp4")
    with records.store.transaction() as c:
        c.execute("UPDATE jobs SET status='needs_review',snapshot='{}' WHERE id=?", (job["id"],))
        c.execute(
            "INSERT INTO artifacts(id,job_id,kind,path,sha256,size,attempt) VALUES(?,?,?,?,?,?,?)",
            (
                job["id"],
                job["id"],
                "video",
                path.relative_to(records.root).as_posix(),
                digest(path),
                path.stat().st_size,
                1,
            ),
        )
    return job["id"], path


def test_pending_publication_pack_is_traceable_and_never_implies_publish_approval(tmp_path):
    from ecom_video.connectors.xhs_import import add_account
    from ecom_video.db import Store
    from ecom_video.media import safe_path
    from ecom_video.operations.media_pack import publication_pack, register_content
    from ecom_video.operations.records import Records

    records = Records(tmp_path, Store(tmp_path / "workflow.db"))
    jid, path = video_job(records)
    pack = publication_pack(records, jid, "douyin", "看清外套细节", "客户自行核对文案")
    assert pack["payload"]["review_status"] == "pending"
    assert pack["payload"]["can_publish"] is False
    archive = zipfile.ZipFile(safe_path(tmp_path, pack["files"][0]["path"]))
    assert "video.mp4" in archive.namelist()
    manifest = json.loads(archive.read("handoff.json"))
    assert manifest["video_sha256"] == pack["payload"]["video_sha256"]
    account = add_account(records, "douyin", "工程账户", "owner")
    with pytest.raises(ValueError):
        register_content(records, pack["id"], account["id"], "123", "", False)
    binding = register_content(
        records, pack["id"], account["id"], "123", "AUTOMATED FIXTURE mapping only", True
    )
    assert (
        binding["payload"]["job_id"] == jid
        and binding["payload"]["ownership"] == "declared_mapping"
    )
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        publication_pack(records, jid, "douyin", "title", "copy")


def test_image_pack_uses_bound_product_assets_or_explicit_schematic(tmp_path):
    from test_customer import approve, client, picture, project

    from ecom_video.operations.media_pack import image_pack
    from ecom_video.operations.records import Records
    from ecom_video.operations.research import create_strategy

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    r = Records(tmp_path, c.app.state.store)
    s = create_strategy(r, p["id"], p["product"]["revision"], "通勤人群", "克制", None)
    schematic = image_pack(r, s["id"], None)
    assert schematic["payload"]["display_kind"] == "schematic_not_product_photo"
    real = image_pack(r, s["id"], p["media"][0]["id"])
    assert real["payload"]["display_kind"] == "provided_asset_with_literal_text"
    assert real["payload"]["review_status"] == "pending"
    with pytest.raises(ValueError):
        image_pack(r, s["id"], "a" * 32)
