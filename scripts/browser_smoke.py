"""Headless browser regression + actual UI creation, upload, render, reload and review.
Run against an isolated test service with --data var/browser-test; uses synthetic inputs.
"""

import argparse
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8766")
    p.add_argument("--fixtures", default="var/smoke")
    p.add_argument("--evidence", default="docs/evidence")
    args = p.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url) as c, sync_playwright() as pw:
        c.headers["X-Workflow-Token"] = c.get("/api/session").raise_for_status().json()["token"]
        suffix = str(time.time_ns())

        def create(label):
            return (
                c.post(
                    "/api/jobs",
                    json={"title": label + suffix, "script": label + "原文", "seconds": 1},
                )
                .raise_for_status()
                .json()
            )

        a, b = create("草稿A"), create("草稿B")
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url)
        page.locator(".job").filter(has_text=a["title"]).click()
        page.wait_for_function(
            '(text)=>document.querySelector("#script").value===text', arg=a["script"]
        )
        # Failed fetch must not commit the new selected ID before data arrives.
        page.route(
            "**/api/jobs/" + b["id"],
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"simulated disconnect"}',
            ),
            times=1,
        )
        page.locator(".job").filter(has_text=b["title"]).click()
        page.wait_for_function(
            '()=>document.querySelector("#notice").textContent.includes("simulated disconnect")'
        )
        page.locator("#script").fill("草稿A修改后")
        page.locator("#save").click()
        page.wait_for_function('()=>document.querySelector("#saveHint").textContent==="草稿已保存"')
        assert c.get("/api/jobs/" + b["id"]).json()["script"] == b["script"], (
            "Failed selection overwrote draft B"
        )
        assert c.get("/api/jobs/" + a["id"]).json()["script"] == "草稿A修改后"
        # Full user workflow via controls, never API shortcuts for generation/review.
        page.locator("#newJob").click()
        page.locator("#title").fill("浏览器验收示例" + suffix)
        page.locator("#script").fill("展示杯身整体外观\n查看杯口细节")
        page.locator("#seconds").fill("1")
        page.locator("#save").click()
        page.wait_for_function('()=>!document.querySelector("#visualFiles").disabled')
        page.locator("#visualFiles").set_input_files(
            [str(Path(args.fixtures).resolve() / f"product-{n}.png") for n in (1, 2)]
        )
        page.wait_for_function(
            '()=>document.querySelector("#assetCount").textContent.startsWith("2 /")'
        )
        page.locator("#script").fill("展示杯身整体外观\n查看杯口的细节")
        # Polling must preserve a dirty editor.
        page.wait_for_timeout(3000)
        assert page.locator("#script").input_value().endswith("杯口的细节")
        page.locator("#submit").click()
        page.wait_for_function(
            '()=>document.querySelector("#status").textContent==="待人工复核"', timeout=120000
        )
        page.reload()
        page.wait_for_selector("#video:not([hidden])")
        page.wait_for_function('()=>document.querySelector("#video").readyState>=2')
        page.locator("#video").evaluate("(v)=>{v.currentTime=.5;}")
        page.wait_for_function('()=>!document.querySelector("#video").seeking')
        page.locator("#video").evaluate("async (v)=>{v.muted=true;await v.play();}")
        page.wait_for_function('()=>document.querySelector("#video").currentTime>.8')
        page.locator("#video").evaluate("(v)=>v.pause()")
        assert page.locator("#video").evaluate("(v)=>v.videoWidth") == 1080
        assert page.locator("#downloads a").count() == 5
        page.screenshot(path=str(evidence / "workbench-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        page.screenshot(path=str(evidence / "workbench-mobile.png"), full_page=True)
        page.locator("#reviewer").fill("自动化测试专用")
        page.locator("#reviewNote").fill("仅验证人工复核表单，合成测试素材，不构成真实商品审核。")
        page.locator("#confirmed").check()
        page.locator('button[value="ready"]').click()
        page.wait_for_function('()=>document.querySelector("#status").textContent==="复核通过"')
        assert not errors, errors
        result = {
            "checks": [
                "failed_selection_is_atomic",
                "dirty_script_survives_poll",
                "create_upload_submit_render",
                "reload_restores_job",
                "five_downloads",
                "video_1080p",
                "video_playback",
                "mobile_no_overflow",
                "review_form",
            ],
            "page_errors": errors,
            "passed": True,
            "fixture_only": True,
        }
        (evidence / "browser.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
