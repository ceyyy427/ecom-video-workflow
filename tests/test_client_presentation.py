import copy

import pytest


def test_presentation_opt_in_and_old_signature_unchanged():
    from ecom_video.delivery_revision import canonical
    from ecom_video.storyboard import Shot

    assert Shot().presentation is None
    assert Shot(presentation="client").presentation == "client"
    with pytest.raises(ValueError):
        Shot(presentation="remote")
    old = {"assets": [], "storyboard": {"shots": [{"shot_id": "a"}]}}
    before = canonical(old)
    old["storyboard"]["shots"][0]["presentation"] = None
    assert canonical(old) == before


def test_legacy_recipe_without_motion_plan_cannot_silently_change_in_client_mode():
    from ecom_video.storyboard import Shot

    assert Shot(shot_recipe="scanline-annotate-focus").presentation is None
    with pytest.raises(ValueError, match="动效计划"):
        Shot(presentation="client", shot_recipe="scanline-annotate-focus")
    assert Shot(
        presentation="client", shot_recipe="scanline-annotate-focus", motion_plan={"version": 2}
    )


def test_only_selected_shot_changes_and_can_return_to_legacy():
    from ecom_video.customer_api import ShotChanges
    from ecom_video.shot_changes import apply_changes

    board = [{"shot_id": "a", "presentation": None}, {"shot_id": "b"}]
    untouched = copy.deepcopy(board[1])
    apply_changes(board[0], ShotChanges(presentation="client").model_dump(exclude_unset=True))
    assert board[0]["presentation"] == "client"
    assert board[1] == untouched
    apply_changes(board[0], {"presentation": "legacy"})
    assert board[0]["presentation"] == "legacy"


def test_saved_customer_board_accepts_client_and_requires_normal_review(tmp_path):
    from test_customer import approve, client, picture, plan, prepare, project

    c = client(tmp_path / "runtime")
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    job = p["job"]
    board = copy.deepcopy(job["storyboard"])
    board["shots"][0]["presentation"] = "client"
    response = c.put(
        "/api/jobs/" + job["id"] + "/storyboard",
        json={"revision": job["storyboard_revision"], "board": board},
    )
    assert response.status_code == 200, response.text
    assert response.json()["storyboard"]["shots"][0]["presentation"] == "client"
    assert response.json()["status"] == "draft"
