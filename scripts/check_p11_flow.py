"""Real local API + browser regression; isolated data, no cloud or live customer edits."""

import json
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

OUT = ROOT / "docs/evidence/p11"
OUT.mkdir(exist_ok=True)
DATA = ROOT / "var/p11-flow" / str(time.time_ns())
server = uvicorn.Server(
    uvicorn.Config(create_app(DATA), host="127.0.0.1", port=8774, log_level="error")
)
threading.Thread(target=server.run, daemon=True).start()
stop = threading.Event()


def consume():
    worker = Worker(DATA)
    while not stop.is_set():
        if not worker.run_once():
            stop.wait(0.3)


threading.Thread(target=consume, daemon=True).start()
try:
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    with (
        httpx.Client(base_url="http://127.0.0.1:8774", trust_env=False, timeout=240) as c,
        sync_playwright() as pw,
    ):
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def call(method, path, **kw):
            r = c.request(method, "/api" + path, **kw)
            r.raise_for_status()
            return r.json()

        p = call(
            "POST",
            "/customer-projects",
            json={
                "title": "P11 流程验收 · 非客户审核",
                "settings": {"brief": {"format": "narrated"}, "auto_select": False},
            },
        )
        pid = p["id"]
        base = "/customer-projects/" + pid
        prod = "/products/" + pid
        with (ROOT / "examples/p10-real/opening/reference.jpg").open("rb") as f:
            p = call(
                "POST",
                base + "/assets",
                data={"revision": p["revision"], "role": "product"},
                files={"file": ("商品.jpg", f, "image/jpeg")},
            )
        product = call("GET", prod)
        lines = ["握稳瓶身，轻轻拧开瓶盖。", "看一看，瓶口和瓶身的细节。"]
        product = call(
            "POST",
            prod + "/documents",
            data={"revision": product["revision"]},
            files={"file": ("演示说明.txt", "\n".join(lines).encode(), "text/plain")},
        )
        product = call(
            "POST",
            prod + "/facts/confirm",
            json={
                "revision": product["revision"],
                "fact_ids": [f["id"] for f in product["facts"]],
                "reviewer": "自动测试",
                "note": "fixture 非客户确认",
                "confirmed": True,
            },
        )
        call(
            "POST",
            prod + "/scripts",
            json={
                "revision": product["revision"],
                "scenes": [
                    {"text": line, "fact_ids": [f["id"] for f in product["facts"]]}
                    for line in lines
                ],
            },
        )
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8774/create?project=" + pid)

        def idle():
            page.wait_for_function(
                "()=>!document.querySelector('#projectControls').disabled", timeout=240000
            )

        idle()
        assert page.locator(".direction").count() == 0
        page.locator("#scriptReviewer").fill("自动页面验收 非客户确认")
        page.locator("#scriptNote").fill("自动流程验收，非客户事实核验")
        page.locator("#scriptChecked").check()
        page.locator("#approveScript").click()
        idle()
        print("AFTER APPROVAL", page.locator("#message").inner_text(), errors, flush=True)
        assert page.locator(".direction").count() == 3
        page.locator("[data-style=social]").click()
        assert page.locator("#makeBoard").is_disabled(), (
            "No narration/job: must show choice, but not enable execution"
        )
        assert "配音" in page.locator("#selectionHint").inner_text()
        page.reload()
        idle()
        assert page.locator("[data-style=social]").get_attribute("aria-pressed") == "true"
        page.screenshot(path=str(OUT / "styles-before-voice.png"), full_page=True)
        page.locator("#voiceUpload").set_input_files(
            str(ROOT / "examples/p10-real/opening/voice.wav")
        )
        idle()
        page.locator("#prepare").click()
        idle()
        assert page.locator("[data-style=social]").get_attribute("aria-pressed") == "true"
        page.wait_for_function("()=>p.alignment?.status==='needs_review'", timeout=240000)
        page.locator("#voiceReviewer").fill("自动测试 非真人听核")
        page.locator("#voiceChecked").check()
        page.locator("#makeBoard").click()
        idle()
        assert page.locator(".customer-shot").count() == 2
        page.locator("#render").click()
        idle()
        page.wait_for_function("()=>p.job?.status==='needs_review'", timeout=300000)
        p = call("GET", base)
        assert p["job"]["storyboard"]["creative"]["style_id"] == "social"
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "flow-mobile.png"), full_page=True)
        page.locator("#newTitle").fill("P11 项目切换提示隔离")
        page.locator("#createProject").click()
        idle()
        assert page.locator(".direction").count() == 0
        assert page.locator("#previewStyles").is_hidden()
        assert page.locator("#selectionHint").inner_text() == ""
        assert page.locator("#previewState").inner_text() == ""
        assert not errors, errors
        report = {
            "project_id": pid,
            "isolated_data": str(DATA),
            "three_styles_before_voice": True,
            "selection_survives_reload_and_prepare": True,
            "job_id": p["job"]["id"],
            "status": p["job"]["status"],
            "style": "social",
            "no_page_errors": True,
            "mobile_no_overflow": True,
            "project_switch_clears_hints": True,
            "voice": "existing local Tingting fixture, NOT Volcengine",
            "human_review": "pending",
        }
        (OUT / "flow.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(report)
        browser.close()
finally:
    stop.set()
    server.should_exit = True
