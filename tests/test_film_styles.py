def test_all_styles_are_pinned_and_return_six_distinct_directions():
    from ecom_video.film_styles import catalog, recommend

    library = catalog()
    assert len(library) == 59
    out = recommend("给小学生解释太阳系", "小学生", "轻松、有好奇心", "code")
    assert len(out["options"]) == len({s["id"] for s in out["options"]}) == 6
    assert all(s["status"] == "reference" for s in out["options"])
    assert all("小学生" in s["adapted_prompt"] for s in out["options"])
    assert all("原片" in s["adapted_prompt"] for s in out["options"])
    assert all(len(s["source"]["commit"]) == 40 for s in out["options"])


def test_topic_changes_matching_and_reference_claims_are_not_inherited():
    from ecom_video.film_styles import recommend

    a = recommend("解释机械结构和工程原理", "工程师", "技术严谨", "code")
    b = recommend("温暖的睡前童话绘本", "儿童", "柔和水彩", "code")
    assert a["options"][0]["id"] != b["options"][0]["id"]
    assert a["basis"] != b["basis"]
    assert a["approvals"] == [] and b["approvals"] == []
    assert "事实" in a["options"][0]["adapted_prompt"]


def test_real_product_footage_prefers_editing_over_redrawn_geometry():
    from ecom_video.film_styles import recommend

    result = recommend("藏蓝衣服的口袋和泼水实拍", "通勤人群", "清楚自然", "footage")
    assert all(s["category"] in ("剪辑与纪实", "实证影像", "图形与排版") for s in result["options"])
    chosen = recommend("商品展示", mode="footage", preferred="paper-popup")
    assert chosen["options"][0]["id"] == "paper-popup"
    assert "不重绘商品" in chosen["options"][0]["adapted_prompt"]


def test_ideas_endpoint_is_same_origin_and_does_not_create_customer_jobs(tmp_path):
    from test_customer import client

    c = client(tmp_path)
    before = c.get("/api/jobs").json()
    r = c.post(
        "/api/film-styles/recommend",
        json={"idea": "解释机械结构", "audience": "学生", "tone": "清楚", "mode": "code"},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["options"]) == 6
    assert c.get("/api/jobs").json() == before
    assert c.get("/ideas").status_code == 200
    c.headers.pop("X-Workflow-Token")
    assert c.post("/api/film-styles/recommend", json={"idea": "test"}).status_code == 403
