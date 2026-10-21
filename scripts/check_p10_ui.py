"""Read-only browser acceptance for reference and local cloud-config controls."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "docs/evidence/p10"
pid = json.loads((out / "opening/run.json").read_text())["project_id"]
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8765/create?project=" + pid)
    page.wait_for_function("()=>!document.querySelector('#work').disabled", timeout=120000)
    assert page.locator("#productReference").input_value()
    assert (
        page.locator("#strictProduct").is_checked() and page.locator("#actionTiming").is_checked()
    )
    page.locator("#volcVoiceState").wait_for(state="attached")
    assert page.locator("#volcVoiceGenerate").is_disabled()
    assert not page.locator("input[type=password]").count()
    assert page.locator("#productReference option").count() == 2
    page.screenshot(path=str(out / "intake-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(out / "intake-mobile.png"), full_page=True)
    assert not errors, errors
    (out / "ui-intake.json").write_text(
        json.dumps(
            {
                "url": page.url,
                "errors": errors,
                "reference_selected": True,
                "strict_product": True,
                "action_timing": True,
                "cloud_button_disabled_without_config": True,
                "mobile_no_overflow": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    browser.close()
