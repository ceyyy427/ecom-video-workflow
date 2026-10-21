import json

from fastapi.testclient import TestClient

from ecom_video.api import create_app


def test_curated_previews_are_read_only_pending_review_and_only_serve_published_kinds(
    tmp_path, monkeypatch
):
    import ecom_video.sample_library as library

    folder = tmp_path / "library"
    (folder / "cinema").mkdir(parents=True)
    (folder / "cinema/output.mp4").write_bytes(b"fixture media bytes")
    (folder / "cinema/shotbook.json").write_text("{}")
    (folder / "library.json").write_text(
        json.dumps(
            {"samples": [{"style": "cinema", "duration": 26, "status": "ready", "title": "one"}]}
        )
    )
    monkeypatch.setattr(library, "LIBRARY", folder)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as client:
        rows = client.get("/api/samples/client").json()
        assert len(rows) == 1 and rows[0]["status"] == "needs_review"
        assert rows[0]["review_required"] == ["facts", "script", "style", "listening", "film"]
        r = client.get("/api/samples/client/cinema/video?download=true")
        assert r.status_code == 200 and r.content == b"fixture media bytes"
        assert "attachment" in r.headers["content-disposition"]
        assert client.get("/api/samples/client/cinema/source").status_code == 404
        assert client.get("/api/samples/client/unknown/video").status_code == 404
        assert client.get("/api/samples/client/cinema/narration").status_code == 404
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
        assert client.post("/api/samples/client/cinema/review").status_code in (404, 405)
        assert client.get("/api/jobs").json() == []


def test_missing_or_incomplete_or_symlinked_sample_is_not_published(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "library"
    folder.mkdir()
    monkeypatch.setattr(library, "LIBRARY", folder)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as client:
        assert client.get("/api/samples/client").json() == []
        (folder / "library.json").write_text(
            json.dumps({"samples": [{"style": "social", "duration": 25}]})
        )
        assert client.get("/api/samples/client").json() == []
        (folder / "social").mkdir()
        outside = tmp_path / "private.mp4"
        outside.write_bytes(b"private")
        (folder / "social/output.mp4").symlink_to(outside)
        assert client.get("/api/samples/client").json() == []
        assert client.get("/api/samples/client/social/video").status_code == 404


def test_contextual_library_keeps_pending_status_and_compares_parent_without_exposing_sources(
    tmp_path, monkeypatch
):
    import ecom_video.sample_library as library

    folder = tmp_path / "contextual"
    (folder / "quiet").mkdir(parents=True)
    (folder / "quiet/output.mp4").write_bytes(b"revised")
    (folder / "quiet/parent.mp4").write_bytes(b"parent")
    (folder / "quiet/old.wav").write_bytes(b"old")
    (folder / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": "quiet", "duration": 21.5, "title": "温暖慢叙", "status": "ready"}
                ]
            }
        )
    )
    monkeypatch.setattr(library, "CONTEXTUAL_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        rows = c.get("/api/samples/contextual")
        assert rows.status_code == 200
        assert rows.json()[0]["status"] == "needs_review"
        assert c.get("/api/samples/contextual/quiet/parent").content == b"parent"
        assert c.get("/api/samples/contextual/quiet/old").content == b"old"
        assert c.get("/api/samples/contextual/quiet/source").status_code == 404
        assert c.get("/api/jobs").json() == []


def test_category_library_is_read_only_with_fixed_product_ids(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "categories"
    (folder / "headphones").mkdir(parents=True)
    (folder / "headphones/output.mp4").write_bytes(b"edited fixture")
    (folder / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": "headphones", "title": "耳机", "duration": 20, "status": "ready"}
                ]
            }
        )
    )
    monkeypatch.setattr(library, "CATEGORY_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/categories")
        assert r.status_code == 200
        assert r.json()[0]["status"] == "needs_review"
        assert c.get("/api/samples/categories/headphones/video").content == b"edited fixture"
        assert c.get("/api/samples/categories/headphones/source").status_code == 404
        assert c.get("/api/samples/categories/kinetic/video").status_code == 404
        assert c.get("/api/jobs").json() == []


