"""Real browser listening/resume regression with explicitly synthetic timing fixtures."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or (data.exists() and any(data.iterdir())):
        parser.error("Use an empty directory outside repository")
    data.mkdir(parents=True)
    os.environ["ECOM_AGENT_ENABLED"] = "1"
    os.environ["ECOM_AGENT_EXECUTION_ENABLED"] = "1"
    from playwright.sync_api import expect, sync_playwright
    from test_agent_runtime import control, policy
    from test_customer import approve, audio, client, fixture_alignment, picture, prepare

    from ecom_video.agent_runtime import Runtime
    from ecom_video.agent_service import AgentService

    c = client(data / "runtime")
    p = c.post(
        "/api/customer-projects",
        json={
            "title": "AUTOMATED FIXTURE 浏览器听核回归",
            "settings": {"brief": {"format": "narrated"}},
        },
    ).json()
    p = prepare(c, approve(c, audio(c, picture(c, p))))
    aid = fixture_alignment(data / "runtime", p, confirmed=False)
    p = c.get("/api/customer-projects/" + p["id"]).json()
    proposal = AgentService(data / "runtime", c.app.state.store).create(
        {
            "schema_version": 1,
            "request_id": "browser-listening",
            "operation": "project.produce",
            "input": {
                "project_id": p["id"],
                "expected_revision": p["revision"],
                "expected_product_revision": p["product"]["revision"],
                "policy": policy(),
            },
        }
    )
    rid = proposal["run_id"]
    runtime = Runtime(data / "runtime", c.app.state.store)
    runtime.control(rid, "execute", control(proposal))
    e = runtime.get(rid)
    runtime.choose(
        rid,
        {
            **control(proposal, e["revision"]),
            "style_id": "social",
            "direction_basis": p["direction_basis"],
            "reviewer": "AUTOMATED FIXTURE browser style",
            "confirmed": True,
        },
    )
    runtime.tick()
    runtime.tick()
    assert runtime.get(rid)["waiting_for"] == "listening"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with (data / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ecom_video",
                "--api-only",
                "--data",
                str(data / "runtime"),
                "--port",
                str(port),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            import httpx

            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
                for _ in range(100):
                    try:
                        if http.get("/api/agent/capabilities").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                bodies = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(request):
                    if "direction-previews" in request.request.url:
                        return request.fulfill(
                            status=200, content_type="application/json", body="{}"
                        )
                    if not request.request.url.startswith(f"http://127.0.0.1:{port}"):
                        return request.abort()
                    request.continue_()

                page.route("**/*", route)
                page.on(
                    "request",
                    lambda request: (
                        bodies.append({"url": request.url, "data": request.post_data_json})
                        if "/alignments/" + aid + "/confirm" in request.url
                        else None
                    ),
                )
                page.goto(f"http://127.0.0.1:{port}/create?project=" + p["id"])
                expect(page.locator("#agentState")).to_contain_text("逐句听核", timeout=20000)
                page.locator("#sentences details summary").first.click()
                field = page.locator("#sentences input").first
                changed = float(field.input_value()) + 0.01
                field.fill(str(changed))
                field.press("Tab")
                field.evaluate("el=>el.dataset.acceptance='preserve'")
                page.wait_for_timeout(2300)
                assert field.get_attribute("data-acceptance") == "preserve"
                assert float(field.input_value()) == changed
                page.locator("#voiceReviewer").fill(
                    "AUTOMATED FIXTURE browser listening, not actual approval"
                )
                page.locator("#voiceChecked").check()
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/resume") and response.request.method == "POST"
                    )
                ) as response:
                    page.locator("#agentResume").click()
                assert response.value.status == 200, response.value.text()
                assert (
                    bodies
                    and bodies[-1]["data"]["result"]["sentences"][0]["words"][0]["start"] == changed
                )
                assert not errors, errors
                page.screenshot(path=str(data / "listening-resumed.png"), full_page=True)
                browser.close()
            current = c.get("/api/customer-projects/" + p["id"]).json()
            assert current["alignment"]["status"] == "confirmed"
            assert current["job"]["storyboard_revision"] == 0
            runtime.tick()
            assert runtime.get(rid)["status"] == "running"
            assert (
                c.get("/api/customer-projects/" + p["id"]).json()["job"]["storyboard_revision"] == 1
            )
            report = {
                "phase": "P14",
                "evidence": "browser_real;timing_synthetic_fixture",
                "poll_preserves_timing_edits": True,
                "manual_listening_posted_before_resume": True,
                "agent_plan_effect_created": bool(runtime.effect(rid, "plan")),
                "page_errors": errors,
                "data": str(data),
            }
            (data / "browser.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            server.terminate()
            try:
                server.wait(8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
