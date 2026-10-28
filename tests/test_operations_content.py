"""D1 real planning: literal evidence, three narratives, old flow and human gates."""

import copy
from io import BytesIO

from PIL import Image
from test_customer import client


def request_body(**updates):
    value = {
        "brief": {
            "platform": "douyin",
            "objective": "product_showcase",
            "audience": "通勤与周末户外人群",
            "tone": "自然克制",
            "duration_s": 26,
            "content_brief": {
                "idea": "看清软壳衣的口袋和下摆",
                "subject": "藏蓝软壳衣",
                "mode": "footage",
                "audience": "通勤与周末户外人群",
                "tone": "自然克制",
                "facts": [
                    {"text": "藏蓝配色，拉链口袋。", "source": "客户资料"},
                    {"text": "下摆有抽绳，仅展示外观，非防水等级测试。", "source": "实拍资料"},
                ],
            },
        }
    }
    value["brief"].update(updates)
    return value


def material(mid="a" * 32, note="拉链口袋和下摆近景", **metadata):
    return {
        "id": mid,
        "origin": "upload",
        "name": "实拍.mp4",
        "sha256": "b" * 64,
        "kind": "video",
        "path": "unused-test.mp4",
        "source_in": 0,
        "source_note": "自有工程素材",
        "note": note,
        "metadata": {"duration": 20.0, "inspection_status": "unknown_or_stale", **metadata},
    }


def build(data=None, materials=None):
    from ecom_video.operations.contracts import SuiteBrief
    from ecom_video.operations.planner import plan_content
    from ecom_video.operations.resources import load_resources

    brief = SuiteBrief.model_validate((data or request_body())["brief"])
    return plan_content(
        brief,
        {"materials": materials or [], "source_state": "declared_unconfirmed"},
        load_resources(),
        engine="test-engine",
    )


def test_preview_windows_retain_complete_actions_and_use_distinct_ranges():
    from ecom_video.idea_media import source_windows

    a = material(
        complete_actions=[{"name": "开合", "start": 0, "end": 8, "basis": "manual_annotation"}]
    )
    p = build(materials=[a])
    for o in p["options"]:
        for scene, seconds in zip(o["scenes"][:2], o["preview_scene_seconds"], strict=True):
            if scene["material_id"]:
                source_windows(a, scene["source_in"], seconds)
    normal = build(materials=[material()])
    assert all(
        o["scenes"][0]["source_in"] != o["scenes"][1]["source_in"] for o in normal["options"]
    )


def test_hooks_do_not_invent_cutting_or_bottles_from_a_broad_category():
    for subject, fact, forbidden in [
        ("面霜补充袋", "袋装护肤品，外观为米白色。", ["瓶身"]),
        ("食品展示", "包装上有蓝色图案。", ["切开", "切面", "切片"]),
        ("短袖衣服", "黑色短袖。", ["外套", "口袋", "下摆"]),
    ]:
        d = request_body()
        d["brief"]["content_brief"].update(
            subject=subject, facts=[{"text": fact, "source": "工程事实"}]
        )
        p = build(d)
        assert all(not any(term in o["script"] for term in forbidden) for o in p["options"])


def test_reasons_explain_six_visual_structures_and_headlines_do_not_cut_words():
    p = build()
    assert len({o["reason"] for o in p["options"]}) == 6
    d = request_body(platform="xiaohongshu")
    d["brief"]["content_brief"].update(
        subject="棕色滴管瓶", facts=[{"text": "棕色瓶身，配黑色瓶盖。", "source": "实拍观察"}]
    )
    p = build(d)
    assert all("怎么搭" not in o["script"] for o in p["options"])
    scene = next(o for o in p["options"] if o["id"] == "blueprint")["scenes"][0]
    assert scene["headline"] == "看商品"


def test_new_planning_output_gets_new_identity_and_data_remains_evidence_bound(monkeypatch):
    import ecom_video.operations.planner as planner

    a = build()
    original = planner.script_for

    def revised(*args, **kwargs):
        rows = original(*args, **kwargs)
        rows[0]["text"] = "先看看这处细节。"
        return rows

    monkeypatch.setattr(planner, "script_for", revised)
    b = build()
    assert a["suite_plan"]["plan_id"] != b["suite_plan"]["plan_id"]
    data = request_body()
    data["brief"]["content_brief"]["data"] = [
        {"label": "工程数据", "value": 15, "unit": "件", "source": "仅验证数值门禁"}
    ]
    p = build(data)
    assert all(
        "data-0" in s["claim_ids"]
        for o in p["options"]
        if o["id"] == "dataviz"
        for s in o["scenes"]
    )
    assert all(
        not s["headline"] or s["headline"] in s["text"] or s["headline"] in p["subject"]
        for o in p["options"]
        for s in o["scenes"]
    )


