import copy
import json

import pytest
from fastapi.testclient import TestClient

from ecom_video.api import create_app
from ecom_video.db import Conflict, Store
from ecom_video.storyboard import default_board, validate_board


def draft(tmp_path):
    store = Store(tmp_path / "workflow.db")
    j = store.create_job("分镜", "展示外观\n查看细节", 2)
    for aid, kind, meta in [("photo", "image", {}), ("clip", "video", {"duration": 6})]:
        store.add_asset(
            j["id"],
            {
                "id": aid,
                "name": aid,
                "path": aid,
                "kind": kind,
                "sha256": "hash",
                "size": 10,
                "metadata": meta,
            },
        )
    return store, store.get(j["id"])


def test_board_validates_owned_asset_and_source_bounds(tmp_path):
    s, j = draft(tmp_path)
    b = default_board(j)
    b["shots"][1].update(asset_id="clip", source_in=4, duration=2)
    assert validate_board(j, b)["shots"][1]["source_in"] == 4
    bad = copy.deepcopy(b)
    bad["shots"][0]["asset_id"] = "foreign"
    with pytest.raises(ValueError, match="素材"):
        validate_board(j, bad)
    bad = copy.deepcopy(b)
    bad["shots"][1]["source_in"] = 4.1
    with pytest.raises(ValueError, match="选段"):
        validate_board(j, bad)
    bad = copy.deepcopy(b)
    bad["shots"][0]["duration"] = float("nan")
    with pytest.raises(ValueError):
        validate_board(j, bad)
    bad = copy.deepcopy(b)
    bad["shots"].pop()
    with pytest.raises(ValueError):
        validate_board(j, bad)


def test_board_snapshot_concurrency_and_script_change(tmp_path):
    s, j = draft(tmp_path)
    b = default_board(j)
    saved = s.save_storyboard(j["id"], b, 0)
    assert saved["storyboard_revision"] == 1
    with pytest.raises(Conflict):
        s.save_storyboard(j["id"], b, 0)
    with pytest.raises(Conflict):
        s.remove_asset(j["id"], "photo")
    s.update_draft(j["id"], "分镜", "外观新文案\n查看细节", 2)
    assert s.get(j["id"])["storyboard"] is None
    with pytest.raises(Conflict):
        s.save_storyboard(j["id"], b, 1)
    new = s.get(j["id"])
    s.save_storyboard(j["id"], default_board(new), new["storyboard_revision"])
    queued = s.submit(j["id"])
    assert queued["snapshot"]["storyboard"]["shots"][0]["asset_id"] == "photo"
    with pytest.raises(Conflict):
        s.save_storyboard(j["id"], b, 3)


def test_strict_unknown_fields_and_audio_limits(tmp_path):
    _, j = draft(tmp_path)
    b = default_board(j)
    b["shots"][0]["text"] = "隐藏改写"
    with pytest.raises(ValueError):
        validate_board(j, b)
    b = default_board(j)
    b["narration"]["mode"] = "uploaded"
    with pytest.raises(ValueError):
        validate_board(j, b)


def test_board_api_requires_token_and_revision(tmp_path):
    c = TestClient(create_app(tmp_path), base_url="http://localhost")
    c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
    j = c.post("/api/jobs", json={"title": "样例", "script": "外观"}).json()
    response = c.get(f"/api/jobs/{j['id']}/storyboard")
    assert response.status_code == 200
    b = response.json()["board"]
    assert (
        c.put(f"/api/jobs/{j['id']}/storyboard", json={"board": b, "revision": 0}).status_code
        == 422
    )
    c.headers.pop("x-workflow-token")
    assert (
        c.put(f"/api/jobs/{j['id']}/storyboard", json={"board": b, "revision": 0}).status_code
        == 403
    )


def test_real_video_trim_and_motion(tmp_path):
    import subprocess

    from PIL import Image, ImageChops

    from ecom_video.media import digest, inspect_media
    from ecom_video.worker import Worker

    s = Store(tmp_path / "workflow.db")
    video = tmp_path / "colors.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=180x320:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=180x320:r=30:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
    )
    j = s.create_job("选段", "选取蓝色画面", 1)
    s.add_asset(
        j["id"],
        {
            "id": "v",
            "name": "v",
            "path": video.name,
            "kind": "video",
            "sha256": digest(video),
            "size": video.stat().st_size,
            "metadata": inspect_media(video, "video"),
        },
    )
    j = s.get(j["id"])
    b = default_board(j)
    b["shots"][0]["source_in"] = 1
    s.save_storyboard(j["id"], b, 0)
    s.submit(j["id"])
    Worker(tmp_path).run_once()
    j = s.get(j["id"])
    assert j["status"] == "needs_review", j["error"]
    output = tmp_path / next(a["path"] for a in j["artifacts"] if a["kind"] == "video")
    frame = tmp_path / "selected.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output), "-frames:v", "1", str(frame)],
        check=True,
    )
    pixel = Image.open(frame).getpixel((540, 960))
    assert pixel[2] > 180 and pixel[0] < 50
    manifest = json.loads((output.parent / "manifest.json").read_text())
    assert manifest["schema_version"] == 3
    assert manifest["scenes"][0]["source_in"] == 1
    # A textured still must actually change between two frames with push motion.
    photo = tmp_path / "pattern.png"
    im = Image.new("RGB", (540, 960), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(im)
    for x in range(0, 540, 50):
        draw.rectangle((x, 300, x + 20, 700), fill="blue")
    im.save(photo)
    j = s.create_job("运镜", "推进", 1)
    s.add_asset(
        j["id"],
        {
            "id": "i",
            "name": "i",
            "path": photo.name,
            "kind": "image",
            "sha256": digest(photo),
            "size": photo.stat().st_size,
            "metadata": inspect_media(photo, "image"),
        },
    )
    j = s.get(j["id"])
    b = default_board(j)
    b["shots"][0]["motion"] = "push"
    s.save_storyboard(j["id"], b, 0)
    s.submit(j["id"])
    Worker(tmp_path).run_once()
    j = s.get(j["id"])
    assert j["status"] == "needs_review", j["error"]
    out = tmp_path / next(a["path"] for a in j["artifacts"] if a["kind"] == "video")
    frames = []
    for i, t in enumerate(("0.1", "0.8")):
        f = tmp_path / f"motion{i}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", t, "-i", str(out), "-frames:v", "1", str(f)],
            check=True,
        )
        frames.append(Image.open(f).crop((200, 600, 850, 1300)))
    assert ImageChops.difference(*frames).getbbox() is not None


