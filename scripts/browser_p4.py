"""Real browser edit/save/reload/render/clone. Isolated local data, no platform calls."""

import io
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402


def main():
    evidence = ROOT / "docs/evidence/p4"
    evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p4-browser-") as folder:
        root = Path(folder)
        app = create_app(root)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8768, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(0.05)
            with (
                httpx.Client(base_url="http://127.0.0.1:8768", timeout=60) as c,
                sync_playwright() as pw,
            ):
                c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
                j = c.post(
                    "/api/jobs",
                    json={"title": "分镜浏览器验收", "script": "展示外观\n查看细节", "seconds": 1},
                ).json()
                image = io.BytesIO()
                Image.new("RGB", (500, 800), "#adbda8").save(image, format="PNG")
                c.post(
                    f"/api/jobs/{j['id']}/assets",
                    data={"kind": "image"},
                    files={"file": ("product.png", image.getvalue(), "image/png")},
                ).raise_for_status()
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto("http://127.0.0.1:8768/")
                page.get_by_role("button", name="分镜浏览器验收").click()
                page.get_by_label("分镜 1 运镜", exact=True).select_option("push")
                page.get_by_label("成片风格", exact=True).select_option("demo")
                # Asset refresh must not destroy pending decisions.
                page.locator("#visualFiles").set_input_files(
                    {"name": "extra.png", "mimeType": "image/png", "buffer": image.getvalue()}
                )
                page.wait_for_function(
                    "()=>document.querySelector('#assetCount').textContent.startsWith('2 /')"
                )
                assert page.get_by_label("分镜 1 运镜", exact=True).input_value() == "push"
                assert page.get_by_label("成片风格", exact=True).input_value() == "demo"
                page.get_by_role("button", name="移除 extra.png", exact=True).click()
                page.wait_for_function(
                    "()=>document.querySelector('#assetCount').textContent.startsWith('1 /')"
                )
                assert page.get_by_label("分镜 1 运镜", exact=True).input_value() == "push"
                page.get_by_role("button", name="保存分镜方案").click()
                page.wait_for_function(
                    "()=>document.querySelector('#storyboardHint').textContent.includes('版本 1')"
                )
                page.reload()
                page.wait_for_function(
                    "()=>document.querySelector('#storyboardHint').textContent.includes('版本 1')"
                )
                assert page.get_by_label("分镜 1 运镜", exact=True).input_value() == "push"
                assert page.get_by_label("成片风格", exact=True).input_value() == "demo"
                page.locator("#storyboardPanel").screenshot(
                    path=str(evidence / "editor-desktop.png")
                )
                page.locator("#submit").click()
                page.wait_for_function(
                    "()=>document.querySelector('#status').textContent==='等待生成'"
                )
                Worker(root).run_once()
                page.wait_for_function(
                    "()=>document.querySelector('#status').textContent==='待人工复核'",
                    timeout=20000,
                )
                assert page.locator("#storyboardFields").evaluate("n=>n.disabled"), {
                    "html": page.locator("#storyboardFields").get_attribute("disabled"),
                    "errors": errors,
                }
                assert page.locator("#video").is_visible()
                page.locator("#clone").click()
                page.wait_for_function("()=>document.querySelector('#status').textContent==='草稿'")
                page.wait_for_function("()=>!document.querySelector('#storyboardFields').disabled")
                assert page.get_by_label("分镜 1 运镜", exact=True).input_value() == "push"
                # Save a pending board and then change script: reset must be deliberate and visible.
                page.get_by_label("分镜 1 运镜", exact=True).select_option("pull")
                page.locator("#script").fill("新的外观文案\n查看细节")
                page.on("dialog", lambda dialog: dialog.accept())
                page.locator("#save").click()
                page.wait_for_function(
                    "()=>document.querySelector('#storyboardHint').textContent.includes('版本 2')"
                )
                assert page.get_by_label("分镜 1 运镜", exact=True).input_value() == "static"
                # Untouched default displayed after script reset must become the actual snapshot.
                default_jid = c.get("/api/jobs").json()[0]["id"]
                assert c.get(f"/api/jobs/{default_jid}").json()["storyboard"] is None
                page.locator("#submit").click()
                page.wait_for_function(
                    "()=>document.querySelector('#status').textContent==='等待生成'"
                )
                frozen = c.get(f"/api/jobs/{default_jid}").json()["snapshot"]["storyboard"]
                assert frozen is not None and frozen["style"] == "premium"
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#storyboardPanel").screenshot(
                    path=str(evidence / "editor-mobile.png")
                )
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                page.goto("http://127.0.0.1:8768/distribution")
                assert page.locator("#review").evaluate("(n)=>n.offsetTop") < page.locator(
                    "#publish"
                ).evaluate("(n)=>n.offsetTop")
                page.goto("http://127.0.0.1:8768/guide")
                assert (
                    page.get_by_text("CSV 模式不需要 App ID 或 Secret。", exact=False).count() == 1
                )
                assert not errors, errors
                (evidence / "browser.json").write_text(
                    json.dumps(
                        {
                            "passed": True,
                            "page_errors": errors,
                            "checks": [
                                "asset_upload_preserves_unsaved_edits",
                                "unreferenced_asset_removal_preserves_edits",
                                "untouched_default_saved_before_submission",
                                "save_reload",
                                "locked_render",
                                "clone_remap",
                                "script_reset",
                                "mobile_no_overflow",
                                "reports_first",
                                "guide",
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
