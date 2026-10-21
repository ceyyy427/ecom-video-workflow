"""Read-only smoke check of delivered films in the running local sample gallery."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 1080})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8765/samples")
    page.wait_for_function("document.querySelectorAll('#sampleGallery video').length >= 9")
    videos = page.locator("#sampleGallery video")
    assert page.locator("#sampleGallery article h2").all_text_contents()[:3] == [
        "P6 / 形与留白",
        "P6 / 桌边的一刻",
        "P6 / 先看细节",
    ]
    films = []
    for i in range(3):
        v = videos.nth(i)
        v.evaluate("v => {v.load();}")
        v.evaluate(
            "v => new Promise((resolve, reject) => {if(v.readyState>=1)return resolve();v.onloadedmetadata=resolve;v.onerror=()=>reject('video failed');})"
        )
        data = v.evaluate(
            "v => ({duration:v.duration, width:v.videoWidth, height:v.videoHeight, src:v.currentSrc})"
        )
        assert data["width"] == 1080 and data["height"] == 1920
        assert 15 <= data["duration"] <= 25
        v.evaluate("v => new Promise(resolve => {v.onseeked=resolve;v.currentTime=2;})")
        films.append(data)
    page.screenshot(path=str(ROOT / "docs/evidence/p6/gallery-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(ROOT / "docs/evidence/p6/gallery-mobile.png"), full_page=True)
    assert not errors
    (ROOT / "docs/evidence/p6/gallery.json").write_text(
        json.dumps({"films": films, "errors": errors, "mobile_overflow": False}, indent=2)
    )
    browser.close()
print("Three P6 films decode in the live gallery; desktop and mobile checks passed.")
