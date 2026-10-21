"""Read-only media and Chromium acceptance of the three unapproved real-footage previews."""

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples/client-demo"
EVIDENCE = ROOT / "docs/evidence/client-demo"


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)


def main():
    rows = json.loads((OUT / "library.json").read_text())["samples"]
    assert {r["style"] for r in rows} == {"cinema", "social", "lab"}
    result = {"media": {}, "browser": {}, "review_state": "pending_not_customer_approval"}
    engines = set()
    for row in rows:
        style = row["style"]
        engines.add(
            json.loads((OUT / style / "manifest.json").read_text())["render"]["engine_hash"]
        )
        folder = OUT / style
        video = folder / "output.mp4"
        p = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(video),
                ]
            ).stdout
        )
        v = next(s for s in p["streams"] if s["codec_type"] == "video")
        a = next(s for s in p["streams"] if s["codec_type"] == "audio")
        duration = float(p["format"]["duration"])
        assert (v["width"], v["height"]) == (1080, 1920)
        assert v["r_frame_rate"] == "30/1" and int(v["nb_frames"]) == round(row["duration"] * 30)
        assert 20 <= duration <= 30 and abs(duration - row["duration"]) < 0.04
        assert a["codec_name"] == "aac" and a["sample_rate"] == "48000"
        loud = run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(video),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ]
        )
        metrics = json.loads(re.findall(r"\{[^{}]+\}", loud.stderr)[-1])
        assert -17.5 <= float(metrics["input_i"]) <= -14.5
        assert float(metrics["input_tp"]) <= -1.0
        preview = json.loads((folder / "preview-job.json").read_text())["snapshot"]
        assert preview["preview_only"] is True and not preview["provenance"]["approvals"]
        assert preview["alignment"]["review_state"] == "needs_review"
        assert all(a["kind"] == "video" for a in preview["assets"] if a["kind"] != "audio")
        for shot in preview["provenance"]["source_edits"]:
            for cut in shot["cuts"]:
                assert cut["source_out"] > cut["source_in"]
                if "6177758" in cut["source"]:
                    assert cut["source_out"] <= 8.5 + 0.001
        motion_frames = []
        for at in [0.6, 2.4]:
            raw = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    "crop=500:600:290:800,scale=100:120,format=gray",
                    "-f",
                    "rawvideo",
                    "-",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            motion_frames.append(np.frombuffer(raw, dtype=np.uint8).astype(float))
        motion_difference = float(np.abs(motion_frames[0] - motion_frames[1]).mean() / 255)
        assert motion_difference > 0.001, (style, "no measured motion in first-shot product region")
        result["media"][style] = {
            "duration": duration,
            "first_shot_product_roi_motion_MAD": motion_difference,
            "frames": int(v["nb_frames"]),
            "loudness": metrics,
            "semantic_shots": len(preview["storyboard"]["shots"]),
            "picture_cuts": sum(len(s["cuts"]) for s in preview["provenance"]["source_edits"]),
            "voice_provider": json.loads((folder / "voice-source.json").read_text())["provider"],
            "all_asr_match": [s["match"] for s in preview["alignment"]["sentences"]],
        }
        sheet = Image.new("RGB", (4 * 216, 2 * 404), "#ffffff")
        for i, at in enumerate([0.5, 1.5, 4.8, 8.5, 12.5, 16.5, 21, duration - 0.7]):
            frame = EVIDENCE / f"{style}-frame-{i}.jpg"
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(at),
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=216:384",
                    str(frame),
                ]
            )
            sheet.paste(Image.open(frame), ((i % 4) * 216, (i // 4) * 404 + 20))
            ImageDraw.Draw(sheet).text(
                ((i % 4) * 216 + 6, (i // 4) * 404 + 3), f"{at:.1f}s", fill="black"
            )
        sheet.save(EVIDENCE / f"{style}-contact.jpg")
    assert len(engines) == 1, "Three final films must use the same frozen rendering implementation"
    result["engine_hash"] = next(iter(engines))
    with tempfile.TemporaryDirectory(prefix="jianxu-client-browser-") as temp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, ECOM_QIANCHUAN_WRITES="0")
        with (EVIDENCE / "browser-server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ecom_video",
                    "--api-only",
                    "--data",
                    temp,
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    try:
                        if httpx.get(base + "/api/session", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("preview API unavailable")
                errors = []
                unexpected = []
                playback = {}
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True, args=["--autoplay-policy=no-user-gesture-required"]
                    )
                    page = browser.new_page(viewport={"width": 1440, "height": 1050})
                    page.on("pageerror", lambda e: errors.append(str(e)))

                    def route(r):
                        if r.request.method not in ("GET", "HEAD") or not r.request.url.startswith(
                            base + "/"
                        ):
                            unexpected.append(r.request.url)
                            r.abort()
                        else:
                            r.continue_()

                    page.route("**/*", route)
                    page.goto(base + "/samples")
                    expect(page.locator("#clientGallery article")).to_have_count(3)
                    for row in rows:
                        card = page.locator("#clientGallery article").filter(
                            has=page.get_by_role("heading", name=row["title"], exact=True)
                        )
                        expect(card).to_contain_text("待人工确认")
                        movie = card.locator("video")
                        movie.evaluate("v=>v.play()")
                        expect(movie).to_have_js_property("paused", False)
                        page.wait_for_function(
                            '(url)=>{const v=[...document.querySelectorAll("video")].find(v=>v.src===url);return v&&v.currentTime>.2}',
                            arg=base + "/api/samples/client/" + row["style"] + "/video",
                        )
                        playback[row["style"]] = movie.evaluate(
                            "v=>({time:v.currentTime,duration:v.duration,width:v.videoWidth,height:v.videoHeight})"
                        )
                        assert playback[row["style"]]["width"] == 1080
                        movie.evaluate("v=>v.pause()")
                        response = page.request.get(
                            base + "/api/samples/client/" + row["style"] + "/video",
                            headers={"Range": "bytes=0-1023"},
                        )
                        assert response.status == 206 and len(response.body()) == 1024
                    movies = page.locator("#clientGallery video")
                    movies.nth(0).evaluate("v=>v.play()")
                    movies.nth(1).evaluate("v=>v.play()")
                    expect(movies.nth(0)).to_have_js_property("paused", True)
                    movies.nth(1).evaluate("v=>v.pause()")
                    for i in range(3):
                        movies.nth(i).evaluate(
                            "v=>new Promise(resolve=>{v.addEventListener('seeked',()=>resolve(true),{once:true});v.currentTime=1.5;})"
                        )
                    for width in [1440, 390]:
                        page.set_viewport_size({"width": width, "height": 1050})
                        page.screenshot(path=str(EVIDENCE / f"gallery-{width}.png"), full_page=True)
                    with page.expect_download() as download:
                        page.locator("#clientGallery a").filter(
                            has_text="下载待审样片"
                        ).first.click()
                    download.value.save_as(Path(temp) / "download.mp4")
                    assert (Path(temp) / "download.mp4").stat().st_size == (
                        OUT / "cinema/output.mp4"
                    ).stat().st_size
                    assert not errors and not unexpected, (errors, unexpected)
                    result["browser"] = {
                        "cards": 3,
                        "page_errors": errors,
                        "unexpected_or_write_requests": unexpected,
                        "playback": playback,
                        "range_downloads": 3,
                        "attachment_download": True,
                        "exclusive_playback": True,
                        "widths": [1440, 390],
                    }
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
    (EVIDENCE / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
