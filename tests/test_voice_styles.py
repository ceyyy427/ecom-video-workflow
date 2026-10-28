"""HTTP fixture only; real product gates, audio probe, database and take files."""

import hashlib
import json

import httpx
import pytest
from test_customer import approve, picture, prepare, project
from test_volc_voice import body, configured, sse
from test_volc_voice import mp3 as fixture_mp3


@pytest.fixture
def mp3(tmp_path):
    return fixture_mp3.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def private_environment(monkeypatch):
    monkeypatch.delenv("DOUBAO_TTS_API_KEY", raising=False)


def styled(p, style="social"):
    return {**body(p), "style_id": style, "direction_basis": p["direction_basis"]}


def test_three_profiles_and_preview_are_bound_to_confirmed_copy_without_changing_inputs(
    tmp_path, monkeypatch, mp3
):
    c, _ = configured(tmp_path, monkeypatch)
    p = prepare(c, approve(c, picture(c, project(c))))
    base = f"/api/customer-projects/{p['id']}"
    seen = []

    def send(req):
        seen.append(req)
        return httpx.Response(200, content=sse(mp3))

    c.app.state.volc_voice.transport = httpx.MockTransport(send)
    profiles = c.get("/api/voice/volcengine/status").json()["profiles"]
    assert {profiles[k]["speech_rate"] for k in ("cinema", "social", "lab")} == {-5, 0, 5}
    old_job = json.loads(json.dumps(p["job"]))
    first = c.post(base + "/voice/preview", json=styled(p))
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["revision"] == p["revision"] and result["job"] == old_job
    assert result["inputs_changed"] is False and result["media"] == p["media"]
    take = result["voice_takes"][0]
    assert take["scope"] == "preview" and take["params"]["speech_rate"] == 5
    payload = json.loads(seen[0].content)["req_params"]
    assert payload["text"] == old_job["script"].splitlines()[0]
    assert json.loads(payload["additions"])["context_texts"] == [profiles["social"]["direction"]]
    assert c.get(base + "/voice/takes/" + take["id"]).content == mp3
    assert c.post(base + "/voice/preview", json=styled(result)).status_code == 201
    assert len(seen) == 1
    assert (
        c.post(
            base + "/voice/takes/" + take["id"] + "/use",
            json={k: v for k, v in body(result).items() if k != "external_consent"},
        ).status_code
        == 409
    )


def test_atomic_change_voice_preserves_old_and_requires_new_preparation(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    seen = []
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: seen.append(req) or httpx.Response(200, content=sse(mp3))
    )
    r = c.post(base + "/voice/volcengine", json=styled(p, "cinema"))
    assert r.status_code == 201, r.text
    first = r.json()
    aid = next(a["id"] for a in first["media"] if a["role"] == "voice")
    active = prepare(c, first)
    old_job = active["job"]
    old_id = old_job["id"]
    assert c.post(base + "/voice/volcengine", json=styled(active, "lab")).status_code == 409
    req = {
        **styled(active, "lab"),
        "replace_voice_id": aid,
        "speaker": "zh_female_vv_uranus_bigtts",
    }
    new = c.post(base + "/voice/volcengine", json=req)
    assert new.status_code == 201, new.text
    changed = new.json()
    voices = [a for a in changed["media"] if a["role"] == "voice"]
    assert len(voices) == 1 and voices[0]["id"] != aid
    assert voices[0]["metadata"]["voice_source"]["style_id"] == "lab"
    assert voices[0]["metadata"]["voice_source"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert changed["inputs_changed"] is True
    assert c.get("/api/jobs/" + old_id).json() == old_job
    assert c.get(base + "/voice/takes/" + aid).content == mp3
    assert c.post(base + "/voice/volcengine", json=req).status_code == 409 and len(seen) == 2
    adopted = c.post(
        base + "/voice/takes/" + aid + "/use",
        json={k: v for k, v in body(changed).items() if k != "external_consent"},
    )
    assert adopted.status_code == 200, adopted.text
    restored = adopted.json()
    restored_voice = next(a for a in restored["media"] if a["role"] == "voice")
    assert restored_voice["id"] != aid
    assert restored_voice["metadata"]["voice_source"]["take_id"] == aid
    assert restored["inputs_changed"] is True
    assert len(seen) == 2


def test_bad_or_stale_profile_and_foreign_take_never_send(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    calls = []
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, content=sse(mp3))
    )
    for change in [
        {"direction_basis": "f" * 64},
        {"style_id": "unknown"},
        {"direction": "free prompt"},
        {"speech_rate": 100},
    ]:
        r = c.post(base + "/voice/preview", json={**styled(p), **change})
        assert r.status_code in (409, 422), r.text
    assert not calls
    valid = c.post(base + "/voice/volcengine", json=styled(p)).json()
    aid = valid["voice_takes"][0]["id"]
    other = approve(c, project(c, "other"))
    assert c.get(f"/api/customer-projects/{other['id']}/voice/takes/{aid}").status_code == 404
    assert (
        c.post(
            f"/api/customer-projects/{other['id']}/voice/takes/{aid}/use",
            json={k: v for k, v in body(other).items() if k != "external_consent"},
        ).status_code
        == 404
    )
    assert len(calls) == 1


