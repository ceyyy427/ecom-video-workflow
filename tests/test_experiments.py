import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_customer import approve, client, picture, plan, prepare, project
from test_review_snapshots import command, ingest

from ecom_video.creative_features import sha
from ecom_video.db import Conflict
from ecom_video.distribution import Distribution
from ecom_video.media import digest
from ecom_video.reporting import Reporting

LABEL = "AUTOMATED FIXTURE P16，非真实客户审批"


def finish(root, store, jid):
    """Unit fixture only: synthetic artifact bytes, never evidence of rendering quality."""
    job = store.get(jid)
    if job["status"] == "draft":
        store.submit(jid)
    file = root / (jid + ".mp4")
    file.write_bytes(b"P16 synthetic fixture, not playable video")
    with store.transaction() as c:
        c.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (jid,))
        c.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            (jid, jid, "video", file.name, digest(file), file.stat().st_size, 1),
        )
    store.review(jid, "ready", LABEL, "unit fixture only", True)


def build_env(tmp_path, monkeypatch, with_voice=False):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    monkeypatch.setenv("ECOM_EXPERIMENTS_ENABLED", "1")
    c = client(tmp_path)
    p = picture(c, project(c))
    if with_voice:
        from test_customer import audio, fixture_alignment, narrated, plan_payload

        p = prepare(c, approve(c, narrated(c, audio(c, p))))
        alignment = fixture_alignment(tmp_path, p)
        p = c.post(
            "/api/customer-projects/" + p["id"] + "/plan", json=plan_payload(p, alignment)
        ).json()
    else:
        p = plan(c, prepare(c, approve(c, p)))
    store = c.app.state.store
    parent = p["job"]["id"]
    finish(tmp_path, store, parent)
    aid = Distribution(tmp_path, store).add_account(LABEL, "qianchuan", "123")["id"]
    reports = Reporting(tmp_path, store)
    reports.bind(aid, "123", parent, LABEL)
    ingest(reports, aid, "2026-10-01,123,10,100,10,1,20,100,10\n")
    from ecom_video.experiments import Experiments
    from ecom_video.review_snapshots import Reviews

    review = Reviews(tmp_path, store).create(command(aid, end="2026-10-01"))
    body = {
        "request_id": "proposal-1",
        "review_id": review["review_id"],
        "material_id": "123",
        "parent_job_id": parent,
        "hypothesis": "更清楚的杯口细节可能值得继续观察，尚无效果结论",
        "target_metric": "ctr",
        "change_set": {
            "kind": "visual",
            "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
            "changes": {"focus_x": 0.7},
        },
        "comparison_policy": {"min_reported_days": 1, "min_impressions": 100},
        "actor": LABEL,
    }
    return Experiments(tmp_path, store), body, c, review


@pytest.fixture
def env(tmp_path, monkeypatch):
    return build_env(tmp_path, monkeypatch)


def action(exp, request_id, **kw):
    return {"request_id": request_id, "expected_revision": exp["revision"], "actor": LABEL, **kw}


def selected(env):
    service, body, _, _ = env
    e = service.create(body)
    return service.select(
        e["id"], action(e, "select-1", decision="selected", confirmed=True, note="fixture 人工选择")
    )


def style(service, e):
    job = service.store.get(e["result_job_id"])
    return service.style_confirm(
        e["id"],
        action(
            e,
            "style-1",
            confirmed=True,
            job_id=job["id"],
            board_revision=job["storyboard_revision"],
            style_id=job["storyboard"]["creative"]["style_id"],
        ),
    )


def test_proposal_selection_does_not_create_or_mutate_parent(env):
    service, body, _, review = env
    before = service.store.get(body["parent_job_id"])
    e = service.create(body)
    assert e["status"] == "proposed" and e["result_job_id"] is None
    assert service.create(body) == e
    assert e["proposal"]["review_hash"] == review["snapshot_hash"]
    with pytest.raises(Conflict):
        service.create({**body, "hypothesis": "changed"})
    with pytest.raises(ValueError):
        service.select(
            e["id"], action(e, "bad-confirm", decision="selected", confirmed=False, note="x")
        )
    chosen = selected(env)
    assert chosen["status"] == "selected"
    assert service.store.get(body["parent_job_id"]) == before


