from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from ecom_video.api import create_app

pytest_plugins = ["test_qianchuan_tasks"]


def client_for(service):
    app = create_app(service.root)
    app.state.qianchuan = service
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    client.headers["x-workflow-token"] = client.get("/api/session").json()["token"]
    return client


def test_callback_only_cross_site_exception_and_no_secret_output(native):
    service, task, _ = native
    client = client_for(service)
    aid = task["account_id"]
    result = client.post(f"/api/qianchuan/accounts/{aid}/authorize")
    assert result.status_code == 200
    state = parse_qs(urlparse(result.json()["url"]).query)["state"][0]
    response = client.get(
        "/api/qianchuan/oauth/callback",
        params={"state": state, "auth_code": "private-code"},
        headers={"sec-fetch-site": "cross-site"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "private-code" not in response.text + str(response.headers)
    assert (
        client.get(
            "/api/qianchuan/oauth/callback",
            params={"state": state, "auth_code": "private-code"},
            headers={"sec-fetch-site": "cross-site"},
        ).status_code
        == 409
    )
    assert client.get("/api/session", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.get("/api/qianchuan/accounts/" + aid).json()["status"] == "authorized"


def test_native_api_guards_and_background_queue(native):
    service, task, provider = native
    client = client_for(service)
    response = client.post(
        f"/api/qianchuan/tasks/{task['id']}/upload",
        json={"reviewer": "人", "note": "同意", "confirmed": False},
    )
    assert response.status_code == 422 and provider.uploads == 0
    assert client.get("/qianchuan").status_code == 200
    client.headers.pop("x-workflow-token")
    assert client.post(f"/api/qianchuan/tasks/{task['id']}/cancel").status_code == 403
