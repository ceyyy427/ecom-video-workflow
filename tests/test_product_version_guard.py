"""An inspection upgrade invalidates automatic work without rewriting history.

The legacy analysis is an explicit database fixture; no model or network runs.
"""

import copy
import json

import pytest
from test_customer import approve, client, picture, plan, prepare, project

from ecom_video import clip_matching, customer, product_inspection, product_motion
from ecom_video.db import Store
from ecom_video.media import digest
from ecom_video.media_analysis import Analysis


def legacy_ready_analysis(root, p):
    asset = p["media"][0]
    store = Store(root / "workflow.db")
    row = Analysis(root, store).start(p["id"], asset["id"])
    result = {
        "analysis_id": row["id"],
        "source_sha256": asset["sha256"],
        "context": row["result"]["context"],
        "recognition": "complete",
        "segments": [
            {
                "id": "clip-00",
                "start": 0,
                "end": 0,
                "frames": [],
                "sample_times": [],
                "quality": {"blank": False},
                "observation": {
                    "description": "奶白色杯身，深色杯盖",
                    "subjects": ["杯盖"],
                    "actions": [],
                    "framing": "whole",
                    "usable": True,
                    "uncertainty": "",
                },
                "motion_check": {
                    "version": "reference-motion-v1",
                    "reference_sha256": asset["sha256"],
                    "identity": "same",
                    "samples": [],
                    "events": [],
                },
            }
        ],
    }
    with store.transaction() as db:
        db.execute(
            "UPDATE media_analyses SET status='ready',result=? WHERE id=?",
            (json.dumps(result), row["id"]),
        )


@pytest.mark.parametrize("operation", ["plan", "customer_submit", "legacy_submit"])
def test_prepared_v1_automatic_job_cannot_plan_or_submit_after_upgrade(
    tmp_path, monkeypatch, operation
):
    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = f"/api/customer-projects/{p['id']}"
    response = c.put(
        base,
        json={
            "revision": p["revision"],
            "settings": {
                **p["settings"],
                "auto_select": True,
                "strict_product": True,
                "product_reference_id": p["media"][0]["id"],
            },
        },
    )
    assert response.status_code == 200
    p = response.json()

    with monkeypatch.context() as old:
        old.setattr(customer, "MOTION_VERSION", "reference-motion-v1")
        old.setattr(product_inspection, "VERSION", "reference-motion-v1")
        old.setattr(product_motion, "VERSION", "reference-motion-v1")
        legacy_ready_analysis(tmp_path, p)
        p = prepare(c, c.get(base).json())
        recommendation_fingerprint = p["recommendations"]["fingerprint"]
        if operation != "plan":
            old.setattr(clip_matching, "identity", lambda: {"model": "fixture", "digest": "fixture"})

            def fixture_rank(lines, pool, model):
                return [
                    {
                        "line": i + 1,
                        "choices": [{"clip_id": pool[0]["id"], "score": 3, "reason": "fixture"}],
                    }
                    for i in range(len(lines))
                ]

            old.setattr(clip_matching, "rank", fixture_rank)
            p = plan(c, p, "lab")
        assert not p["inputs_changed"]
        historical_job = copy.deepcopy(p["job"])
        historical_versions = copy.deepcopy(p["versions"])

    current = c.get(base).json()
    assert current["media"][0]["analysis_stale"]
    assert current["inputs_changed"]
    request = {
        "revision": current["revision"],
        "job_id": historical_job["id"],
        "board_revision": historical_job["storyboard_revision"],
    }
    if operation == "plan":
        response = c.post(
            base + "/plan",
            json={**request, "style_id": "lab", "fingerprint": recommendation_fingerprint},
        )
    elif operation == "customer_submit":
        response = c.post(base + "/submit", json=request)
    else:
        response = c.post(f"/api/jobs/{historical_job['id']}/submit")
    assert response.status_code == 409, response.text

    after = c.get(base).json()
    assert after["job"] == historical_job
    assert after["versions"] == historical_versions
    assert c.get(f"/api/jobs/{historical_job['id']}").json() == historical_job
    for asset in historical_job["assets"]:
        assert digest(tmp_path / asset["path"]) == asset["sha256"]


def test_inspection_upgrade_preserves_manual_project_and_saved_board(tmp_path, monkeypatch):
    c = client(tmp_path)
    with monkeypatch.context() as old:
        old.setattr(customer, "MOTION_VERSION", "reference-motion-v1")
        p = plan(c, prepare(c, approve(c, picture(c, project(c)))), "lab")
    current = c.get(f"/api/customer-projects/{p['id']}").json()
    assert not current["inputs_changed"]
    assert current["job"] == p["job"]
    assert current["versions"] == p["versions"]


def test_identity_filter_rejects_legacy_or_missing_inspection_version():
    constraints = {"strict_product": True, "reference_sha256": "reference"}
    check = {"identity": "same", "reference_sha256": "reference"}
    for version in (None, "reference-motion-v1"):
        assert not product_motion.eligible_identity(
            {"motion_check": {**check, "version": version}}, constraints
        )
    assert product_motion.eligible_identity(
        {"motion_check": {**check, "version": product_motion.VERSION}}, constraints
    )
