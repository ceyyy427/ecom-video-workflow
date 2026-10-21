"""Reproduce actual mismatch and recover/render in an isolated copy, no cloud calls."""

import json
import shutil
import sqlite3
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

OUT = ROOT / "docs/evidence/p12"
p = json.loads((OUT / "project-before.json").read_text())
pid = p["id"]
RESUME = len(sys.argv) > 1
DATA = Path(sys.argv[1]).resolve() if RESUME else ROOT / "var/p12-recovery" / str(time.time_ns())
assert DATA.is_relative_to(ROOT / "var/p12-recovery"), "Only isolated recovery data is allowed"
if not RESUME:
    DATA.mkdir(parents=True)
    with sqlite3.connect(ROOT / "var/workflow.db") as c, sqlite3.connect(DATA / "workflow.db") as b:
        c.backup(b)
    for a in p["media"] + p["job"]["assets"] + p["product"]["sources"]:
        dest = DATA / a["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "var" / a["path"], dest)
server = uvicorn.Server(
    uvicorn.Config(create_app(DATA), host="127.0.0.1", port=8774, log_level="error")
)
threading.Thread(target=server.run, daemon=True).start()
stop = threading.Event()


def consume():
    w = Worker(DATA)
    while not stop.is_set():
        if not w.run_once():
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
        if RESUME:
            assert page.locator(".customer-shot").count() == 2
            assert (
                page.locator("#scriptScenes textarea").first.input_value() == "倒入杯中，慢慢来。"
            )
            page.locator("#retryRender").click()
            idle()
        else:
            page.wait_for_function(
                "()=>p.alignment?.status==='failed' && !!p.alignment.result?.diagnostic",
                timeout=240000,
            )
            assert "Traceback" not in page.locator("#alignmentState").inner_text()
            assert "FFmpeg" not in page.locator("#alignmentState").inner_text()
            assert page.locator("#makeBoard").is_disabled()
            assert page.locator("#voiceChecked").is_disabled()
            assert "慢慢来" in page.locator("#alignmentDiagnosis").inner_text()
            page.locator("#alignmentDiagnosis").screenshot(path=str(OUT / "mismatch-ui.png"))
            page.locator("#alignmentDiagnosis [data-draft]").first.click()
            assert page.locator("#scriptScenes textarea").count() == 2
            original = page.locator("#scriptScenes textarea").all_text_contents()
            assert (
                page.locator("#scriptScenes textarea").first.input_value() == "倒入杯中，慢慢来。"
            )
            # Reconfirming facts must preserve the loaded narration draft.
            page.locator("#factReviewer").fill("AUTOMATED FIXTURE")
            page.locator("#factNote").fill("隔离副本验证 非客户核验")
            page.locator("#factsChecked").check()
            page.locator("#confirmFacts").click()
            idle()
            assert page.locator("#scriptScenes textarea").count() == 2
            assert (
                page.locator("#scriptScenes textarea").first.input_value() == "倒入杯中，慢慢来。"
            )
            page.locator("#scriptReviewer").fill("AUTOMATED FIXTURE")
            page.locator("#scriptNote").fill("隔离副本匹配恢复验证")
            page.locator("#scriptChecked").check()
            page.locator("#approveScript").click()
            idle()
            page.wait_for_function("()=>p.alignment?.status==='needs_review'", timeout=240000)
            page.locator("[data-style=social]").click()
            page.locator("#voiceReviewer").fill("AUTOMATED FIXTURE 非真人听核")
            page.locator("#voiceChecked").check()
            page.locator("#makeBoard").click()
            idle()
            assert page.locator(".customer-shot").count() == 2, page.locator(
                "#message"
            ).inner_text()
            page.locator("#render").click()
            idle()
        page.wait_for_function(
            "()=>['needs_review','failed','blocked'].includes(p.job?.status)", timeout=300000
        )
        p = c.get("/api/customer-projects/" + pid).json()
        assert p["job"]["status"] == "needs_review", p["job"].get("error")
        assert not errors, errors
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "recovered-mobile.png"), full_page=True)
        artifact = next(a for a in p["job"]["artifacts"] if a["kind"] == "video")
        shutil.copy2(DATA / artifact["path"], OUT / "recovered.mp4")
        (OUT / "recovery.json").write_text(
            json.dumps(
                {
                    "isolated_data": str(DATA),
                    "project_id": pid,
                    "job_id": p["job"]["id"],
                    "status": p["job"]["status"],
                    "render_retry_after_resource_release": RESUME,
                    "script": p["job"]["script"],
                    "shots": p["job"]["storyboard"]["shots"],
                    "matching_history_recovery": True,
                    "facts_preserve_script": True,
                    "failed_alignment_cannot_confirm": True,
                    "no_page_errors": True,
                    "human_review": "pending; isolated automated fixture approvals only",
                    "voice": "existing macOS Tingting, not Volcengine",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("RECOVERY OK", p["job"]["id"], flush=True)
        browser.close()
finally:
    stop.set()
    server.should_exit = True
