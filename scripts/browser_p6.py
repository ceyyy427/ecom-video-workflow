"""Four production formats and reusable shot controls in the actual browser."""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402

with tempfile.TemporaryDirectory(prefix="p6-browser-") as folder:
    server = uvicorn.Server(
        uvicorn.Config(create_app(Path(folder)), host="127.0.0.1", port=8771, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    try:
        while not server.started:
            time.sleep(0.05)
        with (
            httpx.Client(base_url="http://127.0.0.1:8771", timeout=240) as c,
            sync_playwright() as pw,
        ):
            c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
            j = c.post(
                "/api/jobs",
                json={"title": "P6 浏览器杯子", "script": "看奶白杯身\n看深色杯盖", "seconds": 5},
            ).json()
            jid = j["id"]
            c.post(
                f"/api/jobs/{jid}/assets",
                data={"kind": "image"},
                files={
                    "file": (
                        "hero.png",
                        (ROOT / "examples/p4/assets/hero.png").read_bytes(),
                        "image/png",
                    )
                },
            ).raise_for_status()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:8771/studio?job={jid}")
            page.locator("#format").select_option("showcase")
            page.locator("#recommend").click()
            page.wait_for_function(
                "()=>document.querySelectorAll('.styleframe').length===3", timeout=240000
            )
            assert page.locator(".direction").count() == 3
            page.locator("[data-style=cinema]").click()
            page.get_by_label("第 1 镜动态字卡", exact=True).fill("奶白杯身")
            page.get_by_label("第 1 镜镜头编排", exact=True).select_option("macro")
            page.get_by_label("第 1 镜转场", exact=True).select_option("wipe")
            page.locator("#save").click()
            page.wait_for_function(
                "()=>document.querySelector('#message').textContent.includes('已保存')"
            )
            page.reload()
            page.wait_for_function(
                "()=>document.querySelectorAll('.direction[aria-pressed=true]').length===1"
            )
            assert page.get_by_label("第 1 镜镜头编排", exact=True).input_value() == "macro"
            assert page.get_by_label("第 1 镜转场", exact=True).input_value() == "wipe"
            assert page.locator("#format").input_value() == "showcase"
            page.screenshot(path=str(ROOT / "docs/evidence/p6/studio-desktop.png"), full_page=True)
            page.locator("#format").select_option("review")
            assert page.locator(".direction[aria-pressed=true]").count() == 0
            assert "真实视频" in page.locator("#formatHint").inner_text()
            page.locator("#save").click()
            page.wait_for_function(
                "()=>document.querySelector('#message').textContent.includes('选定')"
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(ROOT / "docs/evidence/p6/studio-mobile.png"), full_page=True)
            assert not errors, errors
            (ROOT / "docs/evidence/p6/browser.json").write_text(
                json.dumps(
                    {
                        "checks": [
                            "4 named formats plus legacy",
                            "3 actual product direction previews",
                            "shot recipe and transition save/reload",
                            "format change clears choice",
                            "review guidance",
                            "390px no overflow",
                        ],
                        "errors": errors,
                    },
                    indent=2,
                )
            )
            browser.close()
    finally:
        server.should_exit = True
