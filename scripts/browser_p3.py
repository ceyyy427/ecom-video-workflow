"""Real Chromium + FFmpeg; all OAuth/platform responses are injected fixtures.
No provider network is available to this harness; no real credentials are used.
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import uvicorn
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_qianchuan_auth import MemorySecrets  # noqa: E402
from test_qianchuan_tasks import NativeFixture  # noqa: E402

from ecom_video.api import create_app  # noqa: E402
from ecom_video.platform_worker import tick  # noqa: E402
from ecom_video.qianchuan_auth import QianchuanAuth  # noqa: E402
from ecom_video.qianchuan_tasks import QianchuanTasks  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402


def main():
    evidence = ROOT / "docs/evidence/p3"
    evidence.mkdir(parents=True, exist_ok=True)
    os.environ["ECOM_QIANCHUAN_WRITES"] = "1"  # fixture process only
    with tempfile.TemporaryDirectory(prefix="p3-browser-") as folder:
        root = Path(folder)
        app = create_app(root)
        store = app.state.store
        provider = NativeFixture()
        auth = QianchuanAuth(root, store, secrets=MemorySecrets(), provider=provider)
        auth.configure(
            "99", "fixture-secret", "http://127.0.0.1:8767/api/qianchuan/oauth/callback", "1000"
        )
        service = QianchuanTasks(root, store, auth=auth)
        app.state.qianchuan = service
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=8767, access_log=False, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(0.05)
            with (
                httpx.Client(base_url="http://127.0.0.1:8767", timeout=60) as c,
                sync_playwright() as pw,
            ):
                c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
                c.post(
                    "/api/distribution/accounts",
                    json={
                        "name": "P3 合成验收账户",
                        "platform": "qianchuan",
                        "advertiser_id": "123",
                    },
                ).json()["id"]
                jid = c.post(
                    "/api/jobs",
                    json={"title": "P3 合成验收杯子", "script": "展示杯子外观", "seconds": 1},
                ).json()["id"]
                art = io.BytesIO()
                Image.new("RGB", (600, 800), "#7da2b0").save(art, format="PNG")
                c.post(
                    f"/api/jobs/{jid}/assets",
                    data={"kind": "image"},
                    files={"file": ("cup.png", art.getvalue(), "image/png")},
                ).raise_for_status()
                c.post(f"/api/jobs/{jid}/submit").raise_for_status()
                Worker(root).run_once()
                assert c.get(f"/api/jobs/{jid}").json()["status"] == "needs_review"
                c.post(
                    f"/api/jobs/{jid}/review",
                    json={
                        "decision": "ready",
                        "reviewer": "测试人",
                        "note": "合成视频测试，不对真实产品背书",
                        "confirmed": True,
                    },
                ).raise_for_status()
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto("http://127.0.0.1:8767/qianchuan")
                page.wait_for_function(
                    '()=>document.querySelector("#authStatus").textContent.includes("尚未授权")'
                )
                page.locator("#authorize").click()
                page.wait_for_selector("#oauthLink:not([hidden])")
                state = parse_qs(urlparse(page.locator("#oauthLink").get_attribute("href")).query)[
                    "state"
                ][0]
                response = c.get(
                    "/api/qianchuan/oauth/callback",
                    params={"state": state, "auth_code": "fixture-code"},
                    headers={"sec-fetch-site": "cross-site"},
                )
                assert response.status_code == 303
                page.locator("#refresh").click()
                page.wait_for_function(
                    '()=>document.querySelector("#authStatus").textContent.includes("广告主已授权")'
                )
                page.locator("#job").select_option(jid)
                for key, value in {
                    "name": "P3 确认门测试",
                    "product": "333",
                    "aweme": "444",
                    "title": "展示杯子外观",
                    "budget": "100",
                    "roi": "1.5",
                }.items():
                    page.locator("#" + key).fill(value)
                page.locator("#aigc").select_option("false")
                page.locator("#draftForm button").click()
                page.wait_for_selector("#detail[open]")
                assert provider.uploads == provider.creates == 0
                page.locator("#reviewer").fill("测试确认人")
                page.locator("#note").fill("仅确认合成素材上传")
                page.locator("#confirmed").check()
                page.locator("#submitConsent").click()
                page.wait_for_function(
                    '()=>document.querySelector("#taskTitle").textContent.includes("上传排队中")'
                )
                assert provider.uploads == 0
                tick(root, store, native=service)
                assert provider.uploads == 1 and provider.creates == 0
                page.locator("#detail .close").click()
                page.locator("#refresh").click()
                page.get_by_role("button", name="查看 / 确认").click()
                page.wait_for_selector("#recheck:not([hidden])")
                page.locator("#recheck").click()
                page.wait_for_function('()=>!document.querySelector("#recheck").disabled')
                tick(root, store, native=service)
                page.locator("#detail .close").click()
                page.locator("#refresh").click()
                page.get_by_role("button", name="查看 / 确认").click()
                page.wait_for_function(
                    '()=>document.querySelector("#taskTitle").textContent.includes("待确认创建广告")'
                )
                assert provider.creates == 0
                assert "累计消费上限" in page.locator("#consentLabel").inner_text()
                assert "支付 ROI" in page.locator("#consentLabel").inner_text()
                assert "SCHEDULE_FROM_NOW" in page.locator("#payload").inner_text()
                page.screenshot(path=str(evidence / "approval-desktop.png"), full_page=True)
                # Change account controls cannot change the immutable detail target.
                page.locator("#reviewer").fill("预算负责人")
                page.locator("#note").fill("仅 fixture 测试，确认精确参数")
                page.locator("#confirmed").check()
                page.locator("#submitConsent").click()
                page.wait_for_function(
                    '()=>document.querySelector("#taskTitle").textContent.includes("创建排队中")'
                )
                assert provider.creates == 0
                tick(root, store, native=service)
                assert provider.creates == 1
                tick(root, store, native=service)
                assert provider.creates == 1
                page.locator("#detail .close").click()
                page.reload()
                page.wait_for_selector(".task-card")
                page.get_by_role("button", name="查看 / 确认").click()
                page.wait_for_function(
                    '()=>document.querySelector("#taskTitle").textContent.includes("已收到计划 ID")'
                )
                assert "456" in page.locator("#taskError").inner_text()
                page.screenshot(path=str(evidence / "submitted-desktop.png"), full_page=True)
                page.locator("#detail .close").click()
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth") <= 390
                page.screenshot(path=str(evidence / "mobile.png"), full_page=True)
                assert not errors, errors
                result = {
                    "evidence": "real Chromium + actual FFmpeg, synthetic OAuth/upload/create provider",
                    "real_platform_calls": 0,
                    "uploads_fixture": provider.uploads,
                    "creates_fixture": provider.creates,
                    "javascript_errors": errors,
                    "mobile_width": 390,
                    "approval_gate": "no upload before upload approval; no create before final exact-payload approval; one POST; reload persisted",
                }
                (evidence / "browser-result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2)
                )
                print(json.dumps(result, ensure_ascii=False))
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