def test_audio_rules_and_local_voice_overflow(tmp_path):
    from PIL import Image

    from ecom_video.media import digest, inspect_media
    from ecom_video.storyboard import capabilities
    from ecom_video.worker import Worker

    s, j = draft(tmp_path)
    for aid in ("voice", "music"):
        s.add_asset(
            j["id"],
            {
                "id": aid,
                "name": aid,
                "path": aid,
                "kind": "audio",
                "sha256": "hash",
                "size": 1,
                "metadata": {"duration": 8},
            },
        )
    j = s.get(j["id"])
    b = default_board(j)
    with pytest.raises(ValueError, match="配音超过"):
        validate_board(j, b)
    b["shots"][0]["duration"] = 6
    b["music_id"] = "voice"
    with pytest.raises(ValueError, match="另一条"):
        validate_board(j, b)
    b["music_id"] = "music"
    assert validate_board(j, b)["music_id"] == "music"
    if not capabilities()["local_tts"]:
        pytest.skip("native macOS voice unavailable")
    image = tmp_path / "actual.png"
    Image.new("RGB", (100, 100)).save(image)
    j = s.create_job("配音不能截断", "这里是一句超过一秒钟的配音，请延长镜头时长。", 1)
    s.add_asset(
        j["id"],
        {
            "id": "actual",
            "name": "actual",
            "path": image.name,
            "kind": "image",
            "sha256": digest(image),
            "size": image.stat().st_size,
            "metadata": inspect_media(image, "image"),
        },
    )
    j = s.get(j["id"])
    b = default_board(j)
    b["narration"]["mode"] = "local"
    s.save_storyboard(j["id"], b, 0)
    s.submit(j["id"])
    Worker(tmp_path).run_once()
    result = s.get(j["id"])
    assert result["status"] == "failed"
    assert "配音需至少" in result["error"]
    assert result["artifacts"] == []


def test_clone_remaps_storyboard_assets_and_preserves_source_lock(tmp_path):
    from io import BytesIO

    from PIL import Image

    app = create_app(tmp_path)
    s = app.state.store
    provenance = {"script_approval": {"script_hash": "unused"}, "sources": []}
    j = s.create_job("来源脚本", "已确认的文案", 2, provenance=provenance)
    c = TestClient(app, base_url="http://localhost")
    c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
    f = BytesIO()
    Image.new("RGB", (100, 100)).save(f, format="PNG")
    j = c.post(
        f"/api/jobs/{j['id']}/assets",
        data={"kind": "image"},
        files={"file": ("a.png", f.getvalue())},
    ).json()
    b = default_board(j)
    s.save_storyboard(j["id"], b, 0)
    clone = c.post(f"/api/jobs/{j['id']}/clone").json()
    assert clone["storyboard"]["shots"][0]["asset_id"] == clone["assets"][0]["id"]
    assert clone["assets"][0]["id"] != j["assets"][0]["id"]
    assert clone["provenance"] == provenance
    assert (
        c.put(
            f"/api/jobs/{clone['id']}",
            json={"title": "来源脚本", "script": "绕过确认", "seconds": 2},
        ).status_code
        == 409
    )
    assert (
        c.put(
            f"/api/jobs/{clone['id']}/storyboard",
            json={"board": {**clone["storyboard"], "text": "绕过"}, "revision": 1},
        ).status_code
        == 422
    )


def test_chinese_caption_does_not_orphan_punctuation():
    from PIL import Image, ImageDraw, ImageFont

    from ecom_video.media import font_path
    from ecom_video.storyboard_renderer import caption_lines

    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1920)))
    font = ImageFont.truetype(str(font_path()), 64)
    text = "一只杯子，留一点日常的从容。"
    lines = caption_lines(text, draw, font)
    assert "".join(lines) == text
    assert all(line[0] not in "，。！？、；：" for line in lines)
    assert all(draw.textlength(line, font=font) <= 864 for line in lines)


def test_video_range_uses_picture_duration_not_longer_audio(tmp_path):
    import subprocess

    from ecom_video.media import inspect_media

    video = tmp_path / "short-picture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=180x320:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "3",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )
    meta = inspect_media(video, "video")
    assert meta["duration"] == pytest.approx(1, abs=0.04)
    s, j = draft(tmp_path)
    j["assets"][1]["metadata"] = meta
    board = default_board(j)
    board["shots"][1].update(asset_id="clip", duration=2)
    with pytest.raises(ValueError, match="选段"):
        validate_board(j, board)


def test_output_qc_rejects_missing_picture_frames(tmp_path):
    import subprocess

    from ecom_video.renderer import verify_output

    video = tmp_path / "short-output.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=1080x1920:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )
    with pytest.raises(ValueError):
        verify_output(video, 2, lambda: None)
