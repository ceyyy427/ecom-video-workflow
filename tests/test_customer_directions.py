"""Style choice must be usable before narration / expensive visual analysis."""

from test_customer import approve, client, picture, prepare, project


def narrated(c, p):
    return c.put(
        "/api/customer-projects/" + p["id"],
        json={
            "revision": p["revision"],
            "settings": {
                **p["settings"],
                "brief": {"format": "narrated"},
                "auto_select": True,
                "strict_product": True,
                "action_timing": True,
            },
        },
    ).json()


def test_confirmed_script_recommends_before_voice_and_analysis_without_bypassing_prepare(tmp_path):
    c = client(tmp_path)
    p = approve(c, narrated(c, picture(c, project(c))))
    assert p["job"] is None
    assert len(p["recommendations"]["options"]) == 3
    assert p["recommendations"]["scope"] == "project"
    assert any("配音" in x for x in p["preparation_blockers"])
    assert any("参照" in x for x in p["preparation_blockers"])
    assert (
        c.post(
            "/api/customer-projects/" + p["id"] + "/prepare", json={"revision": p["revision"]}
        ).status_code
        >= 400
    )
    assert c.get("/api/customer-projects/" + p["id"]).json()["job"] is None


def test_unconfirmed_script_has_no_recommendation(tmp_path):
    c = client(tmp_path)
    p = picture(c, project(c))
    assert p["recommendations"] is None


def test_preparation_keeps_direction_basis_but_uses_job_fingerprint(tmp_path):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    basis = p["direction_basis"]
    p = prepare(c, p)
    assert p["direction_basis"] == basis
    assert p["recommendations"]["scope"] == "job"
    from ecom_video.creative import recommend

    assert (
        p["recommendations"]["fingerprint"]
        == recommend(p["job"], p["settings"]["brief"])["fingerprint"]
    )


def test_new_script_invalidates_early_choice_and_old_board_does_not_block_directions(tmp_path):
    from test_customer import plan

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    old = p["direction_basis"]
    p = plan(c, prepare(c, p))
    prod = p["product"]
    payload = [
        {"text": s["text"], "fact_ids": s["fact_ids"]} for s in prod["script_drafts"][0]["payload"]
    ]
    r = c.post(
        "/api/products/" + p["id"] + "/scripts",
        json={"revision": prod["revision"], "scenes": payload},
    )
    assert r.status_code == 201
    current = c.get("/api/customer-projects/" + p["id"]).json()
    assert current["recommendations"] is None
    prod = r.json()
    r = c.post(
        "/api/products/" + p["id"] + "/scripts/confirm",
        json={
            "revision": prod["revision"],
            "draft_id": prod["current_draft_id"],
            "reviewer": "自动测试",
            "note": "fixture",
            "confirmed": True,
            "seconds": 2,
        },
    )
    assert r.status_code == 201
    current = c.get("/api/customer-projects/" + p["id"]).json()
    assert current["inputs_changed"]
    assert current["recommendations"]["scope"] == "project"
    assert len(current["recommendations"]["options"]) == 3
    assert current["direction_basis"] != old
