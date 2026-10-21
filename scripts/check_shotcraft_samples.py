"""Read-only final media/HTTP/browser checks. Writes evidence, never business state."""

import hashlib
import json
import subprocess
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/shotcraft-integration"


def main():
    media = {}
    for case in ("headphones", "serum"):
        folder = ROOT / "examples/motion-demo" / case
        films, audio = {}, []
        for name in ("parent.mp4", "output.mp4", "retake.mp4"):
            path = folder / name
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            info = json.loads(result.stdout)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30/1")
            assert (a["codec_name"], a["sample_rate"]) == ("aac", "48000")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                capture_output=True,
                check=True,
                timeout=90,
            )
            pcm = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:a",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-f",
                    "s16le",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            audio.append(hashlib.sha256(pcm).hexdigest())
            films[name] = {
                "duration": float(info["format"]["duration"]),
                "frames": int(v["nb_frames"]),
                "decoded": True,
                "pcm_sha256": audio[-1],
            }
        assert len({f["frames"] for f in films.values()}) == 1
        assert len(set(audio)) == 1, "Visual recipes must not alter final audio in this fixture"
        media[case] = films
    base = "http://127.0.0.1:8765"
    with httpx.Client(base_url=base, trust_env=False) as client:
        rows = client.get("/api/samples/motion").json()
        assert len(rows) == 2 and all(r["status"] == "needs_review" for r in rows)
        for row in rows:
            for kind in ("video", "parent", "retake", "shotbook", "subtitles", "poster"):
                r = client.get(f"/api/samples/motion/{row['style']}/{kind}?download=true")
                assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
            assert (
                client.get(
                    f"/api/samples/motion/{row['style']}/video", headers={"Range": "bytes=0-1023"}
                ).status_code
                == 206
            )
            assert client.get(f"/api/samples/motion/{row['style']}/source").status_code == 404
    errors, writes, played = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "request", lambda r: writes.append(r.url) if r.method not in ("GET", "HEAD") else None
        )
        page.goto(base + "/samples#motionExamples")
        expect(page.locator("#motionGallery article")).to_have_count(2)
        for i in range(2):
            card = page.locator("#motionGallery article").nth(i)
            for j in range(2):
                if j:
                    card.locator("summary").click()
                video = card.locator("video").nth(j)
                video.evaluate("async v=>{v.muted=true;await v.play()}")
                page.wait_for_function(
                    "v=>v.currentTime>0", arg=video.element_handle(), timeout=15000
                )
                played.append(video.get_attribute("src"))
                video.evaluate("v=>{v.pause();v.currentTime=1.5}")
                page.wait_for_function(
                    "v=>!v.seeking&&v.readyState>=2&&v.currentTime>=1",
                    arg=video.element_handle(),
                    timeout=15000,
                )
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#motionExamples").screenshot(path=str(OUT / f"gallery-{width}.png"))
        browser.close()
    assert not errors and not writes, (errors, writes)
    (OUT / "media-page.json").write_text(
        json.dumps(
            {
                "media": media,
                "played": played,
                "page_errors": errors,
                "business_writes": writes,
                "widths": [1440, 390],
                "status": "needs_review",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        "Six films decoded; identical final audio; four players, download/Range, desktop/mobile passed"
    )


if __name__ == "__main__":
    main()
