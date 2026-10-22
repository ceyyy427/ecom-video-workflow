"""Proposals remain suggestions, preserve facts, and expire on material changes."""

import copy

from ecom_video.script_alternatives import alternatives


def product():
    facts = [{"id": "f1", "text": "黑色耳罩。"}, {"id": "f2", "text": "耳罩向内折叠。"}]
    return {"title": "黑色耳机", "revision": 1, "current_review_id": "r1"}, facts


def image():
    return {
        "id": "a",
        "name": "客户图片.png",
        "kind": "image",
        "sha256": "a" * 64,
        "metadata": {"width": 1080, "height": 1920, "customer_role": "product"},
    }


def test_three_joint_proposals_keep_unknowns_and_no_video_warning():
    p, facts = product()
    out = alternatives(
        p, facts, {"format": "narrated", "audience": "学生", "tone": "活泼"}, assets=[image()]
    )
    assert len({c["direction"]["family"] for c in out["candidates"]}) == 3
    for c in out["candidates"]:
        assert c["direction"]["voice"]["speaker"]
        assert c["material_fit"]["unknown_count"] > 0
        assert c["inventory"]["videos"] == 0
        assert c["inventory"]["same_product"] == "pending_human"
        assert c["shot_strategies"][2]["material"]["status"] != "suggestion"
        assert any("实拍" in w for w in c["inventory"]["warnings"])
        assert all(s["text"] in [f["text"] for f in facts] for s in c["payload"] if s["fact_ids"])


def test_proposals_depend_on_brief_and_materials_not_request_count():
    p, facts = product()
    base = {"format": "narrated", "audience": "学生", "tone": "活泼节奏"}
    a = alternatives(p, facts, base, assets=[image()])
    assert a == alternatives(p, facts, base, assets=[image()])
    b = alternatives(
        p, facts, {**base, "audience": "重视工艺", "tone": "电影克制留白"}, assets=[image()]
    )
    assert a["basis"] != b["basis"]
    assert [c["direction"]["id"] for c in a["candidates"]] != [
        c["direction"]["id"] for c in b["candidates"]
    ]
    media = image()
    media["metadata"]["source_in"] = 1
    changed = alternatives(p, facts, base, assets=[media])
    assert changed["basis"] != a["basis"]


def test_stale_material_basis_cannot_replace_current_confirmed_script(tmp_path):
    from test_customer import approve, client, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = "/api/products/" + p["id"]
    req = {"revision": p["product"]["revision"], "brief": p["settings"]["brief"]}
    bundle = c.post(base + "/scripts/alternatives", json=req).json()
    old = copy.deepcopy(p["product"])
    a = p["media"][0]
    edited = c.put(
        "/api/customer-projects/" + p["id"] + "/assets/" + a["id"],
        json={
            "revision": p["revision"],
            "role": "detail",
            "source_in": 0,
            "note": "另一用途",
        },
    )
    assert edited.status_code == 200
    response = c.post(
        base + "/scripts/alternatives/adopt",
        json={
            **req,
            "candidate_id": "overview",
            "basis": bundle["basis"],
        },
    )
    assert response.status_code == 409, response.text
    assert c.get(base).json() == old


def test_existing_direction_gets_material_plan_without_changing_fingerprint(tmp_path):
    from test_customer import approve, client, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    options = p["recommendations"]["options"]
    assert len(options) == 3
    assert all(o["production_readiness"]["inventory"]["images"] == 1 for o in options)
    assert all(o["production_readiness"]["fit"]["unknown_count"] for o in options)
    assert p["intake_preflight"]["same_product"] == "pending_human"


def test_changed_saved_audience_rejects_old_proposal_even_if_client_sends_old_brief(tmp_path):
    from test_customer import approve, client, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = "/api/products/" + p["id"]
    req = {"revision": p["product"]["revision"], "brief": p["settings"]["brief"]}
    bundle = c.post(base + "/scripts/alternatives", json=req).json()
    changed = copy.deepcopy(p["settings"])
    changed["brief"]["audience"] = "周末户外人群"
    assert (
        c.put(
            "/api/customer-projects/" + p["id"],
            json={"revision": p["revision"], "settings": changed},
        ).status_code
        == 200
    )
    r = c.post(
        base + "/scripts/alternatives/adopt",
        json={**req, "basis": bundle["basis"], "candidate_id": "overview"},
    )
    assert r.status_code == 409, r.text


