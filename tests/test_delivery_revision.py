import copy

from test_customer import approve, client, picture, plan, prepare, project
from test_experiments import finish


def env(root):
    c = client(root)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    finish(root, c.app.state.store, p["job"]["id"])
    return c, c.get("/api/customer-projects/" + p["id"]).json()


def version(p):
    return {
        "revision": p["revision"],
        "job_id": p["job"]["id"],
        "board_revision": p["job"]["storyboard_revision"],
    }


def test_impact_readonly_and_compare_remaps_asset_ids(tmp_path):
    c, p = env(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    data = {
        **version(p),
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "changes": {"headline": ""},
    }
    before = c.app.state.store.get(p["job"]["id"])
    r = c.post(base + "/edit-impact", json=data)
    assert r.status_code == 200, r.text
    assert r.json()["affected_shots"] == [data["shot_id"]]
    assert r.json()["audio_changed"] is False
    assert c.app.state.store.get(p["job"]["id"]) == before
    child = c.post(base + "/revise-shot", json={**data, "request_id": "revision-test-00001"}).json()
    r = c.get(
        base + "/version-comparison", params={"before": p["job"]["id"], "after": child["job"]["id"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["changed_shots"] == [data["shot_id"]]
    assert not r.json()["audio_changed"]
    assert not r.json()["script_changed"]
    other = project(c)
    assert (
        c.get(
            "/api/customer-projects/" + other["id"] + "/version-comparison",
            params={"before": p["job"]["id"], "after": child["job"]["id"]},
        ).status_code
        == 404
    )


def test_restore_preserves_old_version_and_rejects_stale_and_running(tmp_path):
    c, p = env(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    child = c.post(
        base + "/revise-shot",
        json={
            **version(p),
            "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
            "changes": {"headline": ""},
            "request_id": "revision-test-00002",
        },
    ).json()
    parent_before = c.app.state.store.get(p["job"]["id"])
    r = c.post(
        base + "/restore-version",
        json={
            **version(child),
            "target_job_id": p["job"]["id"],
            "confirmed": True,
            "reviewer": "AUTOMATED FIXTURE",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["job"]["id"] == p["job"]["id"]
    assert c.app.state.store.get(p["job"]["id"])["reviews"] == parent_before["reviews"]
    assert len(r.json()["versions"]) == 2
    assert (
        c.post(
            base + "/restore-version",
            json={
                **version(child),
                "target_job_id": p["job"]["id"],
                "confirmed": True,
                "reviewer": "AUTOMATED FIXTURE",
            },
        ).status_code
        == 409
    )
    p2 = picture(c, r.json())
    assert (
        c.post(
            base + "/restore-version",
            json={
                **version(p2),
                "target_job_id": child["job"]["id"],
                "confirmed": True,
                "reviewer": "AUTOMATED FIXTURE",
            },
        ).status_code
        == 409
    )


def test_shot_review_binds_film_blocks_legacy_final_and_fixture_handoff(tmp_path):
    c, p = env(tmp_path)
    jid = p["job"]["id"]
    store = c.app.state.store
    # Fixture simulates a render ending, never a real customer audit.
    with store.transaction() as db:
        db.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (jid,))
    base = "/api/customer-projects/" + p["id"]
    p = c.get(base).json()
    r = c.get(base + "/shot-reviews")
    assert r.status_code == 200, r.text
    state = r.json()
    data = {
        **version(p),
        "basis": state["basis"],
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "decision": "changes_requested",
        "reason": "product_visibility",
        "note": "商品太小",
        "reviewer": "AUTOMATED FIXTURE",
        "confirmed": True,
    }
    r = c.post(base + "/shot-reviews", json=data)
    assert r.status_code == 200, r.text
    final = {"decision": "ready", "reviewer": "人工", "note": "已看听", "confirmed": True}
    assert c.post("/api/jobs/" + jid + "/review", json=final).status_code == 409
    for s in p["job"]["storyboard"]["shots"]:
        r = c.post(
            base + "/shot-reviews",
            json={
                **data,
                "shot_id": s["shot_id"],
                "decision": "pass",
                "reason": "checked",
                "note": "fixture仅测试",
            },
        )
        assert r.status_code == 200, r.text
    assert r.json()["all_passed"] and r.json()["fixture"]
    assert c.post("/api/jobs/" + jid + "/review", json=final).status_code == 200
    assert c.get(base).json()["handoff_status"]["approved_for_handoff"] is False
    assert c.post(base + "/shot-reviews", json=data).status_code == 409


def test_review_stale_hash_and_impact_unknown_fields_rejected(tmp_path):
    c, p = env(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    data = {
        **version(p),
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "changes": {"duration": 1},
    }
    assert c.post(base + "/edit-impact", json=data).status_code == 422
    assert (
        c.post(
            base + "/edit-impact", json={**data, "changes": {"headline": "x"}, "revision": -1}
        ).status_code
        == 422
    )
    r = c.post(
        base + "/shot-reviews",
        json={
            **version(p),
            "basis": "0" * 64,
            "shot_id": data["shot_id"],
            "decision": "pass",
            "reason": "checked",
            "note": "test",
            "reviewer": "AUTOMATED FIXTURE",
            "confirmed": True,
        },
    )
    assert r.status_code == 409


def test_frozen_links_and_creative_structure_are_versioned(tmp_path, monkeypatch):
    from test_experiments import build_env

    service, body, c, frozen = build_env(tmp_path, monkeypatch)
    pid = service.context(frozen["review_id"], "123")["product_id"]
    r = c.get("/api/customer-projects/" + pid + "/learning-links")
    assert r.status_code == 200, r.text
    assert r.json()["snapshots"][0]["review_id"] == frozen["review_id"]
    assert r.json()["snapshots"][0]["material_id"] == "123"
    assert r.json()["causal_inference"] is False
    f = frozen["snapshot"]["materials"][0]["creative_feature"]
    assert f["feature_version"] == "submitted-creative-v2"
    assert f["features"]["shot_recipes"] is not None
    assert f["features"]["creative_plan_id"] is None
    assert "feature_missing:creative_plan_id" in f["missing_reasons"]
    assert service.reviews.get(frozen["review_id"]) == frozen


def test_comparison_includes_music_gain_in_audio_impact(tmp_path):
    c, p = env(tmp_path)
    base = "/api/customer-projects/" + p["id"]
    child = c.post(
        base + "/revise-shot",
        json={
            **version(p),
            "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
            "changes": {"headline": ""},
            "request_id": "gain-comparison-001",
        },
    ).json()
    board = copy.deepcopy(child["job"]["storyboard"])
    board["music_db"] = -24
    r = c.put(
        "/api/jobs/" + child["job"]["id"] + "/storyboard",
        json={"revision": child["job"]["storyboard_revision"], "board": board},
    )
    assert r.status_code == 200, r.text
    r = c.get(
        base + "/version-comparison", params={"before": p["job"]["id"], "after": child["job"]["id"]}
    )
    assert r.json()["audio_changed"] is True


def test_frozen_features_preserve_review_reasons_without_changing_old_snapshot(
    tmp_path, monkeypatch
):
    from test_experiments import build_env

    service, body, c, original = build_env(tmp_path, monkeypatch)
    jid = body["parent_job_id"]
    pid = service.context(original["review_id"], "123")["product_id"]
    with service.store.transaction() as db:
        db.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (jid,))
    p = c.get("/api/customer-projects/" + pid).json()
    data = {
        **version(p),
        "basis": p["shot_reviews"]["basis"],
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "decision": "changes_requested",
        "reason": "product_visibility",
        "note": "fixture 商品不清楚",
        "reviewer": "AUTOMATED FIXTURE",
        "confirmed": True,
    }
    assert c.post("/api/customer-projects/" + pid + "/shot-reviews", json=data).status_code == 200
    # Capture review provenance directly; no counterfeit film approval.
    from ecom_video.creative_features import extract

    job = service.store.get(jid)
    payload = extract({**job, "snapshot": __import__("json").dumps(job["snapshot"])}, "a" * 64)
    assert payload["feature_version"] == "submitted-creative-v2"
    assert (
        original["snapshot"]["materials"][0]["creative_feature"]["production_review"]["enabled"]
        is False
    )
    assert service.reviews.get(original["review_id"]) == original


def test_media_replacement_preview_agrees_with_real_revision(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, picture(c, project(c)), "detail"))))
    finish(tmp_path, c.app.state.store, p["job"]["id"])
    p = c.get("/api/customer-projects/" + p["id"]).json()
    data = {
        **version(p),
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "changes": {"media_id": p["media"][1]["id"]},
    }
    r = c.post("/api/customer-projects/" + p["id"] + "/edit-impact", json=data)
    assert r.status_code == 200, r.text
    assert r.json()["can_apply_single_shot"]
    r = c.post(
        "/api/customer-projects/" + p["id"] + "/revise-shot",
        json={**data, "request_id": "review-media-00001"},
    )
    assert r.status_code == 201, r.text


def test_draft_preview_accepts_transition_but_finished_revision_does_not(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    base = "/api/customer-projects/" + p["id"]
    data = {
        **version(p),
        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
        "changes": {"transition": "wipe"},
    }
    r = c.post(base + "/edit-impact", json=data)
    assert r.status_code == 200, r.text
    assert r.json()["can_apply"]
    board = copy.deepcopy(p["job"]["storyboard"])
    board["shots"][0]["transition"] = "wipe"
    assert (
        c.put(
            "/api/jobs/" + p["job"]["id"] + "/storyboard",
            json={"revision": p["job"]["storyboard_revision"], "board": board},
        ).status_code
        == 200
    )
    finish(tmp_path, c.app.state.store, p["job"]["id"])
    p = c.get(base).json()
    assert c.post(base + "/edit-impact", json={**data, **version(p)}).status_code == 422
