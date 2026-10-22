"""All records here are synthetic unit fixtures, never customer approvals."""

import copy
import hashlib
import io
import json
import zipfile


def predicate_input():
    # Pure predicate input only; no business database or customer record is created.
    sha = hashlib.sha256("原稿".encode()).hexdigest()
    p = {
        "settings": {"review_context": ""},
        "inputs_changed": False,
        "product": {"current_review_id": "facts", "current_draft_id": "draft"},
        "job": {
            "id": "job",
            "status": "ready",
            "script_hash": sha,
            "script": "原稿",
            "provenance": {
                "fact_review": {"id": "facts", "reviewer": "A"},
                "script_approval": {"draft_id": "draft", "reviewer": "A", "script_hash": sha},
            },
            "storyboard": {"creative": {"style_id": "cinema"}, "narration": {"mode": "uploaded"}},
            "snapshot": {"alignment": {"timing_review": {"reviewer": "A", "confirmed_at": 1}}},
            "reviews": [
                {"decision": "ready", "reviewer": "A", "checklist_confirmed": 1, "script_hash": sha}
            ],
            "artifacts": [{"kind": "video"}],
        },
    }
    from ecom_video.alignment import input_hash
    from ecom_video.creative import signature

    job = p["job"]
    voice = {"id": "voice", "kind": "audio", "sha256": "a" * 64}
    job["assets"] = [voice]
    job["storyboard"]["narration"]["asset_id"] = "voice"
    job["storyboard"]["creative"]["alignment_id"] = "aligned"
    fingerprint = input_hash(job, voice)
    job["snapshot"]["alignment"].update(audio_sha256=voice["sha256"])
    job["snapshot"]["alignment"]["timing_review"]["input_fingerprint"] = fingerprint
    job["snapshot"]["script"] = job["script"]
    job["snapshot"]["storyboard"] = copy.deepcopy(job["storyboard"])
    p["alignment"] = {
        "id": "aligned",
        "job_id": job["id"],
        "reviewer": "A",
        "fingerprint": fingerprint,
        "status": "confirmed",
    }
    job["artifacts"][0]["sha256"] = "b" * 64
    job["audit"] = {"output_sha256": "b" * 64, "snapshot_sha256": signature(job["snapshot"])}
    return p


def test_all_gates_required_and_fixture_is_never_customer_approval():
    from ecom_video.customer_handoff import status

    p = predicate_input()
    assert status(p)["approved_for_handoff"] is True
    for path in ("fact_review", "script_approval"):
        changed = copy.deepcopy(p)
        changed["job"]["provenance"][path]["reviewer"] = "AUTOMATED FIXTURE"
        assert not status(changed)["approved_for_handoff"]
    changed = copy.deepcopy(p)
    changed["job"]["snapshot"]["alignment"]["timing_review"]["automated_fixture"] = True
    assert not status(changed)["approved_for_handoff"]
    for field in ("inputs_changed",):
        changed = copy.deepcopy(p)
        changed[field] = True
        assert not status(changed)["approved_for_handoff"]
    for field in ("snapshot", "provenance", "storyboard", "reviews"):
        changed = copy.deepcopy(p)
        changed["job"][field] = None if field != "reviews" else []
        assert not status(changed)["approved_for_handoff"]
    assert not status({"job": None})["export_available"]


def test_delivery_requires_both_real_consistent_style_records():
    from ecom_video.creative import signature
    from ecom_video.customer_handoff import status

    p = predicate_input()
    p["job"]["storyboard"]["delivery"] = {"version": 1}
    p["job"]["snapshot"]["storyboard"] = copy.deepcopy(p["job"]["storyboard"])
    reviews = {
        stage: {"reviewer": "A", "confirmed": True, "style_id": "cinema"}
        for stage in ("direction", "storyboard")
    }
    p["job"]["snapshot"]["delivery_reviews"] = reviews

    def result():
        p["job"]["audit"]["snapshot_sha256"] = signature(p["job"]["snapshot"])
        return status(p)

    assert result()["approved_for_handoff"]
    reviews["direction"]["reviewer"] = "AUTOMATED FIXTURE"
    assert result()["fixture"] and not result()["approved_for_handoff"]
    reviews["direction"] = {"reviewer": "A", "confirmed": True, "style_id": "social"}
    assert not result()["approved_for_handoff"]
    reviews.pop("direction")
    assert not result()["approved_for_handoff"]


def fixture_project(tmp_path):
    from test_customer import approve, client, picture, plan, prepare, project

    from ecom_video.media import digest

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    media = tmp_path / "unit-fixture-video.mp4"
    media.write_bytes(b"NOT A REAL VIDEO: synthetic export unit fixture")
    with c.app.state.store.transaction() as conn:
        conn.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (p["job"]["id"],))
        conn.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            ("video", p["job"]["id"], "video", media.name, digest(media), media.stat().st_size, 1),
        )
    return c, c.get("/api/customer-projects/" + p["id"]).json()


