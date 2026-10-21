"""Real browser/manual revision acceptance; no model or media doubles."""

import hashlib
import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p9"
state = json.loads((OUT / "run.json").read_text())
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
    url = "http://127.0.0.1:8765/create?project=" + state["project_id"]
    page.goto(url)
    page.wait_for_function(
        "()=>!document.querySelector('#projectControls').disabled", timeout=120000
    )
    assert page.locator(".customer-shot").count() == 3
    assert page.locator(".content-analysis").count() == 2
    assert page.locator(".direction img").count() == 3
    assert all(
        i.evaluate("e=>e.complete&&e.naturalWidth>0") for i in page.locator(".direction img").all()
    )
    assert page.get_by_label("第 3 镜编排", exact=True).input_value() == "footage"
    assert page.get_by_label("第 3 镜识别片段", exact=True).count() == 1
    assert "书本←书本" in page.locator("#planningNotes").inner_text()
    page.screenshot(path=str(OUT / "customer-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(OUT / "customer-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    # An explicit editing preference, NOT a correction of a model's wrong scene.
    page.get_by_label("第 3 镜素材入点", exact=True).fill("0.5")
    page.get_by_label("第 3 镜素材入点", exact=True).dispatch_event("change")
    page.get_by_label("第 3 镜字卡", exact=True).fill("书本和电脑旁")
    page.get_by_label("第 3 镜字卡", exact=True).dispatch_event("change")
    page.locator(".customer-shot").nth(2).get_by_role(
        "button", name="仅修改此镜并生成新版", exact=True
    ).click()
    page.wait_for_function("old=>p.job.id!==old", arg=before["job"]["id"], timeout=120000)
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
    assert old[:2] == new[:2]
    assert new[2] == {**old[2], "source_in": 0.5, "headline": "书本和电脑旁"}
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    latest = ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
    manifest = json.loads((latest.parent / "manifest.json").read_text())
    assert [s["cache_hit"] for s in manifest["scenes"]] == [True, True, False]
    page.reload()
    page.wait_for_function(
        "()=>!document.querySelector('#projectControls').disabled", timeout=120000
    )
    assert page.get_by_label("第 3 镜素材入点", exact=True).input_value() == "0.5"
    assert page.get_by_label("第 3 镜字卡", exact=True).input_value() == "书本和电脑旁"
    page.locator(".customer-shot").nth(2).screenshot(path=str(OUT / "manual-shot.png"))
    assert not errors, errors
    report = {
        "url": url,
        "original_job_id": before["job"]["id"],
        "manual_job_id": p["job"]["id"],
        "original_video": str(original),
        "original_sha256": original_hash,
        "final_video": str(latest),
        "manual_change": "Codex operator preference: shot 3 starts 0.5s later and headline changes. NOT a scene-matching correction or human customer approval.",
        "cache_hits": [True, True, False],
        "unchanged_other_shots": True,
        "mobile_no_overflow": True,
        "errors": errors,
        "shots": 3,
        "analyses": 2,
        "styleframes": 3,
        "status": p["job"]["status"],
    }
    (OUT / "browser-manual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (OUT / "manual-result.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
    state.update(manual_job_id=p["job"]["id"], final_video=str(latest))
    (OUT / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    browser.close()