def test_six_content_options_are_three_narratives_with_different_visual_and_story_rhythm():
    from ecom_video.operations.contracts import SuitePlan

    p = build(materials=[material()])
    assert p["version"] == "domestic-creative-v1"
    assert len(p["options"]) == len({o["id"] for o in p["options"]}) == 6
    assert {o["narrative"] for o in p["options"]} == {
        "product_showcase",
        "scenario_share",
        "detail_explain",
    }
    assert len({o["script"] for o in p["options"]}) == 6
    assert len({tuple(s["seconds"] for s in o["scenes"]) for o in p["options"]}) >= 3
    assert len({tuple(s["recipe"] for s in o["scenes"]) for o in p["options"]}) == 6
    assert all(abs(sum(s["seconds"] for s in o["scenes"]) - 26) < 0.04 for o in p["options"])
    assert p["approvals"] == [] and p["preview_seconds"] == 7
    assert SuitePlan.model_validate(p["suite_plan"]).six_options
    assert p["positioning"]["core_selling_point"]["text"] in [
        f["text"] for f in request_body()["brief"]["content_brief"]["facts"]
    ]


def test_fact_conditions_numbers_and_model_names_are_never_rewritten_or_invented():
    data = request_body()
    fact = "ECP33.21，容量1,000 ml；仅冷水条件下测试，不代表防水等级。"
    data["brief"]["content_brief"]["facts"] = [{"text": fact, "source": "说明书原文"}]
    p = build(data)
    by_id = {c["id"]: c["text"] for c in p["claims"]}
    for o in p["options"]:
        assert fact in o["script"]
        for s in o["scenes"]:
            if any(cid.startswith("fact-") for cid in s["claim_ids"]):
                assert any(
                    s["text"] == by_id[cid] or s["text"].endswith(by_id[cid])
                    for cid in s["claim_ids"]
                )
        assert all(
            phrase not in o["script"]
            for phrase in ["亲测", "全网最低", "绝对防水", "我穿了", "99%"]
        )
    assert p["data"] == []


def test_subject_audience_tone_platform_and_objective_change_recommendations():
    a = build(materials=[material()])
    for key, value in [
        ("audience", "准备周末轻食的人"),
        ("tone", "轻快、有冲击力"),
        ("platform", "xiaohongshu"),
        ("objective", "detail_explain"),
    ]:
        changed = build(request_body(**{key: value}), [material()])
        assert changed["basis"] != a["basis"]
        assert changed["options"] != a["options"]
    b = request_body()
    b["brief"]["content_brief"].update(
        subject="鲜橙",
        idea="展示鲜橙切面",
        facts=[{"text": "橙色果皮，切面可见。", "source": "许可实拍"}],
    )
    assert build(b)["options"] != a["options"]


def test_unknown_evidence_is_a_gap_and_known_visibility_and_actions_are_not_weakened():
    p = build(materials=[material()])
    assert any("人工" in gap or "未知" in gap for gap in p["missing"])
    assert all(o["feasibility"] != "verified" for o in p["options"])
    bad = material(
        verified_visible_ranges=[{"start": 0, "end": 1}],
        complete_actions=[{"name": "pour", "start": 0, "end": 20, "basis": "manual_annotation"}],
    )
    p = build(materials=[bad])
    assert all(o["feasibility"] == "needs_materials" for o in p["options"])
    assert all(s["material_id"] is None for o in p["options"] for s in o["scenes"][:2])
    no = build()
    assert all(o["feasibility"] == "code_diagram_only" for o in no["options"])
    assert any("图示" in g for g in no["missing"])


def test_platform_copy_is_draft_and_never_claims_platform_approval():
    from ecom_video.operations.content import make_publication_copy

    p = build()
    a = make_publication_copy(p, "douyin")
    b = make_publication_copy(p, "xiaohongshu")
    assert a["body"] != b["body"] and a["titles"] != b["titles"]
    for value in [a, b]:
        assert value["source_refs"] and value["rule_refs"] and value["status"] == "draft"
        assert value["cover_brief"] and value["tags"]
        assert "平台审核通过" not in str(value)


