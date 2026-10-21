from fastapi.testclient import TestClient

from ecom_video.api import create_app
from ecom_video.platform_worker import tick


def test_report_api_boundaries_and_async_failure(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as c:
        assert c.get("/distribution").status_code == 200
        assert c.post("/api/distribution/accounts", json={}).status_code == 403
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        r = c.post(
            "/api/distribution/accounts",
            json={"name": "千川", "platform": "qianchuan", "advertiser_id": "1234567890123456789"},
        )
        assert r.status_code == 201
        aid = r.json()["id"]
        bad = c.post(
            "/api/distribution/accounts",
            json={"name": "x", "platform": "qianchuan", "advertiser_id": 123},
        )
        assert bad.status_code == 422
        data = {
            "account_id": aid,
            "start_date": "2026-10-01",
            "end_date": "2026-10-01",
            "actor": "测试员",
            "confirmed": "true",
        }
        raw = b"date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n2026-10-01,999,100,1000,20,3,300,500,100\n"
        r = c.post("/api/reports/import", data=data, files={"file": ("x.csv", raw, "text/csv")})
        assert r.status_code == 201, r.text
        bid = r.json()["id"]
        assert c.get(f"/api/reports/batches/{bid}/source").content == raw
        query = {k: v for k, v in data.items() if k in ("account_id", "start_date", "end_date")}
        d = c.get("/api/reports/dashboard", params=query).json()
        assert d["ratios"]["payment_roi"] == "3"
        assert (
            "attachment"
            in c.get("/api/reports/export", params=query).headers["content-disposition"]
        )
        r = c.post("/api/reports/syncs", json={**query, "actor": "测试员"})
        assert r.status_code == 201
        assert tick(tmp_path, c.app.state.store)
        sync = c.get("/api/reports/syncs", params={"account_id": aid}).json()[0]
        assert sync["status"] == "failed" and sync["batch_id"] is None
        assert len(c.get("/api/reports/batches", params={"account_id": aid}).json()) == 1
        assert c.get("/api/distribution/capabilities").json()["platform_write"] is False
