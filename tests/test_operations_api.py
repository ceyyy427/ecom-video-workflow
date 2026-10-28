from test_customer import client
from test_operations_content import request_body


def test_suite_page_and_plan_listing_keep_original_routes_and_secret_errors_safe(tmp_path):
    c = client(tmp_path)
    assert c.get("/operations").status_code == 200
    created = c.post("/api/operations/plans", json=request_body()).json()
    response = c.get("/api/operations/plans")
    assert response.status_code == 200
    assert response.json()[0]["id"] == created["id"]
    bad = c.post(
        "/api/operations/connectors/douyin/config",
        json={"client_secret": "DO_NOT_LEAK", "callback": "bad"},
    )
    assert bad.status_code == 422 and "DO_NOT_LEAK" not in bad.text
    assert c.get("/ideas").status_code == 200 and c.get("/create").status_code == 200


def test_independent_module_disable_retains_history_and_old_workbench(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("ECOM_DOMESTIC_HANDOFF", "0")
    r = c.post("/api/operations/publication-packs", json={})
    assert r.status_code == 403
    assert c.get("/api/operations/objects?kind=publication_pack").json() == []
    assert c.get("/create").status_code == 200
