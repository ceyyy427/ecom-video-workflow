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


def test_video_intake_route_uses_existing_video_upload_budget(tmp_path):
    from ecom_video.api import BodyLimit
    from ecom_video.media_intake import MAX_VIDEO_SOURCE

    # A Content-Length check must classify the new path like customer media, not JSON.
    calls = []

    async def app(scope, receive, send):
        calls.append("allowed")

    import asyncio

    async def check():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            calls.append(message.get("status"))

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/idea-uploads",
            "headers": [(b"content-length", str(MAX_VIDEO_SOURCE - 1).encode())],
        }
        await BodyLimit(app, tmp_path)(scope, receive, send)

    asyncio.run(check())
    assert calls == ["allowed"]


def test_freezing_project_media_survives_deleting_the_original_library_entry(tmp_path):
    from test_customer import picture, project

    from ecom_video.maintenance import backup
    from ecom_video.media import safe_path

    c = client(tmp_path)
    p = picture(c, project(c))
    a = p["media"][0]
    row = c.post(
        "/api/idea-plans",
        json={
            "idea": "用这张图讲清楚构图",
            "mode": "footage",
            "materials": [{"origin": "customer", "project_id": p["id"], "id": a["id"]}],
        },
    ).json()
    frozen = safe_path(tmp_path, row["plan"]["materials"][0]["path"])
    r = c.request(
        "DELETE",
        f"/api/customer-projects/{p['id']}/assets/{a['id']}",
        json={"revision": p["revision"]},
    )
    assert r.status_code == 200, r.text
    assert frozen.is_file()
    backup(tmp_path, tmp_path.parent / (tmp_path.name + "-backup"))