def test_concurrent_material_change_is_guarded_inside_draft_transaction(tmp_path, monkeypatch):
    from test_customer import approve, client, picture, project

    from ecom_video.customer import Customers
    from ecom_video.products import Products

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = "/api/products/" + p["id"]
    req = {"revision": p["product"]["revision"], "brief": p["settings"]["brief"]}
    bundle = c.post(base + "/scripts/alternatives", json=req).json()
    save = Products.save_draft

    def race(self, *args, **kwargs):
        service = Customers(tmp_path, c.app.state.store)
        current = service.get(p["id"])
        a = current["media"][0]
        service.edit_media(p["id"], a["id"], current["revision"], "detail", 0, "并发修改")
        return save(self, *args, **kwargs)

    monkeypatch.setattr(Products, "save_draft", race)
    r = c.post(
        base + "/scripts/alternatives/adopt",
        json={**req, "basis": bundle["basis"], "candidate_id": "overview"},
    )
    assert r.status_code == 409, r.text
    assert c.get(base).json() == p["product"]


def test_apparel_hood_details_and_filmed_water_keep_different_presentations():
    from ecom_video.production_direction import choreography_for, framing_for
    from ecom_video.semantic_mix import strategy

    lines = [
        "先看外观。",
        "从连帽轮廓，到上身线条。",
        "林间走动，也能看清正侧面。",
        "看看水花落在衣面上的表现。",
        "最后看清整体。",
    ]
    assert framing_for("lab", lines[1], 1, 5) == "detail"
    rows = choreography_for(lines, "lab", [4] * 5)
    assert rows[1]["shot_recipe"] == "scanline-annotate-focus"
    assert rows[2]["shot_recipe"] == rows[3]["shot_recipe"] == "none"
    assert strategy({"script": "\n".join(lines)}, 1, {"kind": "video"})["kind"] == "detail"
    assert strategy({"script": "\n".join(lines)}, 3, {"kind": "video"})["kind"] == "action"


def test_still_image_cannot_satisfy_new_apparel_actions():
    from ecom_video.readiness import action_occurrences, check_materials, required_actions

    a = image()
    a["metadata"]["content_analysis"] = {
        "source_sha256": a["sha256"],
        "recognition": "complete",
        "segments": [
            {
                "start": 0,
                "end": 10,
                "observation": {
                    "usable": True,
                    "description": "户外摆放黑色背包",
                    "objects": ["背包"],
                    "actions": [],
                    "setting": "outdoor",
                    "uncertainty": "",
                },
            }
        ],
    }
    line = "背上背包，在户外走动。"
    assert required_actions(line) == ["shoulder_bag", "walk"]
    assert action_occurrences(line) == ["shoulder_bag", "walk"]
    row = check_materials([line], [a])["lines"][0]
    assert row["status"] != "suggestion" and not row["candidates"]


def test_concurrent_analysis_completion_rejects_old_proposal(tmp_path, monkeypatch):
    import json

    from test_customer import approve, client, picture, project

    from ecom_video.media_analysis import Analysis
    from ecom_video.products import Products

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    store = c.app.state.store
    analysis = Analysis(tmp_path, store).start(p["id"], p["media"][0]["id"])
    base = "/api/products/" + p["id"]
    req = {"revision": p["product"]["revision"], "brief": p["settings"]["brief"]}
    bundle = c.post(base + "/scripts/alternatives", json=req).json()
    save = Products.save_draft

    def race(self, *args, **kwargs):
        with store.transaction() as conn:
            conn.execute(
                "UPDATE media_analyses SET status='ready',result=? WHERE id=?",
                (json.dumps({"segments": [], "context": {}}), analysis["id"]),
            )
        return save(self, *args, **kwargs)

    monkeypatch.setattr(Products, "save_draft", race)
    r = c.post(
        base + "/scripts/alternatives/adopt",
        json={**req, "basis": bundle["basis"], "candidate_id": "overview"},
    )
    assert r.status_code == 409, r.text
    assert c.get(base).json() == p["product"]
