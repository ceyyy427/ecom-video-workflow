"""Check three directions and single-shot controls in an isolated synthetic project."""

import argparse
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main():
    import uvicorn
    from playwright.sync_api import expect, sync_playwright
    from test_customer import approve, client, picture, prepare, project

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "docs/evidence/narrative-samples")
    evidence = parser.parse_args().evidence
    evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shotcraft-ui-") as temp:
        c = client(Path(temp))
        p = approve(c, picture(c, project(c, "自动UI fixture · 非客户审核")))
        settings = {
            **p["settings"],
            "brief": {
                "format": "showcase",
                "category": "数码耳机",
                "audience": "年轻学生",
                "tone": "利落活泼节奏",
            },
        }
        p = c.put(
            f"/api/customer-projects/{p['id']}",
            json={"revision": p["revision"], "settings": settings},
        ).json()
        p = prepare(c, p)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(c.app, host="127.0.0.1", port=port, log_level="error", access_log=False)
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        errors = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))
                # Exercise unavailable-preview recovery, not a fake rendered styleframe.
                page.route("**/direction-previews", lambda r: r.abort())
                page.goto(f"http://127.0.0.1:{port}/create?project={p['id']}")
                expect(page.locator(".direction")).to_have_count(3)
                assert page.locator(".direction").filter(has_text="镜头组合：").count() == 3
                assert page.locator(".direction").filter(has_text="完整编排：").count() == 3
                page.locator(".direction").first.click()
                expect(page.locator(".direction").first).to_have_attribute("aria-pressed", "true")
                page.locator("#makeBoard").click()
                choices = page.get_by_label("第 1 镜动效配方", exact=True)
                expect(choices).to_be_visible()
                choices.select_option("none")
                page.get_by_label("第 1 镜水平焦点", exact=True).fill("0.63")
                page.get_by_label("第 1 镜动效强度", exact=True).select_option("bold")
                page.get_by_label("第 1 镜动效偏移秒数", exact=True).fill("0.25")
                ranges = page.get_by_label("第 1 镜保护区间", exact=True)
                ranges.fill("0.20-99")
                ranges.press("Tab")
                before = c.get(f"/api/customer-projects/{p['id']}").json()["job"]
                page.locator(".customer-shot").first.get_by_role(
                    "button", name="保存这一镜", exact=True
                ).click()
                page.wait_for_timeout(300)
                blocked = c.get(f"/api/customer-projects/{p['id']}").json()["job"]
                assert before["storyboard_revision"] == blocked["storyboard_revision"], (
                    "Invalid ranges saved"
                )
                ranges.fill("0.20-0.50")
                ranges.press("Tab")
                page.locator(".customer-shot").first.get_by_role(
                    "button", name="保存这一镜", exact=True
                ).click()
                expect(page.locator("#message")).to_contain_text("这一镜已保存", timeout=10000)
                saved = c.get(f"/api/customer-projects/{p['id']}").json()["job"]
                assert saved["storyboard"]["shots"][0]["shot_recipe"] == "none"
                assert saved["storyboard"]["creative"]["production"] == "narrative-v1"
                plan = saved["storyboard"]["shots"][0]["motion_plan"]
                assert saved["storyboard"]["shots"][0]["focus_x"] == 0.63
                assert plan["strength"] == "bold" and plan["cue_offset"] == 0.25
                assert plan["windows"] == [{"start": 0.2, "end": 0.5, "basis": "manual"}]
                assert saved["status"] == "draft" and not saved["reviews"]
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1000})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(evidence / f"controls-{width}.png"), full_page=True)
                browser.close()
            assert not errors, errors
            (evidence / "controls.json").write_text(
                json.dumps(
                    {
                        "fixture": True,
                        "preview_requests": "deliberately aborted; no styleframe render claimed",
                        "three_motion_descriptions": True,
                        "three_joint_production_descriptions": True,
                        "selection_and_save_recipe": True,
                        "invalid_range_blocks_save": True,
                        "strength_cue_manual_window_saved": True,
                        "status": "draft",
                        "review_records": 0,
                        "page_errors": errors,
                        "widths": [1440, 390],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    print("Isolated controls check passed")


if __name__ == "__main__":
    main()