def test_visual_apply_atomic_idempotent_new_draft_and_style_gate(env):
    service, body, _, _ = env
    e = selected(env)
    parent = service.store.get(body["parent_job_id"])
    cmd = action(e, "apply-1")
    child = service.apply(e["id"], cmd)
    jid = child["result_job_id"]
    j = service.store.get(jid)
    assert child["status"] == "draft_created" and j["status"] == "draft"
    assert j["parent_id"] == parent["id"] and j["provenance"] == parent["provenance"]
    assert j["storyboard"]["shots"][0]["focus_x"] == 0.7
    handoff = service.customers.get(child["proposal"]["product_id"])["iteration"]
    assert handoff["id"] == child["id"] and handoff["style_confirm_needed"]
    assert service.apply(e["id"], cmd) == child
    assert service.store.get(parent["id"]) == parent
    with pytest.raises(Conflict, match="风格"):
        service.store.submit(jid)
    style(service, child)
    assert not service.customers.get(child["proposal"]["product_id"])["iteration"][
        "style_confirm_needed"
    ]
    assert service.store.submit(jid)["status"] == "queued"


def test_concurrent_same_apply_creates_one_child(env):
    service, _, _, _ = env
    e = selected(env)
    cmd = action(e, "apply-concurrent")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.apply(e["id"], cmd), range(2)))
    assert results[0] == results[1]
    with service.store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM jobs WHERE parent_id=?", (e["proposal"]["parent_job_id"],)
            ).fetchone()[0]
            == 1
        )


def test_stale_product_or_voice_and_receipt_failure_leave_no_child(env, monkeypatch):
    service, body, _, _ = env
    e = selected(env)
    with service.store.transaction() as c:
        c.execute(
            "UPDATE products SET revision=revision+1 WHERE id=?", (e["proposal"]["product_id"],)
        )
    with pytest.raises(Conflict, match="变化|过期"):
        service.apply(e["id"], action(e, "stale-apply"))
    with service.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM jobs WHERE parent_id=?", (body["parent_job_id"],)
        ).fetchone()


def test_script_apply_is_unapproved_and_attach_requires_same_new_confirmed_script(env):
    service, body, c, _ = env
    product = c.get(
        "/api/products/" + service.context(body["review_id"], body["material_id"])["product_id"]
    ).json()
    scenes = product["script_drafts"][-1]["payload"]
    body["change_set"] = {"kind": "script", "scenes": scenes}
    e = selected(env)
    result = service.apply(e["id"], action(e, "apply-script"))
    assert result["result_job_id"] is None and result["result_script_draft_id"]
    prod = c.get("/api/products/" + e["proposal"]["product_id"]).json()
    assert prod["status"] == "script_draft"
    assert prod["current_draft_id"] == result["result_script_draft_id"]
    with pytest.raises(Conflict):
        service.attach(e["id"], action(result, "attach-bad", job_id=body["parent_job_id"]))


def test_events_proposals_and_command_receipts_are_immutable(env):
    service, body, _, _ = env
    e = service.create(body)
    with service.store.connect() as c:
        from ecom_video.db import SCHEMA_VERSION
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        for sql in [
            "UPDATE experiments SET payload='{}'",
            "DELETE FROM experiments",
            "DELETE FROM experiment_events",
            "DELETE FROM experiment_commands",
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(sql)
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
    assert sha(e["proposal"]) == e["proposal_hash"]


def test_v11_migration_preserves_existing_snapshot_rows(tmp_path):
    with sqlite3.connect(tmp_path / "workflow.db") as c:
        for file in sorted(Path("ecom_video/migrations").glob("*.sql"))[:11]:
            c.executescript(file.read_text())
        c.execute("PRAGMA user_version=11")
        c.execute(
            "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at) VALUES('old','old','old',1,'draft',1,1)"
        )
        c.execute(
            "INSERT INTO platform_accounts VALUES('a','fixture','qianchuan','123','','CNY','Asia/Shanghai',1)"
        )
        c.execute(
            "INSERT INTO report_batches VALUES(7,'b','a','2026-10-01','2026-10-01','csv','sha','path','fixture','{}',1)"
        )
        c.execute("INSERT INTO report_rows VALUES('b','2026-10-01','123','{}')")
        c.execute(
            "INSERT INTO review_snapshots VALUES('r','fixture-request','cmd','a','2026-10-01','2026-10-01',?,'{}','fixture',1)",
            (sha({}),),
        )
        c.execute(
            "INSERT INTO review_sources VALUES('r','b','path','sha','[\"2026-10-01\"]','rows-hash')"
        )
        c.execute("INSERT INTO review_feature_links VALUES('r','123',NULL,NULL)")
        names = [
            r[0]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] not in ("schema_migrations", "sqlite_sequence")
        ]
        before = {n: c.execute("SELECT * FROM " + n + " ORDER BY rowid").fetchall() for n in names}
    from ecom_video.db import Store

    s = Store(tmp_path / "workflow.db")
    assert s.get("old")["script"] == "old"
    with s.connect() as c:
        for n, rows in before.items():
            assert [tuple(r) for r in c.execute("SELECT * FROM " + n + " ORDER BY rowid")] == rows
        assert not c.execute("PRAGMA foreign_key_check").fetchall()


