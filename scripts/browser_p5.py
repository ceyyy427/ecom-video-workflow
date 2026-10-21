"""P5 real UI, product styleframes and save/reload; isolated local data."""

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

with tempfile.TemporaryDirectory(prefix="p5-browser-") as folder:
    app = create_app(Path(folder))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8769, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        while not server.started:
            time.sleep(0.05)
        with (
            httpx.Client(base_url="http://127.0.0.1:8769", timeout=240) as c,
            sync_playwright() as pw,
        ):
            c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
            j = c.post(
                "/api/jobs",
                json={"title": "P5 浏览器杯子", "script": "奶白杯身\n看看细节", "seconds": 2},
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
            other = c.post(f"/api/jobs/{jid}/clone").json()
            oid = other["id"]
            rec = c.post(f"/api/jobs/{oid}/creative/recommend", json={}).json()
            draft = c.get(f"/api/jobs/{oid}/storyboard").json()
            draft["board"]["creative"] = {
                "brief": rec["brief"],
                "fingerprint": rec["fingerprint"],
                "style_id": rec["options"][0]["id"],
                "brand": {"name": "另一商品"},
            }
            for i, shot in enumerate(draft["board"]["shots"]):
                shot["shot_id"] = f"fixture-{i}"
            c.put(
                f"/api/jobs/{oid}/creative",
                json={"board": draft["board"], "revision": draft["revision"]},
            ).raise_for_status()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:8769/studio?job={jid}")
            page.locator("#category").fill("家居")
            page.locator("#tone").fill("安静")
            page.locator("#recommend").click()
            page.wait_for_function(
                "()=>document.querySelectorAll('.styleframe').length===3", timeout=240000
            )
            assert page.locator(".direction").count() == 3
            page.locator(".direction").first.click()
            page.get_by_label("第 1 镜动态字卡").fill("奶白杯身")
            page.locator("#brandName").fill("本机品牌")
            page.locator("#save").click()
            page.wait_for_function(
                "()=>document.querySelector('#message').textContent.includes('已保存')"
            )
            page.screenshot(path=str(ROOT / "docs/evidence/p5/studio-desktop.png"), full_page=True)
            # Switch within the same live page while A's actual preview URLs are populated.
            page.locator("#jobSelect").select_option(oid)
            page.wait_for_function("()=>document.querySelector('#brandName').value==='另一商品'")
            page.wait_for_function("()=>document.querySelectorAll('.direction').length===3")
            assert page.locator(".styleframe").count() == 0
            page.locator("#jobSelect").select_option(jid)
            page.wait_for_function("()=>document.querySelector('#brandName').value==='本机品牌'")
            page.reload()
            page.wait_for_function(
                "()=>document.querySelectorAll('.direction[aria-pressed=true]').length===1"
            )
            assert page.locator("#brandName").input_value() == "本机品牌"
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(ROOT / "docs/evidence/p5/studio-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
            # Stale brief cannot silently reuse an old selection.
            page.locator("#tone").fill("活泼")
            page.locator("#save").click()
            page.wait_for_function(
                "()=>document.querySelector('#message').textContent.includes('重新推荐')"
            )
            # Changing inputs cannot restore an obsolete selection or another job's previews.
            page.on("dialog", lambda dialog: dialog.accept())
            voice_bytes = (ROOT / "examples/p5/narration.wav").read_bytes()
            voices = []
            for name in ["voice-a.wav", "voice-b.wav"]:
                response = c.post(
                    f"/api/jobs/{jid}/assets",
                    data={"kind": "audio"},
                    files={"file": (name, voice_bytes, "audio/wav")},
                )
                response.raise_for_status()
                voices.append(response.json()["assets"][-1]["id"])
            page.reload()
            page.wait_for_function("()=>document.querySelectorAll('.direction').length===3")
            assert page.locator(".direction[aria-pressed=true]").count() == 0
            assert page.locator(".styleframe").count() == 0
            # Hold an old polling response, then switch the playback source before releasing it.
            aid = "b" * 32
            delayed = []
            page.route(
                f"**/api/jobs/{jid}/alignments",
                lambda route: route.fulfill(json={"id": aid, "status": "running", "result": None}),
            )
            page.route(f"**/api/jobs/{jid}/alignments/{aid}", lambda route: delayed.append(route))
            page.locator("#voice").select_option(voices[0])
            page.locator("#align").click()
            until = time.monotonic() + 5
            while not delayed and time.monotonic() < until:
                page.wait_for_timeout(100)
            assert delayed
            page.evaluate(
                "document.querySelector('#heard').checked=true;document.querySelector('#reviewer').value='old reviewer'"
            )
            page.locator("#voice").select_option(voices[1])
            delayed[0].fulfill(
                json={"id": aid, "status": "needs_review", "result": {"sentences": []}}
            )
            page.wait_for_timeout(200)
            assert page.locator("#confirmation").is_hidden()
            assert not page.locator("#heard").is_checked()
            assert page.locator("#reviewer").input_value() == ""
            page.unroute_all()
            clone = c.post(f"/api/jobs/{jid}/clone").json()
            page.goto(f"http://127.0.0.1:8769/studio?job={clone['id']}")
            page.wait_for_function("()=>document.querySelectorAll('.direction').length===3")
            assert page.locator(".styleframe").count() == 0
            assert page.locator(".direction[aria-pressed=true]").count() == 0
            # Real ASR and confirmation UI; this is an automated fixture, never a listening claim.
            vjob = c.post(
                "/api/jobs",
                json={
                    "title": "AUTOMATED VOICE UI FIXTURE",
                    "script": (ROOT / "examples/p5/script.txt").read_text(),
                    "seconds": 3,
                },
            ).json()
            vid = vjob["id"]
            va = c.post(
                f"/api/jobs/{vid}/assets",
                data={"kind": "audio"},
                files={"file": ("narration.wav", voice_bytes, "audio/wav")},
            ).json()
            page.goto(f"http://127.0.0.1:8769/studio?job={vid}")
            page.locator("#voice").select_option(va["assets"][-1]["id"])
            page.locator("#align").click()
            page.locator("#confirmation").wait_for(state="visible", timeout=180000)
            assert page.locator(".alignment-sentence").count() == 4
            page.locator("#reviewer").fill("AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL")
            page.locator("#heard").check()
            page.locator("#confirm").click()
            page.wait_for_function(
                "()=>document.querySelector('#message').textContent.includes('已应用语义拍')"
            )
            page.screenshot(path=str(ROOT / "docs/evidence/p5/alignment-ui.png"), full_page=True)
            assert not errors, errors
            (ROOT / "docs/evidence/p5/browser.json").write_text(
                json.dumps(
                    {
                        "checks": [
                            "three real product styleframes",
                            "explicit selection",
                            "save/reload",
                            "brand persists",
                            "stale brief blocked",
                            "390px no overflow",
                            "changed assets invalidate selection",
                            "cross-job previews cleared",
                            "delayed old voice response ignored and review reset",
                            "real local ASR + automated confirmation UI",
                        ],
                        "errors": errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            browser.close()
    finally:
        server.should_exit = True
