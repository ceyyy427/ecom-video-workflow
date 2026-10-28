"""Local browser regression for real D1 previews; read and idempotent planning only."""

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    from accept_domestic_suite import fingerprints
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    work = args.workspace.resolve()
    if not (work / ".domestic-content-acceptance").is_file():
        parser.error("only marked isolated acceptance")
    receipt = json.loads((work / "acceptance.json").read_text())
    before = fingerprints(work / "runtime/workflow.db")
    errors = []
    requests = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append((r.method, r.url)))
        for case in receipt["cases"]:
            pid = case["plan_id"]
            page.goto(f"http://127.0.0.1:{args.port}/ideas?plan={pid}")
            expect(page.locator("#ideaResults video")).to_have_count(6)
            expect(page.locator("#ideaPositioning")).to_be_visible()
            expect(page.locator("#ideaPublication summary")).to_be_visible()
            video = page.locator("#ideaResults video").first
            video.evaluate("async v=>{v.muted=true;await v.play()}")
            page.wait_for_function("v=>v.currentTime>.3", arg=video.element_handle())
            video.evaluate("v=>v.pause()")
            page.locator("#ideaDuration").select_option("20")
            for b in page.get_by_role("button", name="采用这个方向").all():
                expect(b).to_be_disabled()
            page.locator("#ideaDuration").select_option("26")
            page.get_by_role("button", name="生成六个动态预览").click()
            expect(page.locator("#ideaState")).to_contain_text("六个预览已完成", timeout=20000)
            for b in page.get_by_role("button", name="采用这个方向").all():
                expect(b).to_be_enabled()
            page.locator("#ideaPublication summary").click()
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
                page.screenshot(
                    path=str(work / f"ideas-{case['category']}-{width}.png"), full_page=True
                )
        browser.close()
    if errors or fingerprints(work / "runtime/workflow.db") != before:
        raise ValueError("browser errors or non-idempotent writes: " + str(errors))
    report = {
        "cases": len(receipt["cases"]),
        "viewports": [1440, 390],
        "video_playback": True,
        "dirty_inputs_disable_adoption": True,
        "repeated_submit_reuses_plan": True,
        "database_unchanged": True,
        "page_errors": errors,
        "approval_requests": sum(
            any(w in url for w in ["/confirm", "/review", "/adopt"])
            for method, url in requests
            if method == "POST"
        ),
        "external_requests": sum(
            not url.startswith(f"http://127.0.0.1:{args.port}/") for method, url in requests
        ),
    }
    if report["approval_requests"] or report["external_requests"]:
        raise ValueError("unexpected external or approval request")
    (work / "ui-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
