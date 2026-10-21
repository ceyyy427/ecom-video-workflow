import json

import pytest
from test_customer import client, picture, project

from ecom_video import product_inspection, vision_model
from ecom_video.db import Store
from ecom_video.media_analysis import Analysis

MODEL = {"model": "fixture", "digest": "fixed", "provider": "fixture"}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    c = client(tmp_path)
    p = picture(c, project(c))
    pid = p["id"]
    mid = p["media"][0]["id"]
    p = c.put(
        "/api/customer-projects/" + pid,
        json={
            "revision": p["revision"],
            "settings": {
                **p["settings"],
                "strict_product": True,
                "material_checks": True,
                "product_reference_id": mid,
            },
        },
    ).json()
    monkeypatch.setattr(vision_model, "identity", lambda: MODEL)
    calls = []

    def observe(*a):
        calls.append("observe")
        return {
            "description": "杯身清晰",
            "subjects": ["玻璃杯"],
            "actions": [],
            "framing": "whole",
            "usable": True,
            "uncertainty": "",
        }

    monkeypatch.setattr(vision_model, "observe", observe)
    monkeypatch.setattr(product_inspection, "reference_subject", lambda *a: "cup")
    monkeypatch.setattr(
        product_inspection,
        "motion_state",
        lambda *a, **k: {
            "target_count": "one",
            "visibility": "full",
            "bbox": [0, 0, 900, 900],
            "flow": "absent",
            "lid": "unclear",
            "handling_lid": False,
        },
    )
    svc = Analysis(tmp_path, Store(tmp_path / "workflow.db"))
    svc.start(pid, mid)
    svc.run(svc.claim(), lambda: None)
    old = svc.get(pid, mid)
    return tmp_path, svc, pid, mid, old, calls


def test_completed_observations_reused_but_events_recomputed_and_history_unchanged(ready):
    root, svc, pid, mid, old, calls = ready
    svc.start(pid, mid, refresh=True)
    svc.run(svc.claim(), lambda: None)
    new = svc.get(pid, mid)
    assert calls == ["observe"]
    assert new["result"]["reused_observations_from"] == old["id"]
    assert new["result"]["segments"][0]["motion_check"]["events"] == []
    assert new["result"]["performance"]["model_cache"]["misses"] == 0
    with svc.store.connect() as db:
        stored = json.loads(
            db.execute("SELECT result FROM media_analyses WHERE id=?", (old["id"],)).fetchone()[0]
        )
    assert stored["analysis_id"] == old["id"] and "reused_observations_from" not in stored


@pytest.mark.parametrize("change", ["frame", "payload", "model", "force"])
def test_changed_provenance_or_forced_inference_does_not_reuse_complete_analysis(
    ready, monkeypatch, change
):
    root, svc, pid, mid, old, calls = ready
    if change == "frame":
        name = old["result"]["segments"][0]["frames"][0]
        (root / "analyses" / old["id"] / name).write_bytes(b"corrupt")
    if change == "payload":
        with svc.store.transaction() as db:
            db.execute(
                "UPDATE media_analyses SET result=json_set(result,'$.segments[0].observation.description','changed') WHERE id=?",
                (old["id"],),
            )
    if change == "model":
        monkeypatch.setattr(vision_model, "identity", lambda: {**MODEL, "digest": "new"})
    svc.start(pid, mid, refresh=True, force_inference=change == "force")
    svc.run(svc.claim(), lambda: None)
    new = svc.get(pid, mid)
    assert calls == ["observe", "observe"]
    assert "reused_observations_from" not in new["result"]


def test_force_inference_api_creates_a_new_explicit_request(ready):
    root, svc, pid, mid, old, _ = ready
    c = client(root)
    response = c.post(
        f"/api/customer-projects/{pid}/assets/{mid}/analysis", json={"force_inference": True}
    )
    assert response.status_code == 202
    row = response.json()
    assert row["id"] != old["id"] and row["result"]["force_inference"] is True


@pytest.mark.parametrize("running", [False, True])
def test_force_inference_replaces_an_already_queued_normal_request(ready, running):
    _, svc, pid, mid, _, _ = ready
    normal = svc.start(pid, mid, refresh=True)
    if running:
        claimed = svc.claim()
    forced = svc.start(pid, mid, force_inference=True)
    assert forced["id"] != normal["id"]
    assert forced["result"]["force_inference"] is True
    with svc.store.connect() as db:
        assert (
            db.execute("SELECT status FROM media_analyses WHERE id=?", (normal["id"],)).fetchone()[
                0
            ]
            == "cancelled"
        )
    if running:
        from ecom_video.db import Conflict

        with pytest.raises(Conflict):
            svc.progress(claimed)


@pytest.mark.parametrize("sealed", [True, False])
def test_previous_runtime_release_reuses_only_complete_sealed_evidence(ready, sealed):
    from ecom_video import current_observation_reuse as raw
    from ecom_video.creative import signature

    root, svc, pid, mid, old, calls = ready
    result = old["result"]
    result["engine"] = signature(
        {
            "model": MODEL,
            "scanner": "73e378380d2301f94d017d6038dad1e1e9ecc981ec3b26b62a9f4cf046a1db6c",
            "adapter": "c79ba22d4447964bd2352942aa55573ff27e1a7a9943bfa57a55557aab1277e6",
            "inspection": "65d8c37e463324067851406387781cb4516c4880ccb0d99e9a65b895a02845ab",
        }
    )
    if sealed:
        raw.seal(result, root / "analyses" / old["id"])
    else:
        result.pop("raw_manifest")
    with svc.store.transaction() as db:
        db.execute("UPDATE media_analyses SET result=? WHERE id=?", (json.dumps(result), old["id"]))
    svc.start(pid, mid, refresh=True)
    svc.run(svc.claim(), lambda: None)
    new = svc.get(pid, mid)
    assert (new["result"].get("reused_observations_from") == old["id"]) is sealed
    assert len(calls) == (1 if sealed else 2)
