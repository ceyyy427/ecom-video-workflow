"""Real Chromium + FFmpeg + ZIP acceptance; all advertising data are synthetic."""

import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    evidence = Path("docs/evidence/p2")
    evidence.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=60) as c, sync_playwright() as pw:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        j = c.post(
            "/api/jobs", json={"title": "P2 合成验收杯子", "script": "展示杯子外观", "seconds": 1}
        ).json()
        jid = j["id"]
        image = io.BytesIO()
        Image.new("RGB", (600, 800), "#7da2b0").save(image, format="PNG")
        r = c.post(
            f"/api/jobs/{jid}/assets",
            data={"kind": "image"},
            files={"file": ("cup.png", image.getvalue(), "image/png")},
        )
        r.raise_for_status()
        c.post(f"/api/jobs/{jid}/submit").raise_for_status()
        deadline = time.monotonic() + 60
        while True:
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] == "needs_review":
                break
            assert j["status"] not in ("failed", "blocked"), j
            assert time.monotonic() < deadline
            time.sleep(0.2)
        c.post(
            f"/api/jobs/{jid}/review",
            json={
                "decision": "ready",
                "reviewer": "合成验收人员",
                "note": "仅测试视频，不对真实产品作背书",
                "confirmed": True,
            },
        ).raise_for_status()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url + "/distribution")
        page.get_by_text("添加账户", exact=True).click()
        page.locator("#accountName").fill("合成验收千川账户")
        advertiser = str(time.time_ns())
        page.locator("#advertiser").fill(advertiser)
        page.locator("#accountForm button").click()
        page.wait_for_function('()=>document.querySelector("#account").value.length>0')
        aid = page.locator("#account").input_value()
        page.locator("#job").select_option(jid)
        page.locator("#planName").fill("杯子推广 · 合成验收")
        page.locator("#budget").fill("200.00")
        page.locator("#targetRoi").fill("1.5")
        page.locator("#taskForm button").click()
        page.wait_for_selector("#taskDialog[open]")
        assert page.locator("#approvalForm").is_visible()
        page.locator("#approver").fill("测试确认人")
        page.locator("#approvalNote").fill("已核对模拟账户、视频和意向预算")
        page.locator("#approvalCheck").check()
        page.locator("#approvalForm button").click()
        page.wait_for_selector("#packageLink:not([hidden])", timeout=15000)
        sid = page.locator("#packageLink").get_attribute("href").split("/")[-2]
        package = c.get(f"/api/distribution/tasks/{sid}/package")
        package.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            video = archive.read("video.mp4")
            assert (
                hashlib.sha256(video).hexdigest()
                == next(a for a in j["artifacts"] if a["kind"] == "video")["sha256"]
            )
            assert {"video.mp4", "投放确认.json", "操作说明.txt", "audit.json", "qc.json"}.issubset(
                archive.namelist()
            ), archive.namelist()
        page.locator("#adId").fill("9991234567890123456")
        page.locator("#receiptActor").fill("测试投放人")
        page.locator("#receiptNote").fill("合成回执，未创建真实平台广告")
        page.locator("#receiptCheck").check()
        page.locator("#receiptForm button").click()
        page.wait_for_function(
            '()=>document.querySelector("#taskSummary").textContent.includes("已登记提交回执")'
        )
        page.screenshot(path=str(evidence / "approval-receipt.png"), full_page=False)
        page.get_by_role("button", name="关闭任务详情").click()
        page.locator("#startDate").fill("2026-10-01")
        page.locator("#endDate").fill("2026-10-02")
        page.get_by_text("导入平台 CSV 报表", exact=True).click()
        csv = (
            "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"
            "2026-10-01,8881234567890123456,100,1000,40,4,300,500,100\n"
            "2026-10-02,8881234567890123456,200,2000,60,6,500,1000,200\n"
        ).encode()
        page.locator("#reportFile").set_input_files(
            {"name": "synthetic.csv", "mimeType": "text/csv", "buffer": csv}
        )
        page.locator("#importActor").fill("合成数据验收")
        page.locator("#importCheck").check()
        page.locator("#importForm button").click()
        page.wait_for_function(
            '()=>document.querySelector("#kpis").textContent.includes("2.666667")'
        )
        assert page.locator("#materialRows tr").count() == 1
        page.get_by_text("关联平台素材与本地成片", exact=True).click()
        page.locator("#materialId").fill("8881234567890123456")
        page.locator("#bindingJob").select_option(jid)
        page.locator("#bindingActor").fill("测试核验人")
        page.locator("#bindingCheck").check()
        page.locator("#bindingForm button").click()
        page.wait_for_function(
            '(id)=>document.querySelector("#materialRows").textContent.includes(id)', arg=jid[:8]
        )
        page.locator("#review").scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / "dashboard-desktop.png"), full_page=True)
        query = {"account_id": aid, "start_date": "2026-10-01", "end_date": "2026-10-02"}
        report = c.get("/api/reports/export", params=query).json()
        assert report["totals"]["spend"] == "300" and report["ratios"]["ctr"] == "0.033333"
        assert report["status"] == "complete"
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(evidence / "dashboard-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1")
        assert not errors, errors
        (evidence / "browser-result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "evidence_class": "synthetic_data_real_ffmpeg_browser",
                    "job_id": jid,
                    "task_id": sid,
                    "account_id": aid,
                    "video_sha256": hashlib.sha256(video).hexdigest(),
                    "zip_bytes": len(package.content),
                    "dashboard": report,
                    "browser_errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        browser.close()
        print(
            "P2 real FFmpeg → human approval → ZIP → manual receipt → CSV → dashboard → binding: PASS (synthetic account/data; no platform writes)"
        )


if __name__ == "__main__":
    main()