def test_operations_api_reuses_old_preview_queue_and_keeps_all_approvals_empty(tmp_path):
    c = client(tmp_path)
    body = request_body()
    r = c.post("/api/operations/plans", json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    assert c.post("/api/operations/plans", json=body).json()["id"] == p["id"]
    assert p["plan"]["suite_plan"]["plan_id"] == p["id"]
    assert c.get("/api/idea-plans/" + p["id"]).json() == p
    assert (
        c.post(f"/api/idea-plans/{p['id']}/previews", json={"basis": p["basis"]}).json()["status"]
        == "queued"
    )
    assert (
        c.post(
            f"/api/idea-plans/{p['id']}/adopt",
            json={"basis": p["basis"], "option_id": p["plan"]["options"][0]["id"]},
        ).status_code
        == 409
    )
    assert c.get("/api/customer-projects").json() == []
    old = c.post("/api/idea-plans", json={"idea": "旧版仍可使用"})
    assert old.status_code == 201 and old.json()["plan"]["version"] == "creative-plan-v1"
    assert c.post("/api/operations/plans", json={**body, "confirmed": True}).status_code == 422
    assert (
        c.post(
            "/api/operations/plans", json=body, headers={"origin": "https://other.test"}
        ).status_code
        == 403
    )
    c.headers.pop("X-Workflow-Token")
    assert c.post("/api/operations/plans", json=body).status_code == 403


def test_current_product_context_not_client_facts_is_used_and_stale_context_is_rejected(tmp_path):
    from test_customer import approve, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    body = request_body(
        project_id=p["id"],
        product_ref={"kind": "product", "id": p["id"], "revision": p["product"]["revision"]},
    )
    body["expected_project_revision"] = p["revision"]
    r = c.post("/api/operations/plans", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["plan"]["positioning"]["source_state"] == "confirmed_in_parent"
    claims = [v["text"] for v in r.json()["plan"]["claims"]]
    assert "藏蓝配色，拉链口袋。" not in claims
    body["expected_project_revision"] += 1
    assert c.post("/api/operations/plans", json=body).status_code == 409


def test_bound_facts_cannot_silently_use_a_different_products_media(tmp_path):
    from test_customer import approve, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    other = picture(c, project(c, "其他商品"))
    body = request_body(
        project_id=p["id"],
        product_ref={"kind": "product", "id": p["id"], "revision": p["product"]["revision"]},
    )
    body["expected_project_revision"] = p["revision"]
    body["brief"]["content_brief"]["materials"] = [
        {"origin": "customer", "project_id": other["id"], "id": other["media"][0]["id"]}
    ]
    assert c.post("/api/operations/plans", json=body).status_code == 409


def test_parent_context_is_rechecked_after_compilation(tmp_path, monkeypatch):
    from test_customer import approve, picture, project

    import ecom_video.operations.api as api
    from ecom_video.db import Store

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    body = request_body(
        project_id=p["id"],
        product_ref={"kind": "product", "id": p["id"], "revision": p["product"]["revision"]},
    )
    body["expected_project_revision"] = p["revision"]
    compile = api.plan_content

    def changed(*args, **kwargs):
        result = compile(*args, **kwargs)
        with Store(tmp_path / "workflow.db").transaction() as db:
            db.execute(
                "UPDATE customer_projects SET revision=revision+1 WHERE product_id=?", (p["id"],)
            )
        return result

    monkeypatch.setattr(api, "plan_content", changed)
    assert c.post("/api/operations/plans", json=body).status_code == 409
    with Store(tmp_path / "workflow.db").connect() as db:
        assert db.execute("SELECT COUNT(*) FROM idea_plans").fetchone()[0] == 0


def test_parent_color_lock_is_retained_and_cannot_be_replaced_by_request(tmp_path):
    from test_customer import approve, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    p = c.put(
        "/api/customer-projects/" + p["id"],
        json={
            "revision": p["revision"],
            "settings": {**p["settings"], "identity_lock": {"sku": "杯子A", "color": "奶白"}},
        },
    ).json()
    body = request_body(
        project_id=p["id"],
        product_ref={"kind": "product", "id": p["id"], "revision": p["product"]["revision"]},
    )
    body["expected_project_revision"] = p["revision"]
    result = c.post("/api/operations/plans", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["plan"]["source_context"]["identity_target"] == {
        "sku": "杯子A",
        "color": "奶白",
    }
    body["brief"]["sku_color_policy"] = {
        "product_id": p["id"],
        "mode": "single",
        "colors": ["红色"],
    }
    assert c.post("/api/operations/plans", json=body).status_code == 409


def test_capability_does_not_advertise_missing_or_damaged_resources(tmp_path, monkeypatch):
    import ecom_video.operations.api as api

    def damaged():
        raise ValueError("resource damaged")

    monkeypatch.setattr(api, "load_resources", damaged)
    cap = client(tmp_path).get("/api/operations/capabilities").json()
    assert cap["content_enabled"] is False


def test_material_ownership_and_actual_media_are_preserved_without_spurious_analysis(tmp_path):
    c = client(tmp_path)
    stream = BytesIO()
    Image.new("RGB", (120, 160), "navy").save(stream, format="PNG")
    a = c.post(
        "/api/idea-uploads",
        data={"source_note": "自制工程图", "usage_confirmed": "true"},
        files={"file": ("navy.png", stream.getvalue(), "image/png")},
    ).json()
    body = request_body()
    body["brief"]["content_brief"]["materials"] = [{"origin": "upload", "id": a["id"]}]
    r = c.post("/api/operations/plans", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["plan"]["materials"][0]["id"] == a["id"]
    explicit = copy.deepcopy(body)
    explicit["brief"]["content_brief"]["materials"][0]["source_in"] = 0.0
    same = c.post("/api/operations/plans", json=explicit)
    assert same.json()["id"] == r.json()["id"]
    for option in r.json()["plan"]["options"]:
        assert all(s["material_id"] == a["id"] for s in option["scenes"])
    bad = copy.deepcopy(body)
    bad["brief"]["content_brief"]["materials"][0] = {
        "origin": "customer",
        "id": a["id"],
        "project_id": "f" * 32,
    }
    assert c.post("/api/operations/plans", json=bad).status_code == 422
