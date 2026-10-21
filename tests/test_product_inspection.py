from test_customer import client, picture, project


def test_reference_is_project_owned_image_and_changes_analysis_context(tmp_path):
    c = client(tmp_path)
    p = picture(c, project(c))
    foreign = picture(c, project(c, "other"))
    base = f"/api/customer-projects/{p['id']}"
    settings = {
        **p["settings"],
        "strict_product": True,
        "action_timing": True,
        "product_reference_id": foreign["media"][0]["id"],
    }
    assert c.put(base, json={"revision": p["revision"], "settings": settings}).status_code == 422
    settings["product_reference_id"] = p["media"][0]["id"]
    r = c.put(base, json={"revision": p["revision"], "settings": settings})
    assert r.status_code == 200, r.text
    p = r.json()
    path = base + f"/assets/{p['media'][0]['id']}/analysis"
    a = c.post(path, json={}).json()
    assert a["result"]["context"]["reference_sha256"] == p["media"][0]["sha256"]
    assert c.post(path, json={}).json()["id"] == a["id"]
    settings["action_timing"] = False
    c.put(base, json={"revision": p["revision"], "settings": settings})
    b = c.post(path, json={}).json()
    assert b["id"] != a["id"]
    from ecom_video.db import Store

    with Store(tmp_path / "workflow.db").connect() as db:
        assert (
            db.execute("SELECT status FROM media_analyses WHERE id=?", (a["id"],)).fetchone()[
                "status"
            ]
            == "cancelled"
        )


def test_reference_required_before_strict_analysis(tmp_path):
    c = client(tmp_path)
    p = picture(c, project(c))
    base = f"/api/customer-projects/{p['id']}"
    r = c.put(
        base,
        json={"revision": p["revision"], "settings": {**p["settings"], "strict_product": True}},
    )
    assert r.status_code == 200
    r = c.post(base + f"/assets/{p['media'][0]['id']}/analysis", json={})
    assert r.status_code == 422 and "参照图" in r.text


def test_context_change_during_inference_never_publishes_ready(tmp_path, monkeypatch):
    import pytest

    from ecom_video import vision_model
    from ecom_video.db import Conflict, Store
    from ecom_video.media_analysis import Analysis

    c = client(tmp_path)
    p = picture(c, project(c))
    base = f"/api/customer-projects/{p['id']}"
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    svc.start(p["id"], p["media"][0]["id"])
    row = svc.claim()
    monkeypatch.setattr(vision_model, "identity", lambda: {"model": "fixture", "digest": "fixture"})

    def change_reference(*args):
        r = c.put(
            base,
            json={
                "revision": p["revision"],
                "settings": {
                    **p["settings"],
                    "strict_product": True,
                    "product_reference_id": p["media"][0]["id"],
                },
            },
        )
        assert r.status_code == 200
        return {
            "description": "fixture",
            "subjects": [],
            "actions": [],
            "framing": "whole",
            "usable": True,
            "uncertainty": "",
        }

    monkeypatch.setattr(vision_model, "observe", change_reference)
    with pytest.raises(Conflict, match="参照"):
        svc.run(row, lambda: None)
    assert svc.get(p["id"], p["media"][0]["id"])["status"] != "ready"


def test_motion_cannot_borrow_action_from_second_container(monkeypatch):
    from ecom_video import product_inspection as inspect

    monkeypatch.setattr(
        inspect,
        "generate",
        lambda *args, **kwargs: {
            "target_count": "multiple",
            "liquid_stream_outside_container": True,
            "cap_separated_from_mouth": True,
            "cap_covers_mouth": False,
            "hand_holds_cap": True,
        },
    )
    state = inspect.motion_state("unused", {"model": "fixture"}, "bottle")
    assert state["flow"] == "unclear" and state["lid"] == "unclear" and not state["handling_lid"]


def test_reference_cup_controls_motion_subject_and_conflicting_cap_is_unknown(monkeypatch):
    from ecom_video import product_inspection as inspect

    def response(prompt, *args, **kwargs):
        assert "target category is cup" in prompt
        return {
            "target_count": "one",
            "liquid_stream_outside_container": True,
            "cap_separated_from_mouth": True,
            "cap_covers_mouth": True,
            "hand_holds_cap": True,
        }

    monkeypatch.setattr(inspect, "generate", response)
    state = inspect.motion_state("unused", {"model": "fixture"}, "cup")
    assert state["flow"] == "absent" and state["lid"] == "unclear"