def test_motion_comparison_never_exposes_original_assets_or_claims_approval(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "motion"
    (folder / "serum").mkdir(parents=True)
    (folder / "serum/output.mp4").write_bytes(b"edited motion sample")
    (folder / "serum/parent.mp4").write_bytes(b"previous sample")
    (folder / "library.json").write_text(
        json.dumps(
            {"samples": [{"style": "serum", "title": "滴管瓶", "duration": 19, "status": "ready"}]}
        )
    )
    monkeypatch.setattr(library, "MOTION_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/motion")
        assert r.status_code == 200
        assert r.json()[0]["status"] == "needs_review"
        assert c.get("/api/samples/motion/serum/parent").content == b"previous sample"
        assert (
            c.get("/api/samples/motion/serum/video", headers={"Range": "bytes=0-5"}).status_code
            == 206
        )
        assert c.get("/api/samples/motion/serum/source").status_code == 404
        assert c.get("/api/samples/motion/serum/narration").status_code == 404
        assert c.get("/api/jobs").json() == []


def test_complete_narrative_gallery_requires_three_20_to_30_second_styles(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "narrative"
    folder.mkdir()
    rows = []
    for style, seconds in [("cinema", 26), ("social", 27), ("lab", 28)]:
        (folder / style).mkdir()
        (folder / style / "output.mp4").write_bytes(b"edited preview")
        rows.append({"style": style, "duration": seconds, "title": style, "status": "ready"})
    (folder / "library.json").write_text(json.dumps({"samples": rows}))
    monkeypatch.setattr(library, "NARRATIVE_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        result = c.get("/api/samples/narrative")
        assert result.status_code == 200
        assert len(result.json()) == 3 and all(r["status"] == "needs_review" for r in result.json())
        assert c.get("/api/samples/narrative/cinema/video").content == b"edited preview"
        assert c.get("/api/samples/narrative/cinema/source").status_code == 404
        assert c.get("/api/jobs").json() == []
        rows[2]["duration"] = 19
        (folder / "library.json").write_text(json.dumps({"samples": rows}))
        assert c.get("/api/samples/narrative").json() == []


def test_production_gallery_is_read_only_pending_and_does_not_expose_stock(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "production"
    (folder / "headphones").mkdir(parents=True)
    (folder / "headphones/output.mp4").write_bytes(b"edited film")
    (folder / "library.json").write_text(
        json.dumps({"samples": [{"style": "headphones", "duration": 24, "status": "ready"}]})
    )
    monkeypatch.setattr(library, "PRODUCTION_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/production")
        assert r.status_code == 200 and r.json()[0]["status"] == "needs_review"
        assert c.get("/api/samples/production/headphones/video").content == b"edited film"
        assert c.get("/api/samples/production/headphones/source").status_code == 404
        assert c.get("/api/jobs").json() == []


def test_readiness_example_exposes_frozen_report_without_approving_or_stock(tmp_path, monkeypatch):
    import ecom_video.sample_library as library

    folder = tmp_path / "readiness"
    (folder / "headphones").mkdir(parents=True)
    (folder / "headphones/output.mp4").write_bytes(b"edited film")
    (folder / "headphones/audit.html").write_text("<h1>pending review</h1>")
    (folder / "library.json").write_text(
        json.dumps({"samples": [{"style": "headphones", "duration": 25, "status": "ready"}]})
    )
    monkeypatch.setattr(library, "READINESS_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/readiness")
        assert r.status_code == 200 and r.json()[0]["status"] == "needs_review"
        assert c.get("/api/samples/readiness/headphones/report").status_code == 200
        assert c.get("/api/samples/readiness/headphones/source").status_code == 404
        assert c.get("/api/jobs").json() == []
