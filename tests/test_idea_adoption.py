import pytest


def prepared(tmp_path, previews=False, materials=None):
    from ecom_video.content_plan import ContentBrief
    from ecom_video.db import Store
    from ecom_video.idea_plans import IdeaPlans

    store = Store(tmp_path / "workflow.db")
    plans = IdeaPlans(tmp_path, store)
    p = plans.create(
        ContentBrief(
            idea="解释一件藏蓝外套的细节",
            subject="藏蓝软壳衣",
            facts=[{"text": "有拉链口袋", "source": "用户资料"}],
        ),
        materials or [],
    )
    # Only engineering setup: no actual render or customer approval is claimed.
    with store.transaction() as c:
        c.execute("UPDATE idea_plans SET status='ready' WHERE id=?", (p["id"],))
    if previews:
        from ecom_video.media import digest
        from ecom_video.products import encoded

        marker = tmp_path / "engineering-preview-fixture.mp4"
        marker.write_bytes(b"boundary fixture, not an actual rendered customer preview")
        item = {
            "video": {"path": marker.name, "sha256": digest(marker)},
            "poster": {"path": marker.name, "sha256": digest(marker)},
        }
        with store.transaction() as c:
            c.execute(
                "UPDATE idea_plans SET previews=? WHERE id=?",
                (encoded({o["id"]: item for o in p["plan"]["options"]}), p["id"]),
            )
    return store, plans.get(p["id"])


def test_adoption_is_idempotent_pending_and_preserves_source_plan(tmp_path):
    from ecom_video.customer import Customers
    from ecom_video.db import Conflict
    from ecom_video.idea_adoption import adopt, apply_script, selected_plan

    store, p = prepared(tmp_path, previews=True)
    project = adopt(tmp_path, store, p["id"], p["basis"], p["plan"]["options"][0]["id"])
    assert (
        adopt(tmp_path, store, p["id"], p["basis"], p["plan"]["options"][0]["id"])["id"]
        == project["id"]
    )
    assert project["product"]["current_review_id"] is None
    assert project["product"]["script_approvals"] == [] and project["job"] is None
    assert len(project["media"]) == 4 and all(
        a["metadata"]["code_visual"]["schematic"] for a in project["media"]
    )
    assert selected_plan(store, project["id"])["basis"] == p["basis"]
    with pytest.raises(Conflict):
        apply_script(store, project["id"], p["basis"], project["product"]["revision"])
    facts = project["product"]["facts"]
    products = Customers(tmp_path, store).products
    product = products.confirm_facts(
        project["id"],
        project["product"]["revision"],
        [f["id"] for f in facts],
        "工程夹具",
        "仅测试确认门禁，不是客户审批",
    )
    draft = apply_script(store, project["id"], p["basis"], product["revision"])
    current = next(d for d in draft["script_drafts"] if d["id"] == draft["current_draft_id"])
    assert "\n".join(s["text"] for s in current["payload"]) == p["plan"]["options"][0]["script"]
    assert draft["script_approvals"] == []


def test_stale_basis_and_missing_actual_previews_cannot_create_project(tmp_path):
    from ecom_video.db import Conflict
    from ecom_video.idea_adoption import adopt

    store, p = prepared(tmp_path)
    with pytest.raises(Conflict):
        adopt(tmp_path, store, p["id"], "a" * 64, "swiss-motion")
    with pytest.raises(Conflict):
        adopt(tmp_path, store, p["id"], p["basis"], "swiss-motion")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM customer_projects").fetchone()[0] == 0


def test_omitting_optional_audience_and_tone_keeps_the_chosen_direction_available():
    from ecom_video.content_plan import ContentBrief, build_plan
    from ecom_video.creative import recommend

    p = build_plan(ContentBrief(idea="展示一个文具的结构"), [])
    option = next(o for o in p["options"] if o["id"] == "swiss-motion")
    result = recommend(
        {
            "title": "文具",
            "script": option["script"],
            "assets": [],
            "provenance": {
                "idea_plan": {"basis": p["basis"], "option_id": option["id"], "option": option}
            },
        },
        {"format": "showcase", "category": "", "audience": "", "tone": ""},
    )
    assert "kinetic" in {o["id"] for o in result["options"]}


def test_new_project_keeps_identity_source_but_requires_its_own_confirmation(tmp_path):
    from PIL import Image

    from ecom_video.delivery_plan import identity_matches
    from ecom_video.idea_adoption import adopt
    from ecom_video.media import digest

    source = tmp_path / "declared.png"
    Image.new("RGB", (80, 100), "navy").save(source)
    identity = {
        "sku": "工程同款",
        "color": "藏蓝",
        "reviewer": "旧项目工程标记",
        "confirmed": True,
        "source_sha256": digest(source),
    }
    asset = {
        "id": "original",
        "name": source.name,
        "kind": "image",
        "path": source.name,
        "sha256": digest(source),
        "size": source.stat().st_size,
        "source_in": 0,
        "metadata": {"identity": identity},
    }
    store, p = prepared(tmp_path, previews=True, materials=[asset])
    project = adopt(tmp_path, store, p["id"], p["basis"], p["plan"]["options"][0]["id"])
    item = project["media"][0]
    assert "identity" not in item["metadata"]
    assert item["metadata"]["identity_reference"]["reviewer"] == "旧项目工程标记"
    assert not identity_matches(item, {"sku": "工程同款", "color": "藏蓝"})
    assert project["product"]["fact_reviews"] == []
