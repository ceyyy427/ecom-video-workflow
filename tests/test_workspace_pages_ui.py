"""Four-page shell/DOM invariants. No browser, model or production-data writes."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from ecom_video.api import create_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ecom_video/web"
CONTRACT = json.loads((ROOT / "tests/fixtures/workspace-pages-dom-v1.json").read_text())
PAGES = [
    ("samples.html", "/samples"),
    ("distribution.html", "/distribution"),
    ("setup.html", "/setup"),
    ("recovery.html", "/maintenance"),
]


@pytest.mark.parametrize("name,route", PAGES)
def test_existing_bindings_forms_consents_and_deep_links_are_preserved(name, route):
    soup = BeautifulSoup((WEB / name).read_text(), "html.parser")
    old = CONTRACT[name]
    ids = [e["id"] for e in soup.select("[id]")]
    assert len(ids) == len(set(ids))
    for key, entry in old["ids"].items():
        element = soup.find(id=key)
        assert element and element.name == entry["tag"], (name, key)
        for attr, value in entry["attrs"].items():
            assert element.get(attr) == value, (name, key, attr)
        parents = [
            (p.name, p.get("id"), p.get("method"))
            for p in element.parents
            if p.name in ("form", "fieldset", "dialog")
        ]
        assert parents == [tuple(p) for p in entry["parents"]], (name, key)
        if entry["options"] is not None:
            assert [(o.get("value"), o.get_text()) for o in element.find_all("option")] == [
                tuple(o) for o in entry["options"]
            ]
    forms = soup.find_all("form")
    assert len(forms) == len(old["forms"])
    for form, entry in zip(forms, old["forms"], strict=True):
        for attr, value in entry["attrs"].items():
            assert form.get(attr) == value
        controls = [
            (
                c.name,
                {k: v for k, v in c.attrs.items() if k != "class"},
                c.get_text() if c.name == "button" else "",
            )
            for c in form.find_all(["input", "select", "textarea", "button"])
        ]
        assert controls == [(tag, attrs, text) for tag, attrs, text in entry["controls"]]
    for box in soup.select('input[type="checkbox"]'):
        assert not box.has_attr("checked"), "Never pre-approve an operation or rights statement"
    assert set(old["links"]) <= {a["href"] for a in soup.select("a[href]")}
    assert [e["src"] for e in soup.select("script[src]")] == old["scripts"]


@pytest.mark.parametrize("name,route", PAGES)
def test_same_native_shell_and_page_index_have_accessible_real_targets(name, route):
    soup = BeautifulSoup((WEB / name).read_text(), "html.parser")
    sidebar = soup.select_one(".customer-sidebar")
    assert sidebar, "Unified page navigation is missing"
    assert soup.select_one('.skip-link[href="#workspaceMain"]')
    assert soup.select_one('main#workspaceMain[tabindex="-1"]')
    selected = sidebar.select('a[aria-current="page"]')
    assert len(selected) == 1 and selected[0]["href"] == route
    assert {a["href"] for a in sidebar.select("a[href]")} >= {
        "/create",
        "/samples",
        "/distribution",
        "/experiments",
        "/setup",
        "/maintenance",
        "/guide",
    }
    nav = soup.select_one('nav[aria-label="本页导航"]')
    assert nav
    for link in nav.select("a[href]"):
        target = soup.find(id=link["href"][1:])
        assert target and not target.has_attr("hidden")
        assert not any(p.name == "details" and not p.has_attr("open") for p in target.parents)
    styles = [e["href"] for e in soup.select('link[rel="stylesheet"]')]
    assert styles[-2:] == ["/static/customer.css", "/static/workspace-pages.css"]
    assert not soup.select("button[autofocus],video[autoplay],audio[autoplay]")


@pytest.mark.parametrize("name,route", PAGES)
def test_new_styles_and_pages_are_served_using_temporary_app(name, route, tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        response = client.get(route)
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        assert soup.select_one(".workspace-page")
        for resource in soup.select('link[rel="stylesheet"],script[src]'):
            url = resource.get("href") or resource["src"]
            assert url.startswith("/static/")
            assert client.get(url).status_code == 200
        assert client.get("/api/customer-projects").json() == []


def test_sample_hash_targets_remain_directly_available_without_expanding_history():
    soup = BeautifulSoup((WEB / "samples.html").read_text(), "html.parser")
    for key in CONTRACT["samples.html"]["ids"]:
        element = soup.find(id=key)
        if key == "sampleGallery":  # Deliberately closed legacy AI-image experiments.
            continue
        assert not any(p.name == "details" and not p.has_attr("open") for p in element.parents)


def test_report_notice_and_index_share_one_sticky_region_instead_of_overlapping():
    soup = BeautifulSoup((WEB / "distribution.html").read_text(), "html.parser")
    notice = soup.find(id="notice")
    region = notice.find_parent(class_="workspace-navigation")
    assert region is not None, "Dynamic notices must not cover the report navigation"
    assert region.select_one('nav[aria-label="本页导航"]')