def test_failed_replacement_retains_old_audio_and_take_and_hides_secret(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=sse(mp3))
    )
    p = c.post(base + "/voice/volcengine", json=styled(p)).json()
    old = p["media"][-1]
    old_sha = hashlib.sha256(c.get(base + "/assets/" + old["id"]).content).hexdigest()
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"message": "SECRET"})
    )
    r = c.post(
        base + "/voice/volcengine", json={**styled(p, "cinema"), "replace_voice_id": old["id"]}
    )
    assert r.status_code == 502 and "SECRET" not in r.text
    after = c.get(base).json()
    assert after["revision"] == p["revision"] and after["voice_takes"] == p["voice_takes"]
    assert hashlib.sha256(c.get(base + "/assets/" + old["id"]).content).hexdigest() == old_sha


@pytest.mark.parametrize("preview", [True, False])
def test_response_read_failure_never_deletes_committed_audio(tmp_path, monkeypatch, mp3, preview):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    service = c.app.state.volc_voice
    service.transport = httpx.MockTransport(lambda req: httpx.Response(200, content=sse(mp3)))
    get = service.customers.get
    calls = 0

    def fail_after_commit(pid):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("response read failed after commit")
        return get(pid)

    monkeypatch.setattr(service.customers, "get", fail_after_commit)
    with pytest.raises(RuntimeError, match="response read failed"):
        service.generate(
            p["id"],
            p["revision"],
            p["product"]["revision"],
            p["product"]["current_draft_id"],
            style_id="social",
            direction_basis=p["direction_basis"],
            preview=preview,
        )
    with service.store.connect() as db:
        rows = db.execute("SELECT path FROM voice_takes WHERE product_id=?", (p["id"],)).fetchall()
    assert len(rows) == 1
    assert (service.root / rows[0]["path"]).read_bytes() == mp3


def test_restore_shared_file_does_not_double_count_size(tmp_path, monkeypatch, mp3):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    service = c.app.state.volc_voice
    service.transport = httpx.MockTransport(lambda req: httpx.Response(200, content=sse(mp3)))
    first = c.post(base + "/voice/volcengine", json=styled(p)).json()
    a = next(a for a in first["media"] if a["role"] == "voice")
    second = c.post(
        base + "/voice/volcengine", json={**styled(first, "lab"), "replace_voice_id": a["id"]}
    ).json()
    # Model a large project whose old voice file is now also used as music.
    with service.store.transaction() as db:
        row = db.execute("SELECT * FROM voice_takes WHERE id=?", (a["id"],)).fetchone()
        db.execute(
            "INSERT INTO customer_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "shared-music",
                p["id"],
                "shared.mp3",
                row["path"],
                "audio",
                "music",
                row["sha256"],
                row["size"],
                json.dumps(a["metadata"]),
                0,
                "",
                0,
            ),
        )
        db.execute(
            "UPDATE customer_media SET size=? WHERE product_id=? AND kind='image'",
            (500 * 1024**2 - 2 * len(mp3) - 1, p["id"]),
        )
    r = c.post(
        base + "/voice/takes/" + a["id"] + "/use",
        json={k: v for k, v in body(second).items() if k != "external_consent"},
    )
    assert r.status_code == 200, r.text


