from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ecom_video.api import create_app
from ecom_video.worker import Worker


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        yield c


def create(client, script="展示产品外观"):
    r = client.post("/api/jobs", json={"title": "新品视频", "script": script, "seconds": 1})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, jid):
    f = BytesIO()
    Image.new("RGB", (300, 400), "#88aacc").save(f, format="PNG")
    r = client.post(
        f"/api/jobs/{jid}/assets",
        data={"kind": "image"},
        files={"file": ("../../恶意.png", f.getvalue(), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_origin_token_host_and_input_validation(client):
    assert client.post("/api/jobs", json={}).status_code == 422
    assert (
        client.post("/api/jobs", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/session", headers={"Host": "evil.example"}).status_code == 400
    token = client.headers.pop("X-Workflow-Token")
    assert client.post("/api/jobs", json={}).status_code == 403
    client.headers["X-Workflow-Token"] = token
    assert (
        client.post("/api/jobs", json={"title": "x", "script": "x" * 101, "seconds": 1}).status_code
        == 422
    )


def test_upload_lock_idempotency_and_clone(client):
    jid = create(client)
    assert client.post(f"/api/jobs/{jid}/submit").status_code == 409
    j = upload(client, jid)
    assert ".." not in j["assets"][0]["path"]
    bad = client.post(
        f"/api/jobs/{jid}/assets",
        data={"kind": "image"},
        files={"file": ("fake.png", b"bad", "image/png")},
    )
    assert bad.status_code == 422
    for _ in range(2):
        assert client.post(f"/api/jobs/{jid}/submit").json()["status"] == "queued"
    assert (
        client.put(
            f"/api/jobs/{jid}", json={"title": "x", "script": "改脚本", "seconds": 2}
        ).status_code
        == 409
    )
    assert client.delete(f"/api/jobs/{jid}/assets/{j['assets'][0]['id']}").status_code == 409
    assert (
        client.post(
            f"/api/jobs/{jid}/review",
            json={"decision": "ready", "reviewer": "a", "note": "b", "confirmed": True},
        ).status_code
        == 409
    )
    cloned = client.post(f"/api/jobs/{jid}/clone").json()
    assert cloned["status"] == "draft" and cloned["id"] != jid
    assert len(cloned["assets"]) == 1
    assert client.get(f"/api/jobs/{jid}/artifacts/video").status_code == 404
    assert client.post(f"/api/jobs/{jid}/cancel").json()["status"] == "cancelled"


def test_http_blocked_report_is_downloadable(client, tmp_path):
    jid = create(client, "根治疾病")
    upload(client, jid)
    client.post(f"/api/jobs/{jid}/submit")
    Worker(tmp_path).run_once()
    result = client.get(f"/api/jobs/{jid}").json()
    assert result["status"] == "blocked"
    r = client.get(f"/api/jobs/{jid}/artifacts/audit")
    assert r.status_code == 200 and r.json()["status"] == "blocked"
    assert (
        client.post(
            f"/api/jobs/{jid}/review",
            json={"decision": "ready", "reviewer": "a", "note": "b", "confirmed": True},
        ).status_code
        == 409
    )


def test_serve_workbench(client):
    assert client.get("/").status_code == 200
    assert "脚本" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
