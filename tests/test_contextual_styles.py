import copy

from ecom_video.creative import Brief, fingerprint, recommend, validate_creative


def product(script="透明杯里能看见咖啡的深浅。"):
    return {"title": "透明玻璃杯", "script": script, "assets": [{"sha256": "abc", "kind": "video"}]}


def test_context_changes_real_style_candidates_and_voice_not_only_labels():
    job = product()
    quiet = recommend(
        job,
        Brief(format="narrated", category="家居", audience="办公室喝咖啡的人", tone="安静自然温暖"),
    )
    young = recommend(
        job,
        Brief(format="narrated", category="家居", audience="年轻学生潮流人群", tone="活泼节奏运动"),
    )
    assert {s["id"] for s in quiet["options"]} != {s["id"] for s in young["options"]}
    assert any(s["id"] == "quiet" for s in quiet["options"])
    assert any(s["id"] == "kinetic" for s in young["options"])
    assert quiet == recommend(job, Brief(**quiet["brief"]))
    for rec in (quiet, young):
        assert len(rec["options"]) == len({s["family"] for s in rec["options"]}) == 3
        assert all(
            s["voice"]["direction"] and s["matched_inputs"]["气质"]
            for s in rec["options"]
            if s["id"] in ("quiet", "kinetic")
        )
        assert "相同输入结果稳定" in rec["method"]


def test_each_input_changes_basis_and_product_content_affects_ranking():
    job = product()
    brief = Brief(format="narrated", category="家居", audience="普通用户", tone="自然")
    initial = recommend(job, brief)
    for field, value in [("category", "数码"), ("audience", "年轻学生"), ("tone", "活泼节奏")]:
        changed = brief.model_copy(update={field: value})
        assert recommend(job, changed)["fingerprint"] != initial["fingerprint"]
    other = product("数码工具的接口功能细节，逐一观察讲解。")
    assert recommend(other, brief)["options"] != initial["options"]


def test_old_contextual_board_stays_valid_but_changed_inputs_do_not():
    from ecom_video.creative import DIRECTIONS

    j = product()
    brief = Brief(format="narrated", audience="年轻学生", tone="活泼节奏").model_dump()
    old = {"brief": brief, "fingerprint": fingerprint(j, brief), "style_id": DIRECTIONS[0]["id"]}
    assert validate_creative(j, old)["style_id"] == "cinema"
    new = recommend(j, brief)
    assert new["fingerprint"] != old["fingerprint"]
    chosen = {**old, "fingerprint": new["fingerprint"], "style_id": new["options"][0]["id"]}
    validate_creative(j, chosen)
    changed = copy.deepcopy(j)
    changed["script"] += "新增一句"
    import pytest

    with pytest.raises(ValueError, match="重新推荐"):
        validate_creative(changed, old)


def test_every_contextual_style_can_plan_with_server_voice_and_strict_contract():
    from ecom_video.creative import CATALOG
    from ecom_video.customer_api import Plan
    from ecom_video.voice_profiles import PROFILES
    from ecom_video.volc_voice_api import PreviewVoice

    for style in CATALOG:
        sid = style["id"]
        Plan(revision=0, job_id="j", board_revision=0, style_id=sid, fingerprint="a" * 64)
        PreviewVoice(
            revision=0,
            product_revision=0,
            draft_id="d",
            external_consent=True,
            style_id=sid,
            direction_basis="b" * 64,
        )
        assert PROFILES[sid]["speaker"] and -10 <= PROFILES[sid]["speech_rate"] <= 10


def test_contextual_customer_plan_and_stale_choice_gate(tmp_path):
    from test_customer import approve, client, picture, prepare, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = "/api/customer-projects/" + p["id"]
    settings = {
        **p["settings"],
        "brief": {
            "format": "showcase",
            "category": "家居",
            "audience": "办公室",
            "tone": "安静自然",
        },
    }
    p = c.put(base, json={"revision": p["revision"], "settings": settings}).json()
    p = prepare(c, p)
    rec = p["recommendations"]
    assert rec["version"] == 2
    assert rec["options"][0]["id"] == "quiet"
    body = {
        "revision": p["revision"],
        "job_id": p["job"]["id"],
        "board_revision": p["job"]["storyboard_revision"],
        "fingerprint": rec["fingerprint"],
        "style_id": "quiet",
    }
    saved = c.post(base + "/plan", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["job"]["storyboard"]["creative"]["style_id"] == "quiet"
    assert saved.json()["recommendations"]["version"] == 2
    p = saved.json()
    settings["brief"]["tone"] = "活泼节奏"
    changed = c.put(base, json={"revision": p["revision"], "settings": settings}).json()
    assert changed["direction_basis"] != p["direction_basis"]
    assert c.post(base + "/plan", json=body).status_code == 409


def test_inverted_brand_footage_caption_contrasts_with_actual_ink_plate():
    import base64
    import io

    from PIL import Image

    from ecom_video.subtitle_layout import prepare_captions

    captions = prepare_captions(
        {
            "style": "evidence",
            "treatment": "footage",
            "brand": {"ink": "#ffffff", "paper": "#000000", "subtitle_size": 60},
            "text": "字幕需要看清楚",
            "words": [],
            "voiceStart": 0,
            "voiceEnd": 3,
        }
    )
    im = Image.open(io.BytesIO(base64.b64decode(captions[0]["image"].split(",")[1]))).convert(
        "RGBA"
    )
    visible = [pixel for pixel in im.get_flattened_data() if pixel[3] > 200]
    assert visible and all(max(p[:3]) < 50 for p in visible)


def test_legacy_customer_revision_and_preview_keep_parent_policy(tmp_path, monkeypatch):
    from test_shot_voice import setup_project

    from ecom_video import remotion_renderer
    from ecom_video.creative import fingerprint

    c, p = setup_project(tmp_path, monkeypatch, legacy_context=True)
    base = "/api/customer-projects/" + p["id"]
    expected = {s["id"] for s in p["recommendations"]["options"]}
    seen = []

    def preview(job, root, rec):
        seen.append({s["id"] for s in rec["options"]})
        return {s["id"]: "fixture" for s in rec["options"]}

    monkeypatch.setattr(remotion_renderer, "style_previews", preview)
    assert c.post(base + "/direction-previews", json={"revision": p["revision"]}).status_code == 200
    assert seen == [expected]
    store = c.app.state.volc_voice.store
    with store.transaction() as db:
        db.execute("UPDATE jobs SET status='needs_review' WHERE id=?", (p["job"]["id"],))
    r = c.post(
        base + "/revise-shot",
        json={
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
            "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
            "request_id": "legacy-visual-revision-01",
            "changes": {"motion": "pull"},
        },
    )
    assert r.status_code == 201, r.text
    child = r.json()["job"]
    assert child["storyboard"]["creative"]["style_id"] == "social"
    assert child["storyboard"]["creative"]["fingerprint"] == fingerprint(
        child, p["settings"]["brief"]
    )
