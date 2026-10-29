"""Synthetic regression data only; never customer approvals or platform activity."""

import copy
import hashlib
import json

import pytest


def ready_predicate_project(root):
    """Model the complete approval predicate in disposable test data, with no real video."""
    from test_customer_handoff import fixture_project

    from ecom_video.creative import signature
    from ecom_video.customer_handoff import status

    c, p = fixture_project(root)
    job = p["job"]
    sha = hashlib.sha256(job["script"].encode()).hexdigest()
    provenance = copy.deepcopy(job["provenance"])
    for key in ("fact_review", "script_approval"):
        provenance[key].update(reviewer="A", note="predicate input")
    provenance["script_approval"]["script_hash"] = sha
    snapshot = {"script": job["script"], "storyboard": job["storyboard"]}
    audit = {
        "output_sha256": job["artifacts"][0]["sha256"],
        "snapshot_sha256": signature(snapshot),
    }
    store = c.app.state.store
    with store.transaction() as db:
        db.execute(
            "UPDATE jobs SET script_hash=?,provenance=?,snapshot=?,audit=? WHERE id=?",
            (sha, json.dumps(provenance), json.dumps(snapshot), json.dumps(audit), job["id"]),
        )
    store.review(job["id"], "ready", "A", "predicate input", True)
    p = c.get("/api/customer-projects/" + p["id"]).json()
    assert status(p)["approved_for_handoff"] is True
    return c, p


@pytest.mark.parametrize("case", ["complete", "fixture", "facts_missing", "stale", "historical"])
def test_publication_uses_the_complete_version_bound_handoff_predicate(tmp_path, case):
    from ecom_video.customer_handoff import status
    from ecom_video.operations.media_pack import publication_pack
    from ecom_video.operations.records import Records

    c, p = ready_predicate_project(tmp_path)
    jid = p["job"]["id"]
    with c.app.state.store.transaction() as db:
        if case == "fixture":
            db.execute(
                "UPDATE reviews SET reviewer='非客户模拟确认',note='模拟审批' WHERE job_id=?",
                (jid,),
            )
        elif case == "facts_missing":
            provenance = copy.deepcopy(p["job"]["provenance"])
            provenance["fact_review"] = {}
            db.execute("UPDATE jobs SET provenance=? WHERE id=?", (json.dumps(provenance), jid))
        elif case == "stale":
            db.execute("UPDATE products SET current_review_id=NULL WHERE id=?", (p["id"],))
        elif case == "historical":
            db.execute(
                "UPDATE customer_projects SET active_job_id=NULL WHERE product_id=?", (p["id"],)
            )
    current = c.get("/api/customer-projects/" + p["id"]).json()
    expected = status(current)["approved_for_handoff"] and current["job"]["id"] == jid
    assert expected is (case == "complete")
    records = Records(tmp_path, c.app.state.store)
    pack = publication_pack(records, jid, "douyin", "谓词单元数据", "不是客户审批")
    assert (pack["payload"]["review_status"] == "approved_for_manual_handoff") is expected
    assert pack["payload"]["handoff_review"]["approved_for_handoff"] is expected
    assert pack["payload"]["can_publish"] is False


def test_every_result_card_file_is_downloadable_and_still_hash_checked(tmp_path):
    from test_customer import client
    from test_operations_observations import contract, source

    from ecom_video.operations.comments import analyze_comments, import_comments
    from ecom_video.operations.observations import freeze_observations, import_csv
    from ecom_video.operations.records import Records
    from ecom_video.operations.research import analyze_market

    c = client(tmp_path)
    records = Records(tmp_path, c.app.state.store)
    original = source(records)
    batch = import_csv(records, original["id"], contract())
    frozen = freeze_observations(records, [batch["id"]])
    market = analyze_market(
        records,
        b"sku,product_name,price,currency,sampled_at,source\na,Demo,100,CNY,2026-10-01,test-row\n",
        "AUTOMATED FIXTURE",
        "douyin",
    )
    comments = import_comments(
        records,
        original["payload"]["account_ref"],
        "content_id,nickname,text\nclip-1,PrivateName,口袋多大？联系13812345678\n".encode(),
        "AUTOMATED FIXTURE",
    )
    insight = analyze_comments(records, comments["id"])
    for row in (original, batch, frozen, market, comments, insight):
        for index, file in enumerate(row["files"]):
            url = f"/api/operations/objects/{row['id']}/files/{index}"
            response = c.get(url)
            assert response.status_code == 200, row["kind"]
            assert hashlib.sha256(response.content).hexdigest() == file["sha256"]
            if row["kind"] in ("comments", "comment_insights"):
                assert (
                    b"PrivateName" not in response.content
                    and b"13812345678" not in response.content
                )
        assert c.get(f"/api/operations/objects/{row['id']}/files/-1").status_code == 404
        assert c.get(f"/api/operations/objects/{row['id']}/files/99").status_code == 404
    file = tmp_path / comments["files"][0]["path"]
    file.write_bytes(b"tampered")
    assert c.get(f"/api/operations/objects/{insight['id']}/files/0").status_code == 422


