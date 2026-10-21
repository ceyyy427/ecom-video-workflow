"""Remaining workflow page shell/DOM invariants. No browser, model or production-data writes."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from ecom_video.api import create_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ecom_video/web"
CONTRACT = json.loads((ROOT / "tests/fixtures/workflow-pages-dom-v1.json").read_text())
PAGES = [
    ("experiments.html", "/experiments"),
    ("guide.html", "/guide"),
    ("index.html", "/"),
    ("studio.html", "/studio"),
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
    expected_scripts = old["scripts"] + (
        ["/static/workbench-navigation.js"] if name == "index.html" else []
    )
    assert [e["src"] for e in soup.select("script[src]")] == expected_scripts


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
        hidden_ancestors = [p for p in target.parents if p.has_attr("hidden")]
        assert all(p in nav.parents for p in hidden_ancestors), (
            "Navigation must share its target feature gate"
        )
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


def test_storyboard_keeps_task_list_separate_from_global_navigation_and_review_gate():
    soup = BeautifulSoup((WEB / "index.html").read_text(), "html.parser")
    assert soup.find(id="jobs").find_parent(class_="task-sidebar")
    assert not soup.find(id="jobs").find_parent(class_="customer-sidebar")
    assert soup.find(id="newJob").find_parent(class_="task-sidebar")
    assert soup.find(id="reviewForm").has_attr("hidden")
    assert soup.select_one("a[data-task-studio-link][data-task-required][hidden]")
    assert soup.select_one('script[src="/static/workbench-navigation.js"][defer]')


def test_guide_has_actionable_routes_and_studio_keeps_same_job_return_controls():
    guide = BeautifulSoup((WEB / "guide.html").read_text(), "html.parser")
    routes = guide.find(id="guideRoutes")
    assert routes is not None, "A clear workflow entry and return map is missing"
    assert {a["href"] for a in routes.select("a[href]")} >= {
        "/create",
        "/",
        "/studio",
        "/distribution",
        "/experiments",
        "/setup",
        "/maintenance",
    }
    studio = BeautifulSoup((WEB / "studio.html").read_text(), "html.parser")
    assert studio.find(id="editor").has_attr("disabled")
    assert studio.find(id="confirmation").has_attr("hidden")
    for key in ["jobLink", "renderLink"]:
        assert studio.find(id=key)["href"] == "/"
    assert not studio.find(id="jobLink").find_parent("fieldset")
