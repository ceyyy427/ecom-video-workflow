"""Read-only delivered UI, preserved gallery, and resumed customer project checks."""

import json
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402

OUT = ROOT / "docs/evidence/p8"
evidence = json.loads((OUT / "acceptance.json").read_text())
data = Path(evidence["first_video"]).parents[3]
server = uvicorn.Server(
    uvicorn.Config(create_app(data), host="127.0.0.1", port=8773, log_level="error")
)
threading.Thread(target=server.run, daemon=True).start()
try:
    while not server.started:
        time.sleep(0.05)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8765/")
        page.locator('a[href="/create"]').click()
        page.wait_for_function("()=>!document.querySelector('#projectControls').disabled")
        assert page.locator("#work").is_hidden()
        page.screenshot(path=str(OUT / "live-entry-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "live-entry-mobile.png"), full_page=True)
        page.goto("http://127.0.0.1:8765/samples")
        page.wait_for_function("()=>document.querySelectorAll('#sampleGallery video').length>=9")
        for v in page.locator("#sampleGallery video").all()[:3]:
            v.evaluate("v=>{v.load()}")
            info = v.evaluate(
                "v=>new Promise((resolve,reject)=>{const done=()=>resolve([v.videoWidth,v.videoHeight,v.duration]);if(v.readyState>=1)return done();v.onloadedmetadata=done;v.onerror=()=>reject('decode failed')})"
            )
            assert info[:2] == [1080, 1920] and 15 < info[2] < 25, info
        page.goto("http://127.0.0.1:8773/create?project=" + evidence["project_id"])
        page.wait_for_function(
            "()=>!document.querySelector('#projectControls').disabled", timeout=120000
        )
        assert page.locator(".customer-shot").count() == 3
        assert page.locator(".content-analysis").count() == 2
        assert page.get_by_label("第 2 镜识别片段", exact=True).count() == 1
        assert page.locator(".direction img").count() == 3
        assert all(
            i.evaluate("e=>e.complete&&e.naturalWidth>0")
            for i in page.locator(".direction img").all()
        )
        assert page.get_by_label("第 2 镜转场", exact=True).is_disabled()
        # Exercise the final poll message from an in-browser state only; no server write.
        page.evaluate("()=>{p.job.status='rendering';schedule()}")
        page.wait_for_function(
            "()=>document.querySelector('#message').textContent.includes('成片已生成')"
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "resumed-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator("#directions").screenshot(path=str(OUT / "directions.png"))
        assert not errors, errors
        result = {
            "main_entry": "ready",
            "gallery_films": 9,
            "p6_films_decode": 3,
            "resumed_project": evidence["project_id"],
            "saved_shots": 3,
            "styleframes_loaded": 3,
            "locked_transition": True,
            "completion_message": True,
            "390px_no_overflow": True,
            "browser_errors": errors,
        }
        (OUT / "delivery-browser.json").write_text(json.dumps(result, indent=2))
        print(result)
        browser.close()
finally:
    server.should_exit = True
