import copy

from test_customer import approve, client, picture, plan, prepare, project


def test_context_prompt_adapts_to_product_and_is_read_only(tmp_path):
    c = client(tmp_path / "runtime")
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    base = f"/api/customer-projects/{p['id']}"
    before = copy.deepcopy(c.get(base).json())
    r = c.get(
        base + "/prompt-adaptation",
        params={
            "card_id": "text-as-mask",
            "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["project_id"] == p["id"] and d["job_id"] == p["job"]["id"]
    assert d["text"] in p["job"]["script"]
    assert "客户杯子" in d["adapted_prompt"]
    assert {x["id"] for x in d["choices"]} == {"type-mask-clean-v1", "type-mask-bold-v1"}
    assert all(x["recipe"] == "product-type-mask" for x in d["choices"])
    assert not d["ready"]  # deliberately tiny 160px fixture must not claim render readiness
    assert c.get(base).json() == before
    assert (
        c.get(
            base + "/prompt-adaptation", params={"card_id": "text-as-mask", "shot_id": "wrong"}
        ).status_code
        == 409
    )
    assert c.get(base + "/prompt-adaptation", params={"card_id": "not-a-card"}).status_code == 404
    ref = c.get(base + "/prompt-adaptation", params={"card_id": "before-after-slider-scrub"}).json()
    assert ref["choices"] == [] and not ref["ready"]


def test_no_confirmed_job_still_allows_research_but_not_application(tmp_path):
    c = client(tmp_path / "runtime")
    p = project(c, "藏蓝外套")
    d = c.get(
        f"/api/customer-projects/{p['id']}/prompt-adaptation",
        params={"card_id": "crash-zoom-punch"},
    ).json()
    assert not d["ready"] and d["job_id"] is None
    assert "藏蓝外套" in d["adapted_prompt"]
    assert d["blockers"]


def test_workbench_loads_choice_bridge_before_main_controller():
    from pathlib import Path

    from bs4 import BeautifulSoup

    page = BeautifulSoup(Path("ecom_video/web/customer.html").read_text(), "html.parser")
    scripts = [s.get("src") for s in page.find_all("script")]
    assert scripts.index("/static/customer-prompt-choice.js") < scripts.index("/static/customer.js")
