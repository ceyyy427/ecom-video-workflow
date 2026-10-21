"""Real isolated project UI: read-only coverage, film playback, report seek and responsive checks."""

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from ecom_video.api import create_app

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    data = ap.parse_args().data.resolve()
    receipt = json.loads((data / "acceptance.json").read_text())
    app = create_app(data / "runtime")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    errors, writes = [], []
    out = ROOT / "docs/evidence/script-readiness"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: (
                    writes.append(r.url)
                    if r.method not in ("GET", "HEAD") and not r.url.endswith("/direction-previews")
                    else None
                ),
            )
            page.route("**/direction-previews", lambda r: r.abort())
            page.goto(f"http://127.0.0.1:{port}/create?project={receipt['project_id']}")
            expect(page.locator(".direction")).to_have_count(3)
            expect(page.locator("#scriptScenes")).to_contain_text("镜头目的")
            page.locator("#checkMaterials").click()
            expect(page.locator("#materialReadiness")).to_contain_text("待补/待核对")
            expect(page.locator("#combinedAuditBody")).to_contain_text("画面文字OCR")
            expect(page.locator("#combinedAuditBody")).to_contain_text("素材授权 · 未检查")
            video = page.locator("#film")
            video.evaluate("async v=>{v.muted=true;await v.play()}")
            page.wait_for_function("v=>v.currentTime>0", arg=video.element_handle())
            video.evaluate("v=>v.pause()")
            seek = (
                page.locator("#combinedAuditBody").get_by_role("button", name="跳到此处核对").first
            )
            expect(seek).to_be_visible()
            seek.click()
            target = json.loads((data / "deliverables/audit.json").read_text())["findings"][0][
                "time"
            ]
            page.wait_for_function(
                "o=>Math.abs(o.v.currentTime-o.t)<.2&&!o.v.seeking",
                arg={"v": video.element_handle(), "t": target},
            )
            assert page.locator("#reviewPanel").is_visible()
            assert not page.locator("#filmChecked").is_checked()
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 1000})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(out / f"customer-{width}.png"), full_page=True)
                page.locator("#combinedAudit").screenshot(
                    path=str(out / f"audit-panel-{width}.png")
                )
                page.locator("#materialReadiness").screenshot(
                    path=str(out / f"material-panel-{width}.png")
                )
            browser.close()
        assert not errors and not writes, (errors, writes)
        (out / "customer-ui.json").write_text(
            json.dumps(
                {
                    "fixture": True,
                    "page_errors": errors,
                    "business_writes": writes,
                    "widths": [1440, 390],
                    "checks": [
                        "three_directions",
                        "script_intents",
                        "read_only_material_check",
                        "ocr_asr_unchecked_scope",
                        "actual_film_playback",
                        "seek_from_finding",
                        "final_review_unchecked",
                    ],
                    "style_previews": "deliberately aborted; not rendered",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print("Actual isolated customer page playback, coverage, seek and responsive checks passed")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
