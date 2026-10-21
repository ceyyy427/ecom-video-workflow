import copy
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from ecom_video.api import create_app


def client(root):
    c = TestClient(create_app(root), base_url="http://localhost")
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
    return c


def project(c, title="客户杯子"):
    r = c.post("/api/customer-projects", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def picture(c, p, role="product"):
    buf = BytesIO()
    Image.new("RGB", (160, 240), "#d6cdb9").save(buf, format="PNG")
    r = c.post(
        f"/api/customer-projects/{p['id']}/assets",
        data={"revision": p["revision"], "role": role},
        files={"file": ("产品.png", buf.getvalue(), "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def approve(c, p):
    base = f"/api/products/{p['id']}"
    product = c.get(base).json()
    product = c.post(
        base + "/documents",
        data={"revision": product["revision"]},
        files={"file": ("说明.txt", "奶白色杯身\n深色杯盖".encode(), "text/plain")},
    ).json()
    product = c.post(
        base + "/facts/confirm",
        json={
            "revision": product["revision"],
            "fact_ids": [f["id"] for f in product["facts"]],
            "reviewer": "测试负责人",
            "note": "自动fixture非真实客户审核",
            "confirmed": True,
        },
    ).json()
    product = c.post(base + "/scripts/generate", json={"revision": product["revision"]}).json()
    result = c.post(
        base + "/scripts/confirm",
        json={
            "revision": product["revision"],
            "draft_id": product["current_draft_id"],
            "reviewer": "测试编辑",
            "note": "自动fixture",
            "confirmed": True,
            "seconds": 2,
        },
    )
    assert result.status_code == 201, result.text
    return c.get(f"/api/customer-projects/{p['id']}").json()


def prepare(c, p):
    r = c.post(f"/api/customer-projects/{p['id']}/prepare", json={"revision": p["revision"]})
    assert r.status_code == 200, r.text
    return r.json()


def plan(c, p, style="cinema"):
    r = c.post(
        f"/api/customer-projects/{p['id']}/plan",
        json={
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
            "style_id": style,
            "fingerprint": p["recommendations"]["fingerprint"],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_confirm_prepare_and_plan_are_resumable(tmp_path):
    c = client(tmp_path)
    p = picture(c, project(c))
    base = f"/api/customer-projects/{p['id']}"
    assert c.post(base + "/prepare", json={"revision": p["revision"]}).status_code == 409
    p = prepare(c, approve(c, p))
    assert len(p["recommendations"]["options"]) == 3
    jid = p["job"]["id"]
    assert prepare(c, p)["job"]["id"] == jid
    p = plan(c, p)
    b = p["job"]["storyboard"]
    assert b["creative"]["style_id"] == "cinema" and not b["sample"]
    assert all(s["asset_id"] for s in b["shots"])
    assert b["narration"]["mode"] == "silent"
    assert c.get(base).json()["job"]["storyboard"] == b
    # A stale plan must not overwrite a manually edited board.
    assert (
        c.post(
            base + "/plan",
            json={
                "revision": p["revision"],
                "job_id": jid,
                "board_revision": 0,
                "style_id": "cinema",
                "fingerprint": p["recommendations"]["fingerprint"],
            },
        ).status_code
        == 409
    )


def test_new_material_invalidates_active_production_without_touching_old_job(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    old = copy.deepcopy(p["job"])
    p = picture(c, p, "detail")
    assert p["inputs_changed"] is True
    assert (
        c.post(
            f"/api/customer-projects/{p['id']}/submit",
            json={
                "revision": p["revision"],
                "job_id": old["id"],
                "board_revision": old["storyboard_revision"],
            },
        ).status_code
        == 409
    )
    fresh = prepare(c, p)
    assert fresh["job"]["id"] != old["id"]
    assert c.get("/api/jobs/" + old["id"]).json()["storyboard"] == old["storyboard"]


def test_foreign_assets_and_stale_library_edits_are_rejected(tmp_path):
    c = client(tmp_path)
    a = picture(c, project(c, "甲"))
    b = picture(c, project(c, "乙"))
    path = f"/api/customer-projects/{a['id']}/assets/{b['media'][0]['id']}"
    assert c.get(path).status_code == 404
    assert c.request("DELETE", path, json={"revision": a["revision"]}).status_code in (404, 405)
    r = c.put(
        f"/api/customer-projects/{a['id']}/assets/{a['media'][0]['id']}",
        json={"revision": a["revision"] - 1, "role": "detail", "source_in": 0, "note": ""},
    )
    assert r.status_code == 409


def test_single_shot_revision_is_idempotent_and_does_not_change_the_original(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    base = f"/api/customer-projects/{p['id']}"
    old = p["job"]
    shot = old["storyboard"]["shots"][1]
    # Render lock is enough to test immutable revision semantics without a fake render.
    r = c.post(
        base + "/submit",
        json={
            "revision": p["revision"],
            "job_id": old["id"],
            "board_revision": old["storyboard_revision"],
        },
    )
    assert r.status_code == 200, r.text
    c.post("/api/jobs/" + old["id"] + "/cancel")
    payload = {
        "revision": p["revision"],
        "job_id": old["id"],
        "board_revision": old["storyboard_revision"],
        "shot_id": shot["shot_id"],
        "request_id": "a" * 32,
        "changes": {"motion": "pan_left"},
    }
    r = c.post(base + "/revise-shot", json=payload)
    assert r.status_code == 201, r.text
    revised = r.json()["job"]
    assert revised["parent_id"] == old["id"]
    assert c.post(base + "/revise-shot", json=payload).json()["job"]["id"] == revised["id"]
    assert c.get("/api/jobs/" + old["id"]).json()["storyboard"] == old["storyboard"]
    for i, s in enumerate(revised["storyboard"]["shots"]):
        assert s["shot_id"] == old["storyboard"]["shots"][i]["shot_id"]
        if i != 1:
            assert s["motion"] == old["storyboard"]["shots"][i]["motion"]
    payload["changes"] = {"duration": 7}
    assert c.post(base + "/revise-shot", json=payload).status_code == 422


def audio(c, p, role="voice", seconds=12):
    import wave

    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * (16000 * seconds))
    r = c.post(
        f"/api/customer-projects/{p['id']}/assets",
        data={"revision": p["revision"], "role": role},
        files={"file": (role + ".wav", buf.getvalue(), "audio/wav")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def fixture_alignment(root, p, confirmed=True):
    """Synthetic timing fixture only, never a listening or ASR acceptance result."""
    import json
    import time
    import uuid

    from ecom_video.alignment import AlignmentService, input_hash
    from ecom_video.db import Store
    from ecom_video.local_asr import align

    store = Store(root / "workflow.db")
    job = p["job"]
    voice = next(a for a in job["assets"] if a["metadata"].get("customer_role") == "voice")
    lines = job["script"].splitlines()
    spacing = voice["metadata"]["duration"] / len(lines)
    result = align(
        job["script"],
        [
            {"text": line, "start": i * spacing + 0.2, "end": (i + 1) * spacing - 0.2}
            for i, line in enumerate(lines)
        ],
        voice["metadata"]["duration"],
    )
    aid = uuid.uuid4().hex
    with store.transaction() as db:
        db.execute(
            "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
            (
                aid,
                job["id"],
                input_hash(job, voice),
                "needs_review",
                json.dumps(result),
                None,
                None,
                time.time(),
                time.time(),
            ),
        )
    if confirmed:
        AlignmentService(root, store, recover=False).confirm(
            job["id"], aid, None, "AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL"
        )
    return aid


def narrated(c, p):
    settings = copy.deepcopy(p["settings"])
    settings["brief"]["format"] = "narrated"
    r = c.put(
        f"/api/customer-projects/{p['id']}", json={"revision": p["revision"], "settings": settings}
    )
    assert r.status_code == 200, r.text
    return r.json()


def plan_payload(p, alignment=None):
    return {
        "revision": p["revision"],
        "job_id": p["job"]["id"],
        "board_revision": p["job"]["storyboard_revision"],
        "style_id": "lab",
        "fingerprint": p["recommendations"]["fingerprint"],
        "alignment_id": alignment,
    }


def lock_and_revision(c, p):
    base = f"/api/customer-projects/{p['id']}"
    payload = {
        k: v for k, v in plan_payload(p).items() if k in ("revision", "job_id", "board_revision")
    }
    r = c.post(base + "/submit", json=payload)
    assert r.status_code == 200, r.text
    c.post("/api/jobs/" + p["job"]["id"] + "/cancel").raise_for_status()
    return {
        **payload,
        "shot_id": p["job"]["storyboard"]["shots"][1]["shot_id"],
        "request_id": "test-revision-000000001",
        "changes": {"motion": "pan_left"},
    }


def test_voice_confirmation_is_required_and_survives_visual_revision_only(tmp_path):
    c = client(tmp_path)
    p = narrated(c, audio(c, audio(c, picture(c, project(c)), "music")))
    p = prepare(c, approve(c, p))
    base = f"/api/customer-projects/{p['id']}"
    assert c.post(base + "/plan", json=plan_payload(p)).status_code == 422
    aid = fixture_alignment(tmp_path, p, False)
    assert c.post(base + "/plan", json=plan_payload(p, aid)).status_code == 422
    from ecom_video.alignment import AlignmentService
    from ecom_video.db import Store

    svc = AlignmentService(tmp_path, Store(tmp_path / "workflow.db"), recover=False)
    original_alignment = svc.confirm(
        p["job"]["id"], aid, None, "AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL"
    )
    r = c.post(base + "/plan", json=plan_payload(p, aid))
    assert r.status_code == 200, r.text
    p = r.json()
    board = p["job"]["storyboard"]
    assert board["music_id"] != board["narration"]["asset_id"]
    voice = next(a for a in p["job"]["assets"] if a["id"] == board["narration"]["asset_id"])
    assert voice["metadata"]["customer_role"] == "voice"
    assert abs(sum(s["duration"] for s in board["shots"]) - 12) < 0.04
    payload = lock_and_revision(c, p)
    r = c.post(base + "/revise-shot", json=payload)
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["alignment"]["id"] != aid
    assert new["alignment"]["reviewer"] == original_alignment["reviewer"]
    assert new["alignment"]["updated_at"] == original_alignment["updated_at"]
    assert new["alignment"]["result"]["inherited_from_alignment_id"] == aid
    # Changing the production brief invalidates the inherited basis.
    new = narrated(c, new)
    settings = copy.deepcopy(new["settings"])
    settings["brief"]["tone"] = "新气质"
    changed = c.put(base, json={"revision": new["revision"], "settings": settings}).json()
    assert not changed["visual_revision_allowed"]
    payload.update(
        revision=changed["revision"],
        job_id=changed["job"]["id"],
        request_id="different-request-key",
    )
    assert c.post(base + "/revise-shot", json=payload).status_code == 409


def test_new_visual_can_replace_one_shot_and_retries_do_not_move_active_job_back(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    payload = lock_and_revision(c, p)
    base = f"/api/customer-projects/{p['id']}"
    p = picture(c, p, "detail")
    payload.update(revision=p["revision"], changes={"media_id": p["media"][-1]["id"]})
    first = c.post(base + "/revise-shot", json=payload)
    assert first.status_code == 201, first.text
    first = first.json()
    chosen = first["job"]["storyboard"]["shots"][1]["asset_id"]
    assert (
        next(a for a in first["job"]["assets"] if a["id"] == chosen)["metadata"]["library_id"]
        == p["media"][-1]["id"]
    )
    second_payload = lock_and_revision(c, first)
    second_payload["request_id"] = "second-request-key-00"
    second = c.post(base + "/revise-shot", json=second_payload).json()
    replay = c.post(base + "/revise-shot", json=payload).json()
    assert replay["job"]["id"] == second["job"]["id"]
    assert replay["edit_result_job_id"] == first["job"]["id"]
    payload["changes"] = {"motion": "pull"}
    assert c.post(base + "/revise-shot", json=payload).status_code == 409


def test_music_is_not_narration_and_tampered_library_does_not_create_job(tmp_path):
    from ecom_video.storyboard import default_board

    c = client(tmp_path)
    p = approve(c, audio(c, picture(c, project(c)), "music"))
    prepared = prepare(c, p)
    assert default_board(prepared["job"])["narration"]["mode"] == "silent"
    board = plan(c, prepared)["job"]["storyboard"]
    assert board["music_id"] and board["narration"]["asset_id"] is None
    p = picture(c, prepared, "detail")
    (tmp_path / p["media"][-1]["path"]).write_bytes(b"tampered")
    r = c.post(f"/api/customer-projects/{p['id']}/prepare", json={"revision": p["revision"]})
    assert r.status_code == 409, r.text
    assert len(c.get(f"/api/customer-projects/{p['id']}").json()["versions"]) == 1


def test_planner_rejects_short_video_and_missing_review_evidence(tmp_path):
    import pytest

    from ecom_video.customer_planner import plan_board

    c = client(tmp_path)
    p = prepare(c, approve(c, picture(c, project(c))))
    j = copy.deepcopy(p["job"])
    j["assets"][0].update(kind="video")
    j["assets"][0]["metadata"].update(duration=2, source_in=1)
    with pytest.raises(ValueError, match="选段不足"):
        plan_board(j, p["settings"], "lab")
    # A still photo fallback remains a still photo; no invented video evidence.
    j["assets"].append({**copy.deepcopy(p["job"]["assets"][0]), "id": "fallback"})
    b, _ = plan_board(j, p["settings"], "lab")
    assert all(s["asset_id"] == "fallback" for s in b["shots"])
    j["assets"].append(
        {
            "id": "voice",
            "kind": "audio",
            "sha256": "voice",
            "metadata": {"duration": 12, "customer_role": "voice"},
        }
    )
    p["settings"]["brief"]["format"] = "review"
    n = len(j["script"].splitlines())
    with pytest.raises(ValueError, match="测评需要"):
        plan_board(
            j,
            p["settings"],
            "lab",
            {
                "id": "a" * 32,
                "status": "confirmed",
                "result": {"sentences": [{"start": i * 12 / n} for i in range(n)]},
            },
        )


def test_schema6_upgrade_preserves_legacy_job(tmp_path):
    import sqlite3
    from pathlib import Path

    from ecom_video.db import SCHEMA_VERSION, Store

    path = tmp_path / "workflow.db"
    with sqlite3.connect(path) as db:
        for f in sorted(Path("ecom_video/migrations").glob("*.sql"))[:6]:
            db.executescript(f.read_text())
        db.execute("PRAGMA user_version=6")
        db.execute(
            "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at) VALUES('legacy','old','看看外观',3,'draft',1,1)"
        )
    store = Store(path)
    assert store.get("legacy")["script"] == "看看外观"
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_customer_cannot_skip_style_and_listening_via_either_submit_endpoint(tmp_path):
    c = client(tmp_path)
    p = prepare(c, approve(c, audio(c, narrated(c, picture(c, project(c))))))
    payload = {
        k: v for k, v in plan_payload(p).items() if k in ("revision", "job_id", "board_revision")
    }
    assert c.post(f"/api/customer-projects/{p['id']}/submit", json=payload).status_code == 409
    assert c.post(f"/api/jobs/{p['job']['id']}/submit").status_code == 409
    assert c.get("/api/jobs/" + p["job"]["id"]).json()["status"] == "draft"


def test_single_shot_transition_cannot_change_adjacent_scene(tmp_path):
    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    payload = lock_and_revision(c, p)
    payload["changes"] = {"transition": "iris"}
    assert c.post(f"/api/customer-projects/{p['id']}/revise-shot", json=payload).status_code == 422
