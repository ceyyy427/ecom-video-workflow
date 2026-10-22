import copy

from test_customer import approve, client, picture, prepare, project


def delivery_project(c):
    p = approve(c, picture(c, project(c)))
    settings = {**p["settings"], "delivery_version": 1}
    p = c.put(
        f"/api/customer-projects/{p['id']}", json={"revision": p["revision"], "settings": settings}
    ).json()
    return prepare(c, p)


def confirm(c, p, stage, style):
    result = c.post(
        f"/api/customer-projects/{p['id']}/style-reviews",
        json={
            "revision": p["revision"],
            "stage": stage,
            "style_id": style,
            "basis": p["delivery_reviews"][stage + "_basis"],
            "confirmed": True,
            "reviewer": "AUTOMATED FIXTURE 不代表客户审批",
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def planning(c, p, style):
    return c.post(
        f"/api/customer-projects/{p['id']}/plan",
        json={
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
            "style_id": style,
            "fingerprint": p["recommendations"]["fingerprint"],
        },
    )


def test_agent_planning_cannot_replace_two_human_style_confirmations(tmp_path):
    c = client(tmp_path)
    p = delivery_project(c)
    style = p["recommendations"]["options"][0]["id"]
    r = planning(c, p, style)
    assert r.status_code == 409 and "方向" in r.text
    p = confirm(c, p, "direction", style)
    r = planning(c, p, style)
    assert r.status_code == 200, r.text
    p = r.json()
    jid = p["job"]["id"]
    # The legacy submit route must enforce the exact same final gate.
    r = c.post(f"/api/jobs/{jid}/submit")
    assert r.status_code == 409 and "分镜" in r.text
    p = confirm(c, p, "storyboard", style)
    r = c.post(f"/api/jobs/{jid}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["snapshot"]["delivery_reviews"]["storyboard"]["reviewer"].startswith(
        "AUTOMATED FIXTURE"
    )


def test_saved_edit_invalidates_final_style_review_without_changing_earlier_direction(tmp_path):
    c = client(tmp_path)
    p = delivery_project(c)
    style = p["recommendations"]["options"][0]["id"]
    p = confirm(c, p, "direction", style)
    p = planning(c, p, style).json()
    p = confirm(c, p, "storyboard", style)
    job = p["job"]
    board = copy.deepcopy(job["storyboard"])
    board["shots"][0]["focus_x"] = 0.7
    r = c.put(
        f"/api/jobs/{job['id']}/storyboard",
        json={"revision": job["storyboard_revision"], "board": board},
    )
    assert r.status_code == 200, r.text
    p = c.get(f"/api/customer-projects/{p['id']}").json()
    assert p["delivery_reviews"]["direction"]
    assert not p["delivery_reviews"]["storyboard"]
    assert c.post(f"/api/jobs/{job['id']}/submit").status_code == 409


def test_new_direction_invalidates_old_final_confirmation_even_if_later_changed_back(tmp_path):
    c = client(tmp_path)
    p = delivery_project(c)
    style, other = [o["id"] for o in p["recommendations"]["options"]][:2]
    p = confirm(c, p, "direction", style)
    p = planning(c, p, style).json()
    p = confirm(c, p, "storyboard", style)
    for changed_style in (other, style):
        p = confirm(c, p, "direction", changed_style)
        assert not p["delivery_reviews"]["storyboard"]
        assert c.post(f"/api/jobs/{p['job']['id']}/submit").status_code == 409
    p = confirm(c, p, "storyboard", style)
    assert c.post(f"/api/jobs/{p['job']['id']}/submit").status_code == 200


def test_identity_edit_invalidates_prepared_input_and_early_choice(tmp_path):
    c = client(tmp_path)
    p = delivery_project(c)
    style = p["recommendations"]["options"][0]["id"]
    p = confirm(c, p, "direction", style)
    a = p["media"][0]
    r = c.put(
        f"/api/customer-projects/{p['id']}/assets/{a['id']}",
        json={
            "revision": p["revision"],
            "role": a["role"],
            "source_in": a["source_in"],
            "note": a["note"],
            "identity": {
                "sku": "另一款",
                "color": "白色",
                "confirmed": True,
                "reviewer": "AUTOMATED FIXTURE",
            },
        },
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["inputs_changed"] is True
    assert not p["delivery_reviews"]["direction"]


def test_removing_delivery_contract_cannot_be_human_confirmed_as_current_board(tmp_path):
    c = client(tmp_path)
    p = delivery_project(c)
    style = p["recommendations"]["options"][0]["id"]
    p = confirm(c, p, "direction", style)
    p = planning(c, p, style).json()
    board = copy.deepcopy(p["job"]["storyboard"])
    board["delivery"] = None
    job = p["job"]
    assert (
        c.put(
            f"/api/jobs/{job['id']}/storyboard",
            json={"revision": job["storyboard_revision"], "board": board},
        ).status_code
        == 200
    )
    p = c.get(f"/api/customer-projects/{p['id']}").json()
    r = c.post(
        f"/api/customer-projects/{p['id']}/style-reviews",
        json={
            "revision": p["revision"],
            "stage": "storyboard",
            "style_id": style,
            "basis": p["delivery_reviews"]["storyboard_basis"],
            "confirmed": True,
            "reviewer": "AUTOMATED FIXTURE",
        },
    )
    assert r.status_code == 409, r.text


def test_delivery_agent_waits_for_final_human_board_review_then_resumes(tmp_path, monkeypatch):
    from test_agent_runtime import choose, control, setup_run, start

    c, p, proposal, runtime = setup_run(tmp_path, monkeypatch, settings={"delivery_version": 1})
    start(proposal, runtime)
    for _ in range(4):
        runtime.tick()
    choose(p, proposal, runtime)
    execution = runtime.get(proposal["run_id"])
    runtime.control(proposal["run_id"], "resume", control(proposal, execution["revision"]))
    for _ in range(6):
        runtime.tick()
    execution = runtime.get(proposal["run_id"])
    assert execution["status"] == "waiting_human"
    assert execution["waiting_for"] == "storyboard"
    p = c.get(f"/api/customer-projects/{p['id']}").json()
    assert p["job"]["status"] == "draft" and p["delivery_reviews"]["direction"]
    p = confirm(c, p, "storyboard", "cinema")
    runtime.control(proposal["run_id"], "resume", control(proposal, execution["revision"]))
    runtime.tick()
    assert c.get(f"/api/customer-projects/{p['id']}").json()["job"]["status"] == "queued"
