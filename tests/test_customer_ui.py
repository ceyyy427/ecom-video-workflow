"""Static page contracts, not browser layout or visual acceptance."""

import json
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from ecom_video.api import create_app

ROOT = Path(__file__).resolve().parents[1]


def page():
    return BeautifulSoup((ROOT / "ecom_video/web/customer.html").read_text(), "html.parser")


def test_existing_customer_controls_keep_bindings_and_manual_gates():
    soup = page()
    baseline = json.loads((ROOT / "tests/fixtures/customer-ui-dom-v1.json").read_text())
    ids = [e["id"] for e in soup.select("[id]")]
    assert len(ids) == len(set(ids)), "Duplicate IDs can silently detach business controls"
    for key, old in baseline.items():
        element = soup.find(id=key)
        assert element and element.name == old["tag"], key
        for attr, value in old["attrs"].items():
            assert element.get(attr) == value, (key, attr)
        assert [p.get("id") for p in element.parents if p.name == "fieldset"] == old["fieldsets"]
        if old["options"] is not None:
            assert [(x.get("value"), x.get_text()) for x in element.find_all("option")] == [
                tuple(x) for x in old["options"]
            ]
    for key in ("factsChecked", "scriptChecked", "voiceChecked", "filmChecked", "volcVoiceConsent"):
        assert not soup.find(id=key).has_attr("checked")


def test_workbench_has_native_navigation_and_independent_preview():
    soup = page()
    sidebar = soup.select_one(".customer-sidebar")
    assert sidebar is not None, "The new workbench shell is missing"
    assert {a.get("href") for a in sidebar.select("a")} >= {
        "/create",
        "/samples",
        "/distribution",
        "/experiments",
        "/guide",
        "/setup",
        "/maintenance",
    }
    assert soup.select_one('.skip-link[href="#workspaceMain"]')
    assert soup.select_one('nav[aria-label="制作步骤"]')
    for index in range(1, 5):
        target = soup.find(id=f"step{index}")
        assert target and target.find_parent(id="work")
        assert soup.select_one(f'a[href="#step{index}"]')
    preview = soup.find(id="workspacePreview")
    assert preview and preview.name == "video" and preview.has_attr("controls")
    assert preview.find_parent("fieldset") is None, "Preview must remain usable during work lock"
    assert not preview.has_attr("src") and not preview.has_attr("autoplay")
    assert soup.find(id="workspaceEmpty") and soup.find(id="workspaceNext")


def test_create_static_assets_are_local_and_served_without_business_writes(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        response = client.get("/create")
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        scripts = [x["src"] for x in soup.select("script[src]")]
        assert "/static/customer-workspace.js" in scripts
        for url in scripts:
            assert url.startswith("/static/")
            assert client.get(url).status_code == 200
        assert client.get("/api/customer-projects").json() == []
