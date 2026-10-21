"""Read-only browser acceptance of the actual model demo in the main app."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p8-live"
state = json.loads((OUT / "run.json").read_text())
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    url = "http://127.0.0.1:8765/create?project=" + state["project_id"]
    page.goto(url)
    page.wait_for_function(
        "()=>!document.querySelector('#projectControls').disabled", timeout=120000
    )
    assert page.locator(".customer-shot").count() == 5
    assert page.locator(".content-analysis").count() == 2
    assert page.get_by_label("第 3 镜识别片段", exact=True).count() == 1
    assert page.locator(".direction img").count() == 3
    assert all(
        i.evaluate("e=>e.complete&&e.naturalWidth>0") for i in page.locator(".direction img").all()
    )
    page.screenshot(path=str(OUT / "customer-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(OUT / "customer-mobile.png"), full_page=True)
    assert not errors, errors
    (OUT / "browser.json").write_text(
        json.dumps(
            {
                "url": url,
                "shots": 5,
                "analyses": 2,
                "styleframes": 3,
                "mobile_no_overflow": True,
                "errors": errors,
            },
            indent=2,
        )
    )
    browser.close()
