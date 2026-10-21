"""Real browser/manual revision acceptance; no model or media doubles."""

import hashlib
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p10"
state = json.loads((OUT / "opening/run.json").read_text())
with (
    httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=60) as c,
    sync_playwright() as pw,
):
    base = "/api/customer-projects/" + state["project_id"]
    p = c.get(base).json()
    assert p["job"]["status"] == "needs_review"
    before = p
    original = ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "response",
        lambda r: (
            print("HTTP", r.status, r.url, r.text()[:600], flush=True) if r.status >= 400 else None
        ),
    )
    url = "http://127.0.0.1:8765/create?project=" + state["project_id"]
    page.goto(url)
    page.wait_for_function(
        "()=>!document.querySelector('#projectControls').disabled", timeout=120000
    )
    assert page.locator(".customer-shot").count() == 2
    assert page.locator(".content-analysis").filter(has=page.locator("details")).count() == 3
    assert page.locator(".direction img").count() == 3
    assert all(
        i.evaluate("e=>e.complete&&e.naturalWidth>0") for i in page.locator(".direction img").all()
    )
    assert page.get_by_label("第 2 镜编排", exact=True).input_value() == "footage"
    assert page.get_by_label("第 2 镜识别片段", exact=True).count() == 1
    assert "初次自动安排" in page.locator("#planningNotes").inner_text()
    page.screenshot(path=str(OUT / "customer-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(OUT / "customer-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    # An explicit editing preference, NOT a correction of a model's wrong scene.
    page.get_by_label("第 2 镜字卡", exact=True).fill("瓶口和瓶身")
    page.get_by_label("第 2 镜字卡", exact=True).dispatch_event("change")
    page.locator(".customer-shot").nth(1).get_by_role(
        "button", name="仅修改此镜并生成新版", exact=True
    ).click()
    page.wait_for_timeout(1500)
    print(
        "AFTER CLICK",
        page.locator("#message").inner_text()
        if page.locator("#message").count()
        else page.locator("body").inner_text()[-1800:],
        flush=True,
    )
    page.wait_for_function("old=>p.job.id!==old", arg=before["job"]["id"], timeout=15000)
    started = time.monotonic()
    while True:
        p = c.get(base).json()
        if p["job"]["status"] == "needs_review":
            break
        assert p["job"]["status"] not in ("failed", "blocked", "cancelled"), p["job"].get("error")
        assert time.monotonic() - started < 600
        time.sleep(2)

    def normalized(job):
        assets = {a["id"]: a["sha256"] for a in job["assets"]}
        return [{**s, "asset_id": assets[s["asset_id"]]} for s in job["storyboard"]["shots"]]

    old, new = normalized(before["job"]), normalized(p["job"])
    assert old[:1] == new[:1]
    assert new[1] == {**old[1], "headline": "瓶口和瓶身"}
    old_voice = next(
        a for a in before["job"]["assets"] if a["metadata"].get("customer_role") == "voice"
    )
    new_voice = next(a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice")
    assert old_voice["sha256"] == new_voice["sha256"]
    for key in ("sentences", "raw_words", "audio_sha256", "model_sha256", "adapter_sha256"):
        assert p["alignment"]["result"][key] == before["alignment"]["result"][key]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    latest = ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
    manifest = json.loads((latest.parent / "manifest.json").read_text())
    assert [s["cache_hit"] for s in manifest["scenes"]] == [True, False]
    page.reload()
    page.wait_for_function(
        "()=>!document.querySelector('#projectControls').disabled", timeout=120000
    )
    assert page.get_by_label("第 2 镜字卡", exact=True).input_value() == "瓶口和瓶身"
    page.locator(".customer-shot").nth(1).screenshot(path=str(OUT / "manual-shot.png"))
    assert not errors, errors
    report = {
        "url": url,
        "original_job_id": before["job"]["id"],
        "manual_job_id": p["job"]["id"],
        "original_video": str(original),
        "original_sha256": original_hash,
        "final_video": str(latest),
        "manual_change": "Codex operator preference: shot 2 headline changes; automatic action source timing remains unchanged. NOT a scene-matching correction or human customer approval.",
        "cache_hits": [True, False],
        "unchanged_other_shots": True,
        "voice_sha256": new_voice["sha256"],
        "alignment_timing_unchanged": True,
        "mobile_no_overflow": True,
        "errors": errors,
        "shots": 2,
        "analyses": 3,
        "styleframes": 3,
        "status": p["job"]["status"],
    }
    (OUT / "browser-manual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (OUT / "manual-result.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
    state.update(manual_job_id=p["job"]["id"], final_video=str(latest))
    (OUT / "opening/run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    browser.close()