def test_handoff_rejects_approval_context_changed_during_packaging(tmp_path, monkeypatch):
    import zipfile

    from ecom_video.db import Conflict
    from ecom_video.operations.media_pack import publication_pack
    from ecom_video.operations.records import Records

    c, p = ready_predicate_project(tmp_path)
    records = Records(tmp_path, c.app.state.store)
    original = zipfile.ZipFile.writestr
    changed = False

    def race(archive, name, *args, **kwargs):
        nonlocal changed
        result = original(archive, name, *args, **kwargs)
        if not changed:
            changed = True
            with records.store.transaction() as db:
                db.execute("UPDATE products SET current_review_id=NULL WHERE id=?", (p["id"],))
        return result

    monkeypatch.setattr(zipfile.ZipFile, "writestr", race)
    with pytest.raises(Conflict):
        publication_pack(records, p["job"]["id"], "douyin", "单元数据", "不是客户审批")
    assert not records.listing("publication_pack")


@pytest.mark.parametrize("reference_copied", [True, False])
def test_next_project_rebinds_reference_without_reusing_approval_or_lowering_checks(
    tmp_path, reference_copied
):
    from test_customer import approve, client, picture, prepare, project
    from test_operations_observations import contract

    from ecom_video.connectors.xhs_import import add_account, freeze_source
    from ecom_video.customer import Customers
    from ecom_video.media import digest
    from ecom_video.operations.iterations import hypotheses, select_hypothesis
    from ecom_video.operations.media_pack import publication_pack, register_content
    from ecom_video.operations.observations import freeze_observations, import_csv
    from ecom_video.operations.records import Records
    from ecom_video.product_inspection import context_for

    c = client(tmp_path)
    p = picture(c, picture(c, project(c)))
    ref = p["media"][-1]
    settings = {
        **p["settings"],
        "strict_product": True,
        "action_timing": True,
        "material_checks": True,
        "product_reference_id": ref["id"],
    }
    p = c.put(
        "/api/customer-projects/" + p["id"], json={"revision": p["revision"], "settings": settings}
    ).json()
    p = prepare(c, approve(c, p))
    store = c.app.state.store
    jid = p["job"]["id"]
    fake = tmp_path / "predicate-only.mp4"
    fake.write_bytes(b"NOT VIDEO; synthetic review regression")
    with store.transaction() as db:
        if not reference_copied:
            db.execute(
                "DELETE FROM assets WHERE job_id=? AND json_extract(metadata,'$.library_id')=?",
                (jid, ref["id"]),
            )
        db.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (jid,))
        db.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            ("test", jid, "video", fake.name, digest(fake), fake.stat().st_size, 1),
        )
    records = Records(tmp_path, store)
    account = add_account(records, "douyin", "AUTOMATED FIXTURE", "owned")
    pack = publication_pack(records, jid, "douyin", "单元测试", "待审")
    register_content(records, pack["id"], account["id"], "clip-1", "AUTOMATED FIXTURE", True)
    s = freeze_source(
        records,
        account["id"],
        b"content_id,metric_date,views\nclip-1,2026-10-01,100\n",
        "test.csv",
        "AUTOMATED FIXTURE",
    )
    batch = import_csv(records, s["id"], contract())
    snapshot = freeze_observations(records, [batch["id"]])
    h = hypotheses(records, snapshot["id"], jid)
    chosen = select_hypothesis(records, h["id"], "detail", "AUTOMATED FIXTURE", True)
    child = Customers(tmp_path, store).get(chosen["payload"]["project_id"])
    assert all(
        child["settings"][key] for key in ("strict_product", "action_timing", "material_checks")
    )
    assert (
        child["job"] is None
        and not child["product"]["fact_reviews"]
        and not child["product"]["script_approvals"]
    )
    reference_id = child["settings"]["product_reference_id"]
    if reference_copied:
        assert reference_id != ref["id"]
        new_ref = next(a for a in child["media"] if a["id"] == reference_id)
        assert new_ref["sha256"] == ref["sha256"] == digest(tmp_path / new_ref["path"])
        with store.connect() as db:
            assert context_for(db, child["id"])["reference_id"] == reference_id
        response = c.put(
            "/api/customer-projects/" + child["id"],
            json={
                "revision": child["revision"],
                "settings": {**child["settings"], "auto_select": True},
            },
        )
        assert response.status_code == 200, response.text
    else:
        assert reference_id is None
        assert any("参照图" in note for note in chosen["payload"]["warnings"])
        with store.connect() as db, pytest.raises(ValueError, match="参照图"):
            context_for(db, child["id"])
