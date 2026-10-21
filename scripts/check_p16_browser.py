"""Inspect an existing isolated P16 fixture: customer handoff and pending-request controls."""

import argparse
import json
from pathlib import Path

from accept_p16 import ROOT


def main():
    import os
    import socket
    import subprocess
    import sys
    import time

    import httpx
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT):
        parser.error("Use the isolated acceptance directory, never production var")
    evidence = json.loads((data / "acceptance.json").read_text())
    assert evidence["human_decisions_and_timing_are_automated_fixture"]
    eid = evidence["experiment_id"]
    os.environ["ECOM_REVIEW_SNAPSHOTS_ENABLED"] = "1"
    os.environ["ECOM_EXPERIMENTS_ENABLED"] = "1"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    errors = []
    writes = []
    mocked = []
    with (data / "browser-handoff.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ecom_video",
                "--api-only",
                "--data",
                str(data),
                "--port",
                str(port),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                try:
                    if httpx.get(url + "/api/session", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("API not ready")
            e = httpx.get(url + "/api/experiments/" + eid).json()
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1400, "height": 1050})
                page.on("pageerror", lambda exc: errors.append(str(exc)))

                def route(r):
                    if not r.request.url.startswith(url + "/"):
                        return r.abort()
                    if "direction-previews" in r.request.url:
                        mocked.append("style_previews_not_part_of_P16_acceptance")
                        return r.fulfill(status=200, content_type="application/json", body="{}")
                    if r.request.method not in ("GET", "HEAD"):
                        writes.append(r.request.url)
                    r.continue_()

                page.route("**/*", route)
                page.goto(url + "/create?project=" + e["proposal"]["product_id"])
                expect(page.locator("#customerIteration")).to_be_visible()
                expect(page.locator("#customerIterationText")).to_contain_text(
                    e["proposal"]["review_id"]
                )
                expect(page.locator("#customerIterationLink")).to_have_attribute(
                    "href", "/experiments?id=" + eid
                )
                page.screenshot(path=str(data / "browser-handoff.png"), full_page=True)
                page.locator("#customerIterationLink").click()
                expect(page.locator("#expId")).to_have_value(eid)
                expect(page.locator("#evaluations article")).to_have_count(2)
                held = []
                page.route("**/api/experiments/" + eid, lambda r: held.append(r))
                page.locator("#openExperiment").click()
                expect(page.locator("#expHistory")).to_be_disabled()
                expect(page.locator("#expId")).to_be_disabled()
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(10)
                assert len(held) == 1
                held[0].continue_()
                expect(page.locator("#expHistory")).to_be_enabled()
                expect(page.locator("#expId")).to_have_value(eid)
                page.goto(url + "/distribution")
                expect(page.locator("#importWindow")).to_have_attribute("maxlength", "80")
                assert not writes, writes
                browser.close()
            assert not errors, errors
            result = {
                "checks": 9,
                "page_errors": errors,
                "business_writes": writes,
                "mocked_requests": mocked,
                "data": str(data),
            }
            (data / "browser-handoff.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