def test_receipt_failure_rolls_back_draft_and_cleans_files(env, monkeypatch):
    service, _, _, _ = env
    e = selected(env)
    before = {p.name for p in (service.root / "jobs").iterdir()}
    original = service.record

    def crash(c, eid, op, cmd):
        if op == "apply":
            raise RuntimeError("fixture receipt failure")
        return original(c, eid, op, cmd)

    monkeypatch.setattr(service, "record", crash)
    with pytest.raises(RuntimeError):
        service.apply(e["id"], action(e, "crash-apply"))
    assert service.get(e["id"])["status"] == "selected"
    assert {p.name for p in (service.root / "jobs").iterdir()} == before
    with service.store.connect() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM jobs WHERE parent_id=?", (e["proposal"]["parent_job_id"],)
            ).fetchone()[0]
            == 0
        )


def test_narrated_iteration_requires_fresh_listening_and_style(tmp_path, monkeypatch):
    from ecom_video.alignment import AlignmentService

    env = build_env(tmp_path, monkeypatch, with_voice=True)
    service, _, _, _ = env
    e = selected(env)
    e = service.apply(e["id"], action(e, "apply-voice"))
    child = service.store.get(e["result_job_id"])
    aid = child["storyboard"]["creative"]["alignment_id"]
    with service.store.connect() as c:
        assert (
            c.execute("SELECT status FROM alignments WHERE id=?", (aid,)).fetchone()[0]
            == "needs_review"
        )
    style(service, e)
    with pytest.raises(ValueError, match="听核|对齐"):
        service.store.submit(child["id"])
    AlignmentService(tmp_path, service.store, recover=False).confirm(child["id"], aid, None, LABEL)
    assert service.store.submit(child["id"])["status"] == "queued"


def test_script_handoff_after_real_confirmation_links_parent_and_rechecks_style(env):
    service, body, c, _ = env
    original = service.store.get(body["parent_job_id"])
    ctx = service.context(body["review_id"], body["material_id"])
    body["change_set"] = {"kind": "script", "scenes": ctx["scenes"]}
    e = selected(env)
    e = service.apply(e["id"], action(e, "apply-script-full"))
    pid = e["proposal"]["product_id"]
    product = c.get("/api/products/" + pid).json()
    approval = c.post(
        "/api/products/" + pid + "/scripts/confirm",
        json={
            "revision": product["revision"],
            "draft_id": e["result_script_draft_id"],
            "reviewer": LABEL,
            "note": "fixture new script confirmation",
            "confirmed": True,
            "seconds": 2,
        },
    )
    assert approval.status_code == 201, approval.text
    p = prepare(c, c.get("/api/customer-projects/" + pid).json())
    e = service.attach(e["id"], action(e, "attach-script-full", job_id=p["job"]["id"]))
    assert service.store.get(e["result_job_id"])["parent_id"] == original["id"]
    p = plan(c, c.get("/api/customer-projects/" + pid).json())
    with pytest.raises(Conflict, match="风格"):
        service.store.submit(p["job"]["id"])
    e = style(service, e)
    assert service.store.submit(e["result_job_id"])["status"] == "queued"
    assert service.store.get(original["id"]) == original


def test_confirmed_style_is_invalid_after_board_edit_even_when_flag_off(env, monkeypatch):
    service, _, _, _ = env
    e = selected(env)
    e = service.apply(e["id"], action(e, "apply-edit"))
    style(service, e)
    job = service.store.get(e["result_job_id"])
    board = job["storyboard"]
    board["shots"][0]["focus_x"] = 0.4
    service.store.save_storyboard(job["id"], board, job["storyboard_revision"])
    monkeypatch.delenv("ECOM_EXPERIMENTS_ENABLED")
    with pytest.raises(Conflict, match="风格"):
        service.store.submit(job["id"])


def test_voice_change_after_selection_expires_changeset(tmp_path, monkeypatch):
    env = build_env(tmp_path, monkeypatch, with_voice=True)
    service, _, _, _ = env
    e = selected(env)
    with service.store.transaction() as c:
        c.execute(
            "UPDATE assets SET sha256=? WHERE job_id=? AND kind='audio'",
            ("0" * 64, e["proposal"]["parent_job_id"]),
        )
    with pytest.raises(Conflict, match="变化|过期"):
        service.apply(e["id"], action(e, "stale-voice"))
