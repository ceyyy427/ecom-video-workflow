import json

from test_experiments import action
from test_experiments import env as env


def test_capability_default_off_and_transport_boundary(env, monkeypatch):
    _, body, c, _ = env
    monkeypatch.delenv("ECOM_EXPERIMENTS_ENABLED")
    cap = c.get("/api/experiments/capabilities")
    assert cap.status_code == 200 and cap.json()["enabled"] is False
    assert c.post("/api/experiments", json=body).status_code == 404
    monkeypatch.setenv("ECOM_EXPERIMENTS_ENABLED", "1")
    assert (
        c.post(
            "/api/experiments", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        c.post("/api/experiments", json=body, headers={"X-Workflow-Token": "bad"}).status_code
        == 403
    )
    assert (
        c.get("/api/experiments/capabilities", headers={"Host": "evil.example"}).status_code == 400
    )


def test_api_create_select_apply_and_versioned_export(env):
    service, body, c, _ = env
    r = c.post("/api/experiments", json=body)
    assert r.status_code == 201, r.text
    e = r.json()
    base = "/api/experiments/" + e["id"]
    assert c.get(base).json() == e
    assert (
        c.get("/api/experiments", params={"review_id": body["review_id"]}).json()[0]["id"]
        == e["id"]
    )
    ctx = c.get(
        "/api/experiments/context", params={"review_id": body["review_id"], "material_id": "123"}
    )
    assert ctx.status_code == 200 and ctx.json()["parent_job_id"] == body["parent_job_id"]
    e = c.post(
        base + "/select",
        json=action(e, "api-select", decision="selected", confirmed=True, note="fixture"),
    ).json()
    e = c.post(base + "/apply", json=action(e, "api-apply")).json()
    assert e["result_job_id"] and service.store.get(e["result_job_id"])["status"] == "draft"
    production = c.get(base + "/production").json()
    assert production["job_id"] == e["result_job_id"] and production["style_confirm_needed"]
    exported = c.get(base + "/export")
    assert exported.status_code == 200 and json.loads(exported.content) == c.get(base).json()
    assert c.get("/experiments").status_code == 200


def test_strict_inputs_and_safe_errors(env):
    _, body, c, _ = env
    for patch in [
        {"token": "secret-fixture-never-echo"},
        {"actor": True},
        {"comparison_policy": {"min_reported_days": True, "min_impressions": 0}},
        {"change_set": {"kind": "shell", "command": "never-execute"}},
    ]:
        r = c.post("/api/experiments", json={**body, **patch})
        assert r.status_code == 422 and "secret-fixture-never-echo" not in r.text
    r = c.post("/api/experiments", content=b"{", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_csv_window_declaration_requires_confirmation_and_never_rewrites_old_batch(env):
    service, _, c, review = env
    aid = review["snapshot"]["account"]["id"]
    source = review["snapshot"]["batches"][0]["id"]
    raw = c.get("/api/reviews/snapshots/" + review["review_id"] + "/sources/" + source).content

    def upload(confirmed):
        return c.post(
            "/api/reports/import",
            data={
                "account_id": aid,
                "start_date": "2026-10-01",
                "end_date": "2026-10-01",
                "actor": "fixture",
                "confirmed": "true",
                "attribution_window": "7d_click",
                "context_confirmed": str(confirmed).lower(),
            },
            files={"file": ("fixture.csv", raw, "text/csv")},
        )

    assert upload(False).status_code == 422
    r = upload(True)
    assert r.status_code == 201 and r.json()["id"] != source
    assert json.loads(r.json()["metadata"])["attribution_window"] == "7d_click"
    assert service.reviews.get(review["review_id"]) == review
