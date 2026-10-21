"""Read-only media/HTTP/browser checks of the published, unapproved category examples."""

import json
import re
import subprocess
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/category-validation"
LIBRARY = ROOT / "examples/category-demo"


def main():
    media = {}
    for case in ["headphones", "serum"]:
        folder = LIBRARY / case
        versions = json.loads((folder / "versions.json").read_text())
        assert versions["selection_mode"] == "manual_after_local_proposals"
        assert versions["status"] == "needs_review"
        with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False) as c:
            rows = c.get("/api/samples/categories").json()
            assert len(rows) == 2 and all(r["status"] == "needs_review" for r in rows)
            base = "/api/samples/categories/" + case
            for kind in [
                "video",
                "parent",
                "shotbook",
                "subtitles",
                "recommendations",
                "selection",
            ]:
                r = c.get(base + "/" + kind + "?download=true")
                assert r.is_success and "attachment" in r.headers["content-disposition"]
            assert c.get(base + "/video", headers={"Range": "bytes=0-1023"}).status_code == 206
            assert c.get(base + "/source").status_code == 404
        films = {}
        for filename in ["parent.mp4", "output.mp4"]:
            path = folder / filename
            info = json.loads(
                subprocess.run(
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
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout
            )
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30/1")
            assert (a["codec_name"], a["sample_rate"]) == ("aac", "48000")
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-v",
                    "info",
                    "-i",
                    str(path),
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json",
                    "-f",
                    "null",
                    "-",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
            loud = json.loads(re.findall(r"\{[^{}]+\}", result.stderr)[-1])
            assert -17.5 <= float(loud["input_i"]) <= -14.5
            assert float(loud["input_tp"]) <= -1.0
            films[filename] = {
                "duration": float(info["format"]["duration"]),
                "frames": int(v["nb_frames"]),
                "loudness": loud,
                "decoded": True,
            }
        assert abs(films["output.mp4"]["duration"] - versions["duration"]) < 0.04
        media[case] = films
    errors, writes, played = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "request", lambda r: writes.append(r.url) if r.method not in ("GET", "HEAD") else None
        )
        page.goto("http://127.0.0.1:8765/samples#categoryExamples")
        cards = page.locator("#categoryGallery article")
        expect(cards).to_have_count(2)
        for card in cards.all():
            assert "人工回看" in card.inner_text()
            card.locator("summary").click()
            for player in card.locator("video,audio").all():
                player.evaluate("async e=>{await e.play()}")
                page.wait_for_timeout(150)
                assert player.evaluate("e=>e.readyState>=2&&e.duration>0&&!e.error")
                played.append(player.get_attribute("src"))
                player.evaluate("e=>e.pause()")
        for width in [1440, 390]:
            page.set_viewport_size({"width": width, "height": 1050})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.locator("#categoryExamples").scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / f"gallery-{width}.png"))
        browser.close()
    assert len(played) == 8 and not errors and not writes, (played, errors, writes)
    result = {
        "media": media,
        "players_started": len(played),
        "page_errors": errors,
        "business_or_platform_write_requests": writes,
        "widths": [1440, 390],
        "human_review": "pending",
        "stock_download_endpoint": "404",
    }
    (OUT / "gallery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