def version(p):
    return {
        "revision": p["revision"],
        "job_id": p["job"]["id"],
        "board_revision": p["job"]["storyboard_revision"],
    }


def test_export_freezes_hashes_gates_and_does_not_mutate_job(tmp_path):
    c, p = fixture_project(tmp_path)
    before = copy.deepcopy(p["job"])
    url = "/api/customer-projects/" + p["id"]
    r = c.post(url + "/handoffs", json=version(p))
    assert r.status_code == 201, r.text
    info = r.json()
    assert not info["approved_for_handoff"] and info["classification"] == "review"
    data = c.get(info["download_url"]).content
    assert hashlib.sha256(data).hexdigest() == info["sha256"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("HANDOFF.json"))
        assert not manifest["approved_for_handoff"]
        for row in manifest["files"]:
            assert hashlib.sha256(z.read(row["path"])).hexdigest() == row["sha256"]
        assert z.read("script.txt").decode() == p["job"]["script"]
        assert not any(n.endswith((".db", ".onnx")) or "originals" in n for n in z.namelist())
        assert str(tmp_path).encode() not in z.read("HANDOFF.json")
    assert c.get("/api/jobs/" + before["id"]).json() == before
    from test_customer import project

    other = project(c)
    assert c.get(info["download_url"].replace(p["id"], other["id"])).status_code == 404
    assert (
        c.post(url + "/handoffs", json={**version(p), "revision": p["revision"] - 1}).status_code
        == 409
    )


def test_changed_or_missing_output_does_not_leave_downloadable_package(tmp_path):
    c, p = fixture_project(tmp_path)
    (tmp_path / "unit-fixture-video.mp4").write_bytes(b"tampered")
    r = c.post("/api/customer-projects/" + p["id"] + "/handoffs", json=version(p))
    assert r.status_code == 409, r.text
    assert not list((tmp_path / "customers" / p["id"]).rglob("*.zip"))


def test_export_guard_rejects_changes_during_copy(tmp_path, monkeypatch):
    from ecom_video.customer_handoff import Handoff

    c, p = fixture_project(tmp_path)
    original = Handoff._write

    def race(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE customer_projects SET revision=revision+1 WHERE product_id=?", (p["id"],)
            )
        return value

    monkeypatch.setattr(Handoff, "_write", race)
    r = c.post("/api/customer-projects/" + p["id"] + "/handoffs", json=version(p))
    assert r.status_code == 409
    assert not list((tmp_path / "customers" / p["id"]).rglob("*.zip"))


def test_partial_legacy_receipts_without_ids_or_hash_do_not_pass():
    from ecom_video.customer_handoff import status

    p = predicate_input()
    p["product"] = {}
    p["job"].pop("script_hash")
    p["job"]["provenance"]["fact_review"].pop("id")
    p["job"]["provenance"]["script_approval"] = {"reviewer": "A"}
    p["job"]["reviews"][0].pop("script_hash")
    assert not status(p)["approved_for_handoff"]


def test_missing_or_contradictory_voice_and_film_bindings_stay_pending():
    from ecom_video.customer_handoff import status

    for mutate in (
        lambda p: p["job"]["snapshot"]["alignment"]["timing_review"].pop("input_fingerprint"),
        lambda p: p["job"]["snapshot"]["alignment"].pop("audio_sha256"),
        lambda p: p["job"]["assets"][0].update(sha256="c" * 64),
        lambda p: p["job"]["audit"].update(output_sha256="d" * 64),
        lambda p: p["job"]["audit"].pop("snapshot_sha256"),
    ):
        p = predicate_input()
        mutate(p)
        assert not status(p)["approved_for_handoff"]


def test_corrupt_archive_and_resource_limits_are_rejected(tmp_path, monkeypatch):
    from ecom_video import customer_handoff

    c, p = fixture_project(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    info = c.post(base + "/handoffs", json=version(p)).json()
    archive = tmp_path / "customers" / p["id"] / "handoffs" / (info["id"] + ".zip")
    archive.write_bytes(b"bad")
    assert c.get(info["download_url"]).status_code == 409
    monkeypatch.setattr(customer_handoff, "MAX_BYTES", 1)
    assert c.post(base + "/handoffs", json=version(p)).status_code == 422
    assert customer_handoff.LOCK.acquire(blocking=False)
    try:
        assert c.post(base + "/handoffs", json=version(p)).status_code == 409
    finally:
        customer_handoff.LOCK.release()


def test_changed_brief_can_export_old_film_only_as_review_package(tmp_path):
    c, p = fixture_project(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    settings = copy.deepcopy(p["settings"])
    settings["brief"]["audience"] = "新的受众"
    p = c.put(base, json={"revision": p["revision"], "settings": settings}).json()
    assert p["inputs_changed"]
    r = c.post(base + "/handoffs", json=version(p))
    assert r.status_code == 201, r.text
    assert not r.json()["approved_for_handoff"]
    assert any("输入已变化" in b for b in r.json()["blockers"])
