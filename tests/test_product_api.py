from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from ecom_video.api import create_app
from ecom_video.worker import Worker


def setup(client):
    client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
    p = client.post("/api/products", json={"title": "随行杯"}).json()
    base = "/api/products/" + p["id"]
    r = client.post(
        base + "/documents",
        data={"revision": p["revision"]},
        files={
            "file": (
                "产品.txt",
                "产品名称：随行杯\n容量：500mL\n材质：不锈钢".encode(),
                "text/plain",
            )
        },
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert (
        client.post(base + "/scripts/generate", json={"revision": p["revision"]}).status_code == 409
    )
    r = client.post(
        base + "/facts/confirm",
        json={
            "revision": p["revision"],
            "fact_ids": [f["id"] for f in p["facts"]],
            "reviewer": "产品负责人",
            "note": "逐项核对规格",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert (
        client.post(
            base + "/scripts/generate", json={"revision": p["revision"], "mode": "model"}
        ).status_code
        == 422
    )
    p = client.post(base + "/scripts/generate", json={"revision": p["revision"]}).json()
    r = client.post(
        base + "/scripts/confirm",
        json={
            "revision": p["revision"],
            "draft_id": p["current_draft_id"],
            "reviewer": "编辑",
            "note": "逐镜检查与原资料一致",
            "confirmed": True,
            "seconds": 1,
        },
    )
    assert r.status_code == 201, r.text
    return p, r.json()


def test_document_to_render_provenance_and_clone(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        p, job = setup(client)
        jid = job["id"]
        source = p["sources"][0]
        r = client.get(f"/api/products/{p['id']}/sources/{source['id']}")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        image = BytesIO()
        Image.new("RGB", (120, 200), "#415966").save(image, format="PNG")
        assert (
            client.post(
                f"/api/jobs/{jid}/assets",
                data={"kind": "image"},
                files={"file": ("杯.png", image.getvalue(), "image/png")},
            ).status_code
            == 201
        )
        assert client.post(f"/api/jobs/{jid}/submit").status_code == 200
        Worker(tmp_path).run_once()
        result = client.get(f"/api/jobs/{jid}").json()
        assert result["status"] == "needs_review", result["error"]
        provenance = client.get(f"/api/jobs/{jid}/artifacts/provenance").json()
        assert provenance["script_approval"]["script_hash"] == result["script_hash"]
        assert provenance["facts"][1]["text"] == "容量：500mL"
        assert result["audit"]["provenance"]["source_integrity"] == "verified"
        manifest = client.get(f"/api/jobs/{jid}/artifacts/manifest").json()
        assert manifest["provenance"] == provenance
        clone = client.post(f"/api/jobs/{jid}/clone").json()
        assert clone["provenance"] == job["provenance"]
        assert (
            client.put(
                "/api/jobs/" + clone["id"],
                json={"title": "随行杯", "script": "无依据脚本", "seconds": 1},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/jobs/{jid}/review",
                json={
                    "decision": "ready",
                    "reviewer": "验收人",
                    "note": "已核对",
                    "confirmed": True,
                },
            ).json()["status"]
            == "ready"
        )


def test_tampered_source_blocks_confirmation(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        p, job = setup(client)
        (tmp_path / p["sources"][0]["path"]).write_text("篡改", encoding="utf-8")
        response = client.post(
            "/api/products/" + p["id"] + "/facts/confirm",
            json={
                "revision": p["revision"] + 1,
                "fact_ids": [p["facts"][0]["id"]],
                "reviewer": "编辑",
                "note": "检查",
                "confirmed": True,
            },
        )
        assert response.status_code == 409
        assert "变化" in response.json()["detail"]


def test_link_intake_contract_preserves_snapshot_and_locator(tmp_path, monkeypatch):
    from pathlib import Path

    from ecom_video import product_api
    from ecom_video.sources import parse_html

    html = b'<html><head><title>Fixture cup</title><script type="application/ld+json">{"@type":"Product","name":"Fixture cup","material":"Steel"}</script></head><body><p>Capacity: 500mL. Fixture page only.</p></body></html>'

    def fixture_process(payload, **kwargs):
        assert payload["operation"] == "url"
        Path(payload["path"]).write_bytes(html)
        return {**parse_html(html), "final_url": "https://product.example/cup"}

    monkeypatch.setattr(product_api, "isolated", fixture_process)
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
        p = client.post("/api/products", json={"title": "Fixture cup"}).json()
        response = client.post(
            "/api/products/" + p["id"] + "/links",
            json={"revision": p["revision"], "url": "https://product.example/start"},
        )
        assert response.status_code == 201, response.text
        p = response.json()
        source = p["sources"][0]
        assert source["original_url"] == "https://product.example/start"
        assert source["final_url"] == "https://product.example/cup"
        assert any(f["locator"] == "JSON-LD 1/material" for f in p["facts"])
        download = client.get("/api/products/" + p["id"] + "/sources/" + source["id"])
        assert download.content == html
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["content-type"] == "application/octet-stream"


def test_failed_link_leaves_no_source_and_oversize_upload_rejected(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
        p = client.post("/api/products", json={"title": "Fixture"}).json()
        base = "/api/products/" + p["id"]
        response = client.post(
            base + "/links", json={"revision": p["revision"], "url": "https://127.0.0.1"}
        )
        assert response.status_code == 422
        assert client.get(base).json()["sources"] == []
        assert not list((tmp_path / "products").rglob("*.html"))
        response = client.post(
            base + "/documents",
            data={"revision": p["revision"]},
            files={"file": ("big.txt", b"a" * (11 * 1024 * 1024), "text/plain")},
        )
        assert response.status_code == 413
