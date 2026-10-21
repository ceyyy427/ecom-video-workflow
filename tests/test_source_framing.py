"""Framing must retain real source pixels and remain an explicit, bounded edit."""

import subprocess

import pytest
from PIL import Image

from ecom_video.customer_api import ShotChanges
from ecom_video.remotion_renderer import prepare_source_video
from ecom_video.storyboard import Shot


def test_framing_is_explicit_and_bounded():
    assert Shot().model_dump()["source_framing"] == "original"
    assert Shot(source_framing="square").source_framing == "square"
    assert ShotChanges(source_framing="square").source_framing == "square"
    with pytest.raises(ValueError):
        Shot(source_framing="crop=1:1;movie=/private/file")


def test_prepared_square_uses_focus_and_keeps_product_pixels(tmp_path):
    im = Image.new("RGB", (800, 400), "white")
    # A real pixel target near the right edge; a centre-only crop would lose it.
    im.paste("#102030", (650, 120, 750, 280))
    image = tmp_path / "source.png"
    im.save(image)
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image),
            "-t",
            "0.3",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    scene = {"source_in": 0, "frames": 6, "source_framing": "square", "focus_x": 1, "focus_y": 0.5}
    target = tmp_path / "square.mp4"
    prepare_source_video(source, target, scene, lambda: None)
    frame = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(target),
            "-frames:v",
            "1",
            "-vf",
            "scale=100:100",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    p = Image.frombytes("RGB", (100, 100), frame)
    assert p.getpixel((75, 50))[0] < 40, "the right-hand product must survive framing"
    dimensions = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(target),
        ],
        text=True,
    ).strip()
    assert dimensions == "1080,1080"


def test_different_framing_cannot_share_prepared_media_name():
    from ecom_video.source_framing import media_suffix

    base = {"focus_x": 0.5, "focus_y": 0.5}
    assert media_suffix(base) == media_suffix({**base, "source_framing": "original"}) == ""
    square = {**base, "source_framing": "square"}
    assert media_suffix(square) != media_suffix(base)
    assert media_suffix(square) != media_suffix({**square, "focus_x": 1})


def test_legacy_filter_unchanged_and_images_reject_video_framing(tmp_path):
    from test_storyboard import draft

    from ecom_video.source_framing import crop_filter
    from ecom_video.storyboard import default_board, validate_board
    from ecom_video.storyboard_renderer import visual_filter

    shot = {"fit": "contain", "motion": "static", "focus_x": 0.5, "focus_y": 0.5}
    assert crop_filter(shot) == ""
    assert visual_filter(shot, False, 30) == visual_filter(
        {**shot, "source_framing": "original"}, False, 30
    )
    _, job = draft(tmp_path)
    board = default_board(job)
    board["shots"][0]["source_framing"] = "square"
    with pytest.raises(ValueError, match="方形取景仅支持视频"):
        validate_board(job, board)
    board["shots"][1]["source_framing"] = "square"
    board["shots"][0]["source_framing"] = "original"
    assert validate_board(job, board)["shots"][1]["source_framing"] == "square"


def test_framing_comparison_is_complete_read_only_and_unapproved(tmp_path, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ecom_video import sample_library

    folder = tmp_path / "samples" / "headphones"
    folder.mkdir(parents=True)
    for name in (
        "output.mp4",
        "parent.mp4",
        "retake.mp4",
        "poster.jpg",
        "shotbook.json",
        "subtitles.srt",
        "narration.wav",
        "framing.json",
    ):
        (folder / name).write_bytes(b"fixture")
    (folder.parent / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "style": "headphones",
                        "title": "取景修订",
                        "description": "待听审",
                        "duration": 23.1,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(sample_library, "FRAMING_LIBRARY", folder.parent, raising=False)
    app = FastAPI()
    app.include_router(sample_library.framing_router())
    with TestClient(app) as client:
        rows = client.get("/api/samples/framing").json()
        assert rows[0]["status"] == "needs_review" and "film" in rows[0]["review_required"]
        assert client.get("/api/samples/framing/headphones/video").content == b"fixture"
        assert client.get("/api/samples/framing/headphones/source").status_code == 404
        assert client.post("/api/samples/framing/headphones/video").status_code == 405
        (folder / "framing.json").unlink()
        assert client.get("/api/samples/framing").json() == []


def test_api_replacing_square_video_with_image_resets_implicit_crop(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path / "runtime")
    p = picture(c, project(c))
    base = f"/api/customer-projects/{p['id']}"
    image_id = p["media"][0]["id"]
    video = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=3",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    r = c.post(
        base + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("video.mp4", video.read_bytes(), "video/mp4")},
    )
    assert r.status_code == 201, r.text
    p = plan(c, prepare(c, approve(c, r.json())))
    job = p["job"]
    board = job["storyboard"]
    asset = next(a for a in job["assets"] if a["kind"] == "video")
    board["shots"][1].update(
        asset_id=asset["id"], motion="static", source_in=0, source_framing="square"
    )
    r = c.put(
        f"/api/jobs/{job['id']}/storyboard",
        json={"revision": job["storyboard_revision"], "board": board},
    )
    assert r.status_code == 200, r.text
    p = c.get(base).json()
    payload = lock_and_revision(c, p)
    payload["changes"] = {"media_id": image_id}
    r = c.post(base + "/revise-shot", json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["job"]["storyboard"]["shots"][1]["source_framing"] == "original"
    original = c.get(f"/api/jobs/{job['id']}").json()
    assert original["storyboard"]["shots"][1]["source_framing"] == "square"