def test_preview_integrity_and_budget_stop_before_provider(tmp_path, monkeypatch, mp3):
    from ecom_video import voice_takes

    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    calls = []
    service = c.app.state.volc_voice
    service.transport = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, content=sse(mp3))
    )
    result = c.post(base + "/voice/preview", json=styled(p)).json()
    tid = result["voice_takes"][0]["id"]
    with service.store.connect() as db:
        row = db.execute("SELECT path FROM voice_takes WHERE id=?", (tid,)).fetchone()
    (service.root / row["path"]).write_bytes(b"tampered")
    assert c.post(base + "/voice/preview", json=styled(result)).status_code == 409
    assert c.get(base + "/voice/takes/" + tid).status_code == 409
    monkeypatch.setattr(voice_takes, "MAX_TAKES", 1)
    assert c.post(base + "/voice/preview", json=styled(result, "lab")).status_code == 422
    monkeypatch.setattr(voice_takes, "MAX_TAKES", 40)
    monkeypatch.setattr(voice_takes, "MAX_PROJECT_BYTES", 1)
    assert c.post(base + "/voice/volcengine", json=styled(result)).status_code == 422
    assert len(calls) == 1


def test_schema_12_upgrade_preserves_prior_rows(tmp_path):
    from ecom_video.db import Store

    c = __import__("test_customer").client(tmp_path)
    p = approve(c, picture(c, project(c)))
    store = c.app.state.volc_voice.store
    with store.transaction() as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('voice_takes','schema_migrations') ORDER BY name"
            )
        ]
        before = {
            t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '" ORDER BY rowid')]
            for t in tables
        }
        # A schema12 fixture cannot retain tables from the new schema16 migration.
        db.execute("DROP TABLE operation_oauth_states")
        db.execute("DROP TABLE operation_files")
        db.execute("DROP TABLE operation_objects")
        db.execute("DROP TABLE idea_adoptions")
        db.execute("DROP TABLE idea_plans")
        db.execute("DROP TABLE idea_uploads")
        db.execute("DROP TABLE voice_patches")
        db.execute("DROP TABLE voice_takes")
        db.execute("DELETE FROM schema_migrations WHERE version>=13")
        db.execute("PRAGMA user_version=12")
    upgraded = Store(tmp_path / "workflow.db")
    with upgraded.connect() as db:
        assert (
            db.execute("PRAGMA user_version").fetchone()[0]
            == __import__("ecom_video.db", fromlist=["SCHEMA_VERSION"]).SCHEMA_VERSION
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM voice_takes").fetchone()[0] == 0
        assert before == {
            t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '" ORDER BY rowid')]
            for t in tables
        }
    assert (
        c.get("/api/customer-projects/" + p["id"]).json()["product"]["status"] == "script_confirmed"
    )


def test_uploaded_voice_survives_replacement_and_restore_without_claiming_same_script(
    tmp_path, monkeypatch, mp3
):
    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    r = c.post(
        base + "/assets",
        data={"revision": p["revision"], "role": "voice"},
        files={"file": ("customer.mp3", mp3, "audio/mpeg")},
    )
    assert r.status_code == 201, r.text
    p = r.json()
    old = next(a for a in p["media"] if a["role"] == "voice")
    service = c.app.state.volc_voice
    calls = []
    service.transport = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, content=sse(mp3))
    )
    r = c.post(base + "/voice/volcengine", json={**styled(p), "replace_voice_id": old["id"]})
    assert r.status_code == 201, r.text
    changed = r.json()
    archived = next(t for t in changed["voice_takes"] if t["id"] == old["id"])
    assert archived["params"]["provider"] == "uploaded" and archived["params"]["content_unverified"]
    assert archived["script_hash"] == ""
    restored = c.post(
        base + "/voice/takes/" + old["id"] + "/use",
        json={k: v for k, v in body(changed).items() if k != "external_consent"},
    )
    assert restored.status_code == 200, restored.text
    saved = restored.json()
    voice = next(a for a in saved["media"] if a["role"] == "voice")
    assert voice["metadata"]["voice_source"]["human_listening"] == "pending"
    assert voice["metadata"]["voice_source"]["content_unverified"] is True
    assert voice["id"] != old["id"] and len(calls) == 1
    assert c.get(base + "/assets/" + voice["id"]).content == mp3
