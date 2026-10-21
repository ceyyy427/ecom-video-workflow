"""Read-only published sample decode, HTTP/Range/download and actual browser playback."""

import json
import subprocess
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/script-readiness"


def main():
    film = ROOT / "examples/readiness-demo/headphones/output.mp4"
    info = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(film)]
        )
    )
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"], v["codec_name"]) == (
        1080,
        1920,
        "30/1",
        "h264",
    )
    assert (a["codec_name"], a["sample_rate"]) == ("aac", "48000")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(film), "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=90,
    )
    base = "http://127.0.0.1:8765"
    prefix = "/api/samples/readiness/headphones/"
    with httpx.Client(base_url=base, trust_env=False) as c:
        rows = c.get("/api/samples/readiness").json()
        assert len(rows) == 1 and rows[0]["status"] == "needs_review"
        for kind in (
            "video",
            "poster",
            "report",
            "audit",
            "script",
            "preflight",
            "selection",
            "shotbook",
            "subtitles",
        ):
            r = c.get(prefix + kind + "?download=true")
            assert r.status_code == 200 and "attachment" in r.headers["content-disposition"], kind
        assert c.get(prefix + "video", headers={"Range": "bytes=0-1023"}).status_code == 206
        assert c.get(prefix + "source").status_code == 404
    errors, writes = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "request", lambda r: writes.append(r.url) if r.method not in ("GET", "HEAD") else None
        )
        page.goto(base + "/samples#readinessExamples")
        expect(page.locator("#readinessGallery article")).to_have_count(1)
        video = page.locator("#readinessGallery video")
        video.evaluate("async v=>{v.muted=true;await v.play()}")
        page.wait_for_function("v=>v.currentTime>0", arg=video.element_handle())
        video.evaluate("v=>{v.pause();v.currentTime=3}")
        page.wait_for_function("v=>!v.seeking&&v.currentTime>=3", arg=video.element_handle())
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.locator("#readinessExamples").screenshot(path=str(OUT / f"gallery-{width}.png"))
        page.goto(base + prefix + "report")
        expect(page.locator("h1")).to_contain_text("待人工确认")
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        browser.close()
    assert not errors and not writes, (errors, writes)
    (OUT / "media-page.json").write_text(
        json.dumps(
            {
                "duration": float(info["format"]["duration"]),
                "size": [v["width"], v["height"]],
                "fps": v["r_frame_rate"],
                "full_decode": True,
                "download_and_range": True,
                "playback_and_seek": True,
                "standalone_html": True,
                "widths": [1440, 390],
                "page_errors": errors,
                "business_writes": writes,
                "status": "needs_review",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("Film decoded, gallery/report/Range/download and desktop/mobile playback passed")


if __name__ == "__main__":
    main()
