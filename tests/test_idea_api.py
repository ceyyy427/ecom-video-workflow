from io import BytesIO

from PIL import Image
from test_customer import client


def test_plan_lifecycle_is_local_bounded_and_cannot_adopt_before_render(tmp_path):
    c = client(tmp_path)
    r = c.post(
        "/api/idea-plans",
        json={"idea": "让中学生看懂桥梁结构", "audience": "中学生", "tone": "清楚"},
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "draft" and len(p["plan"]["options"]) == 6
    assert c.get(f"/api/idea-plans/{p['id']}").status_code == 200
    base = f"/api/idea-plans/{p['id']}"
    assert (
        c.post(base + "/adopt", json={"basis": p["basis"], "option_id": "swiss-motion"}).status_code
        == 409
    )
    assert c.post(base + "/previews", json={"basis": "a" * 64}).status_code == 409
    assert c.post(base + "/previews", json={"basis": p["basis"]}).json()["status"] == "queued"
    assert c.delete(base + "/previews").json()["status"] == "cancelled"
    assert c.get(base + "/previews/../video").status_code != 200
    assert c.get("/api/customer-projects").json() == []
    c.headers.pop("X-Workflow-Token")
    assert c.post("/api/idea-plans", json={"idea": "不能跨站创建"}).status_code == 403


def test_upload_requires_usage_declaration_and_rejects_paths_and_code(tmp_path):
    c = client(tmp_path)
    image = BytesIO()
    Image.new("RGB", (80, 120), "#557861").save(image, format="PNG")
    files = {"file": ("sample.png", image.getvalue(), "image/png")}
    r = c.post(
        "/api/idea-uploads",
        data={"source_note": "许可工程图片", "usage_confirmed": "false"},
        files=files,
    )
    assert r.status_code == 422
    r = c.post(
        "/api/idea-uploads",
        data={"source_note": "自制测试图，仅工程验收", "usage_confirmed": "true"},
        files=files,
    )
    assert r.status_code == 201, r.text
    a = r.json()
    p = c.post(
        "/api/idea-plans",
        json={
            "idea": "展示这张图的构图",
            "mode": "footage",
            "materials": [{"origin": "upload", "id": a["id"], "source_in": 0}],
        },
    ).json()
    assert len(p["plan"]["materials"]) == 1
    for extra in [{"path": "/etc/passwd"}, {"code": 'fetch("https://example.test")'}]:
        assert c.post("/api/idea-plans", json={"idea": "非法输入", **extra}).status_code == 422
