"""Real browser + FFmpeg P1 acceptance. Synthetic product data; no real product approval."""

import argparse
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    evidence = Path("docs/evidence/p1")
    evidence.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url) as c, sync_playwright() as pw:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.locator("#productMode").click()
        page.locator("#productTitle").fill("P1 合成验收随行杯 " + str(time.time_ns()))
        page.locator("#createProduct button").click()
        page.wait_for_selector("#productContent:not([hidden])")
        assert page.locator("#generateScript").is_disabled()
        page.locator("#productFile").set_input_files(
            {
                "name": "产品事实.txt",
                "mimeType": "text/plain",
                "buffer": "产品名称：随行杯\n容量：500mL\n材质：不锈钢\n使用前请阅读说明书".encode(),
            }
        )
        page.wait_for_function('()=>document.querySelectorAll("#factsList input").length===4')
        assert page.locator("#generateScript").is_disabled()
        for check in page.locator("#factsList input").all():
            check.check()
        page.locator("#factsReviewer").fill("测试产品负责人")
        page.locator("#factsNote").fill("合成资料，仅验证确认关口")
        page.locator("#factsChecked").check()
        page.locator("#confirmFacts").click()
        page.wait_for_function('()=>!document.querySelector("#generateScript").disabled')
        page.locator("#generateScript").click()
        page.wait_for_function('()=>document.querySelectorAll(".script-scene").length===6')
        pid = page.locator("#productSelect").input_value()
        page.locator("#factsList input").first.uncheck()
        assert page.locator("#generateScript").is_disabled()
        assert page.locator("#approveScript").is_disabled()
        page.locator("#factsList input").first.check()
        # An edited scene must be saved as a new version before approval.
        page.get_by_label("第 3 镜文案", exact=True).fill("杯子容量为500mL")
        assert page.locator("#approveScript").is_disabled()
        page.wait_for_timeout(2800)
        assert page.get_by_label("第 3 镜文案", exact=True).input_value() == "杯子容量为500mL"
        page.locator("#saveProductDraft").click()
        page.wait_for_function(
            '()=>document.querySelector("#draftMeta").textContent.includes("人工编辑")'
        )
        product = c.get("/api/products/" + pid).json()
        assert len(product["script_drafts"]) == 2
        assert product["script_drafts"][-1]["payload"][2]["attribution"] == "human_rewrite"
        page.screenshot(path=str(evidence / "product-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        page.screenshot(path=str(evidence / "product-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.locator("#scriptReviewer").fill("测试编辑")
        page.locator("#scriptNote").fill("仅测试确认表单，不构成真实商品审核")
        page.locator("#scriptChecked").check()
        page.locator("#approveScript").click()
        page.wait_for_selector("#jobProvenance:not([hidden])")
        assert page.locator("#script").is_disabled()
        jid = page.evaluate('localStorage.getItem("ecom.selected")')
        page.locator("#visualFiles").set_input_files(str(Path("var/smoke/product-1.png").resolve()))
        page.wait_for_function(
            '()=>document.querySelector("#assetCount").textContent.startsWith("1 /")'
        )
        page.locator("#seconds").fill("1")
        page.locator("#submit").click()
        page.wait_for_function(
            '()=>document.querySelector("#status").textContent==="待人工复核"', timeout=120000
        )
        assert page.locator("#downloads a").count() == 6
        page.reload()
        page.wait_for_selector("#video:not([hidden])")
        page.wait_for_function('()=>document.querySelector("#video").readyState>=2')
        page.locator("#video").evaluate("async(v)=>{v.muted=true;await v.play();}")
        page.wait_for_function('()=>document.querySelector("#video").currentTime>.5')
        page.locator("#video").evaluate("(v)=>v.pause()")
        page.screenshot(path=str(evidence / "render-desktop.png"), full_page=True)
        page.locator("#reviewer").fill("测试复核人")
        page.locator("#reviewNote").fill("合成输入的自动化界面测试")
        page.locator("#confirmed").check()
        page.locator('button[value="ready"]').click()
        page.wait_for_function('()=>document.querySelector("#status").textContent==="复核通过"')
        provenance = c.get(f"/api/jobs/{jid}/artifacts/provenance").json()
        assert provenance["script_approval"]["job_id"] == jid
        assert provenance["fact_review"]["reviewer"] == "测试产品负责人"
        # A new document invalidates facts/draft but leaves old video evidence intact.
        page.locator("#productMode").click()
        page.locator("#productFile").set_input_files(
            {"name": "补充.txt", "mimeType": "text/plain", "buffer": "新增型号：B".encode()}
        )
        page.wait_for_function(
            '()=>document.querySelector("#productStatus").textContent==="待确认事实"'
        )
        assert page.locator("#generateScript").is_disabled()
        assert c.get(f"/api/jobs/{jid}/artifacts/provenance").json() == provenance
        # Failed product selection never commits a different identity.
        other = c.post("/api/products", json={"title": "选择失败隔离测试"}).json()
        page.locator("#reloadProduct").click()
        page.wait_for_function(
            '(id)=>[...document.querySelector("#productSelect").options].some(o=>o.value===id)',
            arg=other["id"],
        )
        page.route(
            "**/api/products/" + other["id"],
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"fixture product disconnect"}',
            ),
            times=1,
        )
        page.locator("#productSelect").select_option(other["id"])
        page.wait_for_function(
            '()=>document.querySelector("#notice").textContent.includes("fixture product disconnect")'
        )
        assert page.locator("#productSelect").input_value() == pid
        assert not errors, errors
        report = {
            "passed": True,
            "fixture_only": True,
            "product_id": pid,
            "job_id": jid,
            "page_errors": errors,
            "checks": [
                "document_upload_parse",
                "facts_gate",
                "changed_fact_selection_requires_reconfirmation",
                "script_generation",
                "human_edit_new_version",
                "dirty_script_survives_poll",
                "script_gate",
                "provenance_locked",
                "ffmpeg_render",
                "six_downloads",
                "video_playback",
                "reload",
                "mobile_no_overflow",
                "final_review",
                "new_source_invalidates_confirmations",
                "old_provenance_immutable",
                "failed_product_selection_atomic",
            ],
        }
        (evidence / "browser.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
