"""Synthetic engineering tests; no client approvals or performance claims."""

import copy

import pytest
from test_customer import approve, client, picture, prepare, project


def test_spoken_copy_preserves_complete_facts_and_rejects_extra_claims():
    from ecom_video.spoken_copy import speak, validate_copy

    facts = [
        {"id": "f", "text": "仅在活动期内满200元减20元，不含运费。"},
        {"id": "d", "text": "藏蓝连帽设计。"},
    ]
    for kind in ("overview", "scene", "details"):
        rows = speak(facts, {"category": "软壳衣", "audience": "通勤人群", "tone": "自然"}, kind)
        assert validate_copy(rows, facts) == rows
        assert any(r["text"] == facts[0]["text"] for r in rows)
        assert any(facts[1]["text"] in r["text"] and r["text"] != facts[1]["text"] for r in rows)
        from ecom_video.generation import validate_scenes

        saved = validate_scenes(rows, facts)
        assert next(r for r in saved if r["fact_ids"] == ["d"])["attribution"] == "bounded_spoken"
        changed = copy.deepcopy(rows)
        next(r for r in changed if r["fact_ids"] == ["d"])["text"] = "亲测穿一个月也不冷。"
        with pytest.raises(ValueError, match="原文|受控"):
            validate_copy(changed, facts)


def get_bundle(c, p):
    r = c.post(
        f"/api/customer-projects/{p['id']}/creative-proposals",
        json={"revision": p["revision"], "product_revision": p["product"]["revision"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_commuter_shirt_does_not_become_an_outerwear_claim():
    from ecom_video.spoken_copy import speak

    for kind in ("overview", "scene", "details"):
        rows = speak(
            [{"id": "f", "text": "白色衬衫。"}], {"category": "衬衣", "audience": "通勤人群"}, kind
        )
        assert "外套" not in rows[0]["text"]


def test_joint_production_headline_describes_the_product_not_the_spoken_connector(tmp_path):
    from ecom_video.customer_planner import plan_board

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    job = copy.deepcopy(p["job"])
    lines = ["先看一眼，再看细节。", "先看，奶白色杯身", "看清楚，再挑适合自己的。"]
    payload = [{"text": line, "fact_ids": []} for line in lines]
    job["script"] = "\n".join(lines)
    job["provenance"]["creative_plan"] = {"version": "joint-creative-v1", "payload": payload}
    style = p["recommendations"]["options"][0]["id"]
    board, _ = plan_board(job, p["settings"], style)
    assert board["shots"][1]["headline"] == "奶白色杯身"
    job["provenance"].pop("creative_plan")
    old, _ = plan_board(job, p["settings"], style)
    assert old["shots"][1]["headline"] == "先看"
    payload[1]["text"] = "先看，鲜橙外观与切面实拍。"
    job["script"] = "\n".join(s["text"] for s in payload)
    job["provenance"]["creative_plan"] = {"version": "joint-creative-v1", "payload": payload}
    board, _ = plan_board(job, p["settings"], style)
    assert board["shots"][1]["headline"] == "切面", "不能截成不完整的‘切面实’"


def test_joint_proposal_preview_is_stateless_adoption_is_pending_and_plan_survives_confirmation(
    tmp_path,
):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    before = copy.deepcopy(p["product"])
    bundle = get_bundle(c, p)
    assert c.get(f"/api/products/{p['id']}").json() == before
    assert len({a["direction"]["family"] for a in bundle["candidates"]}) == 3
    assert len({a["payload"][0]["text"] for a in bundle["candidates"]}) == 3
    for a in bundle["candidates"]:
        assert a["voice"]["speaker"] and a["narrative"]
        assert len(a["visual_plan"]) == len(a["payload"])
        assert all(v["reason"] and "fallback" in v for v in a["visual_plan"])
        assert a["material_fit"]["unknown_count"] > 0
    chosen = bundle["candidates"][0]
    request = {
        "revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "basis": bundle["basis"],
        "candidate_id": chosen["id"],
    }
    r = c.post(f"/api/customer-projects/{p['id']}/creative-proposals/adopt", json=request)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["product"]["status"] == "script_draft"
    assert p["creative_plan"]["id"] == chosen["id"]
    prod = p["product"]
    r = c.post(
        f"/api/products/{p['id']}/scripts/confirm",
        json={
            "revision": prod["revision"],
            "draft_id": prod["current_draft_id"],
            "reviewer": "AUTOMATED FIXTURE",
            "note": "非客户确认",
            "confirmed": True,
        },
    )
    assert r.status_code == 201, r.text
    p = prepare(c, c.get(f"/api/customer-projects/{p['id']}").json())
    assert p["job"]["provenance"]["creative_plan"]["basis"] == bundle["basis"]
    # Editing with the ordinary manual-script route does not inherit a stale joint plan.
    r = c.post(
        f"/api/products/{p['id']}/scripts",
        json={
            "revision": p["product"]["revision"],
            "scenes": [{"text": "奶白色杯身", "fact_ids": [p["product"]["facts"][0]["id"]]}],
        },
    )
    assert r.status_code == 201, r.text
    assert c.get(f"/api/customer-projects/{p['id']}").json()["creative_plan"] is None


def test_joint_proposals_expire_after_saved_audience_change(tmp_path):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    bundle = get_bundle(c, p)
    settings = {**p["settings"], "brief": {**p["settings"]["brief"], "audience": "新的受众"}}
    r = c.put(
        f"/api/customer-projects/{p['id']}", json={"revision": p["revision"], "settings": settings}
    )
    assert r.status_code == 200
    newer = r.json()
    r = c.post(
        f"/api/customer-projects/{p['id']}/creative-proposals/adopt",
        json={
            "revision": newer["revision"],
            "product_revision": newer["product"]["revision"],
            "basis": bundle["basis"],
            "candidate_id": "overview",
        },
    )
    assert r.status_code == 409, r.text
    assert get_bundle(c, newer)["basis"] != bundle["basis"]


def test_adoption_transaction_does_not_race_a_newly_running_job(tmp_path, monkeypatch):
    from ecom_video.products import Products

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    bundle = get_bundle(c, p)
    original = Products.save_draft

    def racing(self, *args, **kwargs):
        with self.store.transaction() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (p["job"]["id"],))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Products, "save_draft", racing)
    r = c.post(
        f"/api/customer-projects/{p['id']}/creative-proposals/adopt",
        json={
            "revision": p["revision"],
            "product_revision": p["product"]["revision"],
            "basis": bundle["basis"],
            "candidate_id": "overview",
        },
    )
    assert r.status_code == 409, r.text[:500]
    assert (
        c.get(f"/api/products/{p['id']}").json()["current_draft_id"]
        == p["product"]["current_draft_id"]
    )
