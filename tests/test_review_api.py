import json

from fastapi.testclient import TestClient
from test_review_snapshots import command, ingest

from ecom_video.api import create_app
from ecom_video.distribution import Distribution
from ecom_video.reporting import Reporting


def client(root):
    c = TestClient(create_app(root), base_url="http://localhost")
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    return c


def test_default_disabled_catalog_and_no_snapshot_dispatch(tmp_path, monkeypatch):
    monkeypatch.delenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", raising=False)
    c = client(tmp_path)
    cap = c.get("/api/reviews/capabilities")
    assert cap.status_code == 200 and cap.json()["enabled"] is False
    assert c.post("/api/reviews/snapshots", json={}).status_code == 404
    with c.app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 0


def test_api_capture_export_sources_and_fresh_app_read(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    c = client(tmp_path)
    aid = Distribution(tmp_path, c.app.state.store).add_account("fixture", "qianchuan", "123")["id"]
    batch = ingest(
        Reporting(tmp_path, c.app.state.store), aid, "2026-10-01,123,10,100,5,1,20,50,10\n"
    )
    r = c.post("/api/reviews/snapshots", json=command(aid, end="2026-10-01"))
    assert r.status_code == 201, r.text
    frozen = r.json()
    rid = frozen["review_id"]
    base = "/api/reviews/snapshots/" + rid
    assert c.get(base).json() == frozen
    exported = c.get(base + "/export")
    assert exported.status_code == 200
    assert exported.headers["etag"].strip('"') == frozen["snapshot_hash"]
    assert json.loads(exported.content) == frozen
    assert c.get(base + "/verify").json()["snapshot_hash_valid"]
    source = c.get(base + "/sources/" + batch["id"])
    assert source.content == (tmp_path / batch["path"]).read_bytes()
    fresh = client(tmp_path)
    assert fresh.get(base + "/export").content == exported.content
    assert (
        fresh.get("/api/reviews/snapshots", params={"account_id": aid}).json()[0]["review_id"]
        == rid
    )
    # Membership, not a caller-provided source path.
    assert c.get(base + "/sources/" + "0" * 32).status_code == 404


def test_strict_safe_inputs_and_existing_transport_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    c = client(tmp_path)
    aid = Distribution(tmp_path, c.app.state.store).add_account("fixture", "qianchuan", "123")["id"]
    for change in [
        {"token": "do-not-echo-fixture-secret"},
        {"start_date": "2026-10-01T00:00:00"},
        {"account_id": True},
        {"request_id": 1},
        {"actor": "\n"},
    ]:
        r = c.post("/api/reviews/snapshots", json={**command(aid), **change})
        assert r.status_code == 422 and "do-not-echo-fixture-secret" not in r.text
    assert (
        c.post(
            "/api/reviews/snapshots", content=b"{", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/reviews/snapshots", json=command(aid), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/reviews/snapshots", json=command(aid), headers={"X-Workflow-Token": "invalid"}
        ).status_code
        == 403
    )
    assert c.get("/api/reviews/capabilities", headers={"Host": "evil.example"}).status_code == 400
    with c.app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM review_snapshots").fetchone()[0] == 0


def test_label_api_keeps_model_unverified_and_requires_human_confirmation(tmp_path, monkeypatch):
    from test_creative_features import label, ready

    monkeypatch.setenv("ECOM_REVIEW_SNAPSHOTS_ENABLED", "1")
    c = client(tmp_path)
    aid = Distribution(tmp_path, c.app.state.store).add_account("fixture", "qianchuan", "123")["id"]
    jid, _, _ = ready(tmp_path, c.app.state.store)
    Reporting(tmp_path, c.app.state.store).bind(aid, "123", jid, "fixture")
    frozen = c.post("/api/reviews/snapshots", json=command(aid, end="2026-10-01")).json()
    fid = frozen["snapshot"]["materials"][0]["creative_feature"]["feature_id"]
    base = "/api/creative-features/" + fid
    r = c.post(base + "/labels", json={**label(fid), "confirmed": False})
    assert r.status_code == 422
    r = c.post(base + "/labels", json=label(fid, "model", "model-001"))
    assert r.status_code == 201, r.text
    assert r.json()["verified"] is False
    assert c.get(base).json()["labels"]["human"] == []
    assert len(c.get(base).json()["labels"]["model"]) == 1
    assert (
        c.post("/api/reviews/snapshots/" + frozen["review_id"] + "/apply", json={}).status_code
        == 404
    )
