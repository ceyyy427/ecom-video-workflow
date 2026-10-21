import hashlib
import json
import shutil
import subprocess
import wave

import pytest
from PIL import Image

from ecom_video.audit import audit_script
from ecom_video.db import Store
from ecom_video.media import inspect_media, safe_path
from ecom_video.renderer import timeline
from ecom_video.worker import Worker


def test_audit_never_claims_legal_clearance():
    clean = audit_script("这款杯子采用蓝色外观")
    assert clean["status"] == "needs_review"
    assert clean["coverage"]["visual"] is False
    assert audit_script("能够根治疾病")["status"] == "blocked"
    assert audit_script("这就是最好的")["findings"][0]["severity"] == "review"


def test_timeline_preserves_text_and_bounds():
    scenes = timeline("展示外观\n介绍使用方法", 3, 5)
    assert scenes[0]["text"] == "展示外观"
    assert scenes[-1]["end"] == 5
    assert all(s["end"] > s["start"] for s in scenes)
    with pytest.raises(ValueError):
        timeline("第一段\n第二段\n第三段", 3, 1)


def test_media_validates_bytes_and_path(tmp_path):
    bad = tmp_path / "fake.png"
    bad.write_text("not an image")
    with pytest.raises(ValueError):
        inspect_media(bad, "image")
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../secret")
    with pytest.raises(ValueError):
        safe_path(tmp_path, "/etc/passwd")


def add_file(store, root, jid, path, kind):
    data = path.read_bytes()
    return store.add_asset(
        jid,
        {
            "id": path.stem + jid,
            "name": path.name,
            "path": str(path.relative_to(root)),
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "metadata": inspect_media(path, kind),
        },
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires real FFmpeg")
def test_real_mixed_media_render_and_review(tmp_path):
    store = Store(tmp_path / "workflow.db")
    image = tmp_path / "product.png"
    Image.new("RGB", (320, 480), "#a4cbda").save(image)
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    audio = tmp_path / "voice.wav"
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        f.writeframes(b"\x00\x00" * 16000 * 2)
    j = store.create_job("真实渲染测试", "展示杯身外观\n查看杯口细节", 1)
    for path, kind in ((image, "image"), (video, "video"), (audio, "audio")):
        add_file(store, tmp_path, j["id"], path, kind)
    store.submit(j["id"])
    assert Worker(tmp_path).run_once()
    result = store.get(j["id"])
    assert result["status"] == "needs_review", result["error"]
    files = {a["kind"]: safe_path(tmp_path, a["path"]) for a in result["artifacts"]}
    assert set(files) == {"video", "subtitles", "audit", "audit_html", "manifest", "qc"}
    qc = json.loads(files["qc"].read_text())
    assert qc["passed"] and qc["width"] == 1080 and qc["height"] == 1920
    assert qc["video_codec"] == "h264" and qc["audio_codec"] == "aac"
    manifest = json.loads(files["manifest"].read_text())
    assert manifest["timing"] == "estimated_by_text_weight"
    assert len(manifest["scenes"]) == 2
    assert len({x["asset_id"] for x in manifest["scenes"]}) == 2
    assert "展示杯身外观" in files["subtitles"].read_text()
    assert (
        store.review(j["id"], "ready", "测试员", "合成素材测试，不用于投放", True)["status"]
        == "ready"
    )


def test_blocked_script_produces_report_without_video(tmp_path):
    store = Store(tmp_path / "workflow.db")
    image = tmp_path / "product.png"
    Image.new("RGB", (100, 100)).save(image)
    j = store.create_job("风险", "根治疾病", 1)
    add_file(store, tmp_path, j["id"], image, "image")
    store.submit(j["id"])
    Worker(tmp_path).run_once()
    result = store.get(j["id"])
    assert result["status"] == "blocked"
    assert [a["kind"] for a in result["artifacts"]] == ["audit"]


def test_cancelled_command_terminates_real_child(tmp_path):
    import os
    import sys

    from ecom_video.media import run_checked

    pidfile = tmp_path / "child.pid"
    script = (
        "import os,time,pathlib; pathlib.Path("
        + repr(str(pidfile))
        + ").write_text(str(os.getpid())); time.sleep(30)"
    )

    def cancelled():
        if pidfile.exists():
            raise RuntimeError("cancel requested")

    with pytest.raises(RuntimeError, match="cancel requested"):
        run_checked([sys.executable, "-c", script], cancelled)
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_worker_shutdown_stops_claiming(tmp_path):
    worker = Worker(tmp_path)
    worker.shutdown.set()
    assert worker.run_once() is False


def test_anamorphic_video_keeps_display_aspect(tmp_path):
    store = Store(tmp_path / "workflow.db")
    video = tmp_path / "anamorphic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=720x576:d=1:r=30",
            "-vf",
            "setsar=16/15",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
    )
    jid = store.create_job("比例测试", "短字幕", 1)["id"]
    add_file(store, tmp_path, jid, video, "video")
    store.submit(jid)
    Worker(tmp_path).run_once()
    job = store.get(jid)
    assert job["status"] == "needs_review", job["error"]
    output = next(a for a in job["artifacts"] if a["kind"] == "video")
    frame = tmp_path / "frame.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(tmp_path / output["path"]),
            "-frames:v",
            "1",
            str(frame),
        ],
        check=True,
    )
    with Image.open(frame) as im:
        red_rows = [
            y for y in range(1920) if im.getpixel((20, y))[0] > 180 and im.getpixel((20, y))[1] < 80
        ]
    assert abs(len(red_rows) - 810) <= 4, f"Expected 4:3 content height ~810, got {len(red_rows)}"


def test_rule_loading_is_independent_of_os_text_encoding():
    import os
    import sys

    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}
    code = "from ecom_video.audit import audit_script; assert audit_script('plain text')['status'] == 'needs_review'"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
