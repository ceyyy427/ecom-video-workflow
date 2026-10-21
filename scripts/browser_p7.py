"""P7 browser + actual render acceptance; synthetic fixtures, never customer or human approval."""

import json
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ecom_video.api import create_app  # noqa: E402
from ecom_video.media import digest  # noqa: E402
from ecom_video.worker import Worker  # noqa: E402

DATA = ROOT / "var/p7-acceptance" / str(time.time_ns())
OUT = ROOT / "docs/evidence/p7"
FIX = DATA / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
LINES = ["奶白色杯身，深色杯盖。", "先看杯盖，再看杯身。", "近看细节，远看整体。"]
LABEL = "AUTOMATED FIXTURE — NOT HUMAN LISTENING APPROVAL"
(FIX / "fixture-product.txt").write_text("\n".join(LINES))
if not (FIX / "voice.wav").exists():
    parts = [np.zeros(8640, dtype="<i2")]
    for i, line in enumerate(LINES):
        text, aiff, wav = [FIX / f"line-{i}.{ext}" for ext in ["txt", "aiff", "wav"]]
        text.write_text(line)
        subprocess.run(
            ["say", "-v", "Tingting", "-r", "175", "-f", str(text), "-o", str(aiff)], check=True
        )
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav)],
            check=True,
        )
        with wave.open(str(wav), "rb") as w:
            parts.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))
        parts.append(np.zeros(24000 if i < 2 else 48000, dtype="<i2"))
    with wave.open(str(FIX / "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.concatenate(parts).tobytes())
# Reuse P4's explicitly synthetic fixture: this is not customer real footage.
server = uvicorn.Server(
    uvicorn.Config(create_app(DATA), host="127.0.0.1", port=8772, log_level="error")
)
threading.Thread(target=server.run, daemon=True).start()
worker = Worker(DATA)
stop = threading.Event()


def consume():
    while not stop.is_set():
        if not worker.run_once():
            stop.wait(0.2)


threading.Thread(target=consume, daemon=True).start()
errors = []
try:
    deadline = time.monotonic() + 20
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    with httpx.Client(base_url="http://127.0.0.1:8772", timeout=240) as c, sync_playwright() as pw:
        c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(20000)

        def idle():
            page.wait_for_function(
                "()=>!document.querySelector('#projectControls').disabled", timeout=240000
            )

        def state():
            pid = page.url.split("project=")[1]
            r = c.get("/api/customer-projects/" + pid)
            r.raise_for_status()
            return r.json()

        def wait_status(status):
            until = time.monotonic() + 300
            while time.monotonic() < until:
                p = state()
                if p["job"]["status"] == status:
                    return p
                assert p["job"]["status"] not in ("failed", "blocked"), p["job"].get("error")
                page.wait_for_timeout(1000)
            raise AssertionError("render timed out")

        page.goto("http://127.0.0.1:8772/create")
        idle()
        page.locator("#newTitle").fill("P7 合成测试商品 · 非客户实拍")
        page.locator("#createProject").click()
        idle()
        pid = state()["id"]
        print("PROJECT", pid, flush=True)
        page.locator("#autoSelect").uncheck()
        page.locator("#category").fill("家居 随行杯")
        page.locator("#brandName").fill("演示商品")
        page.locator("#saveSettings").click()
        idle()
        page.locator("#documents").set_input_files(str(FIX / "fixture-product.txt"))
        idle()
        page.locator("#visuals").set_input_files(
            [
                str(ROOT / "examples/p4/assets" / f)
                for f in ["hero.png", "detail.png", "detail-take.mp4"]
            ]
        )
        idle()
        assert len(state()["media"]) == 3
        page.get_by_label("detail.png 用途", exact=True).select_option("detail")
        page.locator("#mediaList article").filter(
            has=page.locator("strong", has_text="detail.png")
        ).get_by_role("button", name="保存用途", exact=True).click()
        idle()
        page.get_by_label("detail-take.mp4 素材入点", exact=True).fill("1")
        page.get_by_label("detail-take.mp4 来源说明", exact=True).fill(
            "P4 合成运动视频 fixture，非客户实拍"
        )
        page.locator("#mediaList article").filter(
            has=page.locator("strong", has_text="detail-take.mp4")
        ).get_by_role("button", name="保存用途", exact=True).click()
        idle()
        page.locator("#musicUpload").set_input_files(
            str(ROOT / "examples/p4/assets/ambient-original.wav")
        )
        idle()
        page.locator("#voiceUpload").set_input_files(str(FIX / "voice.wav"))
        idle()
        for box in page.locator(".fact-choice").all():
            box.check()
        page.locator("#factReviewer").fill("自动化测试 · 非人工验收")
        page.locator("#factNote").fill("合成测试资料，仅验证流程")
        page.locator("#factsChecked").check()
        page.locator("#confirmFacts").click()
        idle()
        page.locator("#scriptPaste").fill("\n".join(LINES))
        page.locator("#applyScript").click()
        before_revision = state()["product"]["revision"]
        page.locator("#scriptChecked").check()
        page.locator("#approveScript").click()
        idle()
        assert "确认人" in page.locator("#message").inner_text()
        assert state()["product"]["revision"] == before_revision
        page.locator("#scriptReviewer").fill("自动化测试 · 非客户确认")
        page.locator("#scriptNote").fill("固定 fixture 文稿")
        page.locator("#scriptChecked").check()

        def fail_confirmation_once(route):
            route.fulfill(
                status=422,
                content_type="application/json",
                body='{"detail":"fixture confirmation failure"}',
            )

        page.route("**/api/products/*/scripts/confirm", fail_confirmation_once, times=1)
        page.locator("#approveScript").click()
        idle()
        assert "fixture confirmation failure" in page.locator("#message").inner_text()
        assert state()["product"]["revision"] > before_revision
        page.locator("#scriptChecked").check()
        page.locator("#approveScript").click()
        idle()
        p = state()
        assert p["job"], page.locator("#message").inner_text()
        print("PREPARED", p["job"]["id"], flush=True)
        assert page.locator(".direction").count() == 3
        assert page.locator(".direction img").count() == 3, page.locator("#message").inner_text()
        page.wait_for_function(
            "()=>document.querySelector('#alignmentState').textContent.includes('待听核')",
            timeout=180000,
        )
        p = state()
        assert p["alignment"]["result"]["engine"] == "firered-ctc-int8"
        assert p["alignment"]["status"] == "needs_review"
        page.screenshot(path=str(OUT / "customer-directions-desktop.png"), full_page=True)
        page.locator("[data-style=lab]").click()
        page.locator("#makeBoard").click()
        idle()
        assert not state()["job"]["storyboard"]
        assert "听核" in page.locator("#message").inner_text()
        # Automation marks its identity explicitly; it cannot attest to human listening.
        page.locator("#voiceReviewer").fill(LABEL)
        page.locator("#voiceChecked").check()
        page.locator("#makeBoard").click()
        idle()
        p = state()
        assert p["job"]["storyboard"], page.locator("#message").inner_text()
        board = p["job"]["storyboard"]
        assert len(board["shots"]) == 3
        assert board["shots"][0]["source_in"] == 1
        assert board["music_id"] != board["narration"]["asset_id"]
        assert page.locator(".customer-shot").count() == 3
        page.get_by_label("第 2 镜字卡", exact=True).fill("看杯盖")
        page.locator(".customer-shot").nth(1).get_by_role(
            "button", name="保存这一镜", exact=True
        ).click()
        idle()
        assert state()["job"]["storyboard"]["shots"][1]["headline"] == "看杯盖"
        page.reload()
        idle()
        assert page.get_by_label("第 2 镜字卡", exact=True).input_value() == "看杯盖"
        assert page.locator(".direction[aria-pressed=true]").get_attribute("data-style") == "lab"
        page.locator("#render").click()
        idle()
        first = wait_status("needs_review")
        page.wait_for_function("()=>!document.querySelector('#film').hidden")
        print("FIRST RENDER", first["job"]["id"], flush=True)

        def artifact(p, kind):
            return DATA / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == kind)

        original_hash = digest(artifact(first, "video"))
        # Selection must be cleared when the active film changes.
        page.locator("#filmChecked").check()
        page.get_by_label("第 2 镜运镜", exact=True).select_option("pull")
        page.locator(".customer-shot").nth(1).get_by_role(
            "button", name="仅修改此镜并生成新版", exact=True
        ).click()
        idle()
        second = wait_status("needs_review")
        page.wait_for_function("()=>!document.querySelector('#film').hidden")
        assert first["job"]["id"] != second["job"]["id"]
        assert not page.locator("#filmChecked").is_checked()
        assert page.get_by_label("第 2 镜转场", exact=True).is_disabled()
        assert digest(artifact(first, "video")) == original_hash
        assert second["job"]["parent_id"] == first["job"]["id"]
        assert (
            second["alignment"]["result"]["inherited_from_alignment_id"] == first["alignment"]["id"]
        )
        assert second["alignment"]["updated_at"] == first["alignment"]["updated_at"]
        manifest = json.loads(artifact(second, "manifest").read_text())
        assert manifest["cache"] == {"hits": 2, "rendered": 1, "total": 3}, manifest["cache"]
        for i in [0, 2]:
            a, b = first["job"]["storyboard"]["shots"][i], second["job"]["storyboard"]["shots"][i]
            assert {k: v for k, v in a.items() if k != "asset_id"} == {
                k: v for k, v in b.items() if k != "asset_id"
            }
        page.screenshot(path=str(OUT / "customer-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "customer-mobile.png"), full_page=True)
        page.locator("#shotList").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "customer-mobile-shot.png"))
        assert not errors, errors
        result = {
            "fixture_notice": "Synthetic P4 assets and system voice; NOT customer footage, human listening or client acceptance.",
            "project_id": pid,
            "first_job": first["job"]["id"],
            "revised_job": second["job"]["id"],
            "first_video": str(artifact(first, "video")),
            "revised_video": str(artifact(second, "video")),
            "cache": manifest["cache"],
            "original_sha256_unchanged": original_hash,
            "alignment_engine": first["alignment"]["result"]["engine"],
            "alignment_confirmation": LABEL,
            "video_source_in": 1,
            "browser_errors": errors,
            "checks": [
                "UI uploads doc/image/video/music/voice",
                "missing reviewer and injected confirmation failure retry",
                "locked transition preserves adjacent scene",
                "explicit facts and script confirmation",
                "3 actual styleframes",
                "local CTC alignment and mandatory hearing confirmation gate",
                "3 shots from voice boundaries",
                "shot draft save/reload",
                "actual Remotion render",
                "single-shot revision actual render",
                "same voice confirmation retained",
                "2 cache hits and 1 rerender",
                "old MP4 unchanged",
                "new film review checkbox cleared",
                "390px no overflow",
            ],
        }
        (OUT / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        browser.close()
finally:
    stop.set()
    worker.shutdown.set()
    server.should_exit = True
