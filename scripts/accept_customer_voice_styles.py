"""Isolated voice UI acceptance. --live sends exactly two authorized TTS requests.

Human confirmations below are AUTOMATED FIXTURE records, never customer approvals.
Default uses HTTP audio fixtures; ASR, rendering, cache and databases remain real.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE 声音工作流验收，非客户人工审批"


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from ecom_video.api import create_app
    from ecom_video.volc_voice import ENDPOINT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--live", action="store_true", help="仅两次真实云请求：首句和整稿；按账户计费"
    )
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if data.is_relative_to(ROOT) or (data.exists() and any(data.iterdir())):
        parser.error("Use an empty isolated directory outside the repository")
    data.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    if not args.live:
        config = data / "fixture-config.json"
        config.write_text('{"api_key":"isolated-fixture-no-real-key"}')
        config.chmod(0o600)
        os.environ.pop("DOUBAO_TTS_API_KEY", None)
        os.environ["ECOM_VOLC_VOICE_CONFIG"] = str(config)
    app = create_app(runtime)
    checks, calls, errors, unexpected = [], [], [], []

    def check(name):
        checks.append(name)
        (data / "acceptance.json").write_text(
            json.dumps(
                {
                    "label": LABEL,
                    "live": args.live,
                    "checks": checks,
                    "provider_calls": calls,
                    "errors": errors,
                    "unexpected": unexpected,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("CHECK " + name, flush=True)

    class ObservedTransport(httpx.BaseTransport):
        def handle_request(self, request):
            assert str(request.url) == ENDPOINT and len(calls) < 2
            payload = json.loads(request.content)["req_params"]
            calls.append(
                {
                    "text_length": len(payload["text"]),
                    "speech_rate": payload["audio_params"]["speech_rate"],
                    "speaker": payload["speaker"],
                }
            )
            self.inner = httpx.HTTPTransport(retries=0, trust_env=False)
            return self.inner.handle_request(request)

        def close(self):
            self.inner.close()

    if args.live:
        app.state.volc_voice.transport = ObservedTransport()
    else:
        import base64

        converted = data / "fixture.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(ROOT / "examples/client-demo/social/narration.wav"),
                "-ar",
                "24000",
                str(converted),
            ],
            check=True,
        )

        preview_audio = data / "fixture-preview.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(converted), "-t", "3", str(preview_audio)],
            check=True,
        )

        def fixture(req):
            payload = json.loads(req.content)["req_params"]
            calls.append(
                {
                    "text_length": len(payload["text"]),
                    "speech_rate": payload["audio_params"]["speech_rate"],
                    "speaker": payload["speaker"],
                }
            )
            return httpx.Response(
                200,
                content=(
                    "data: "
                    + json.dumps(
                        {
                            "code": 0,
                            "data": base64.b64encode(
                                (
                                    converted if "\n" in payload["text"] else preview_audio
                                ).read_bytes()
                            ).decode(),
                        }
                    )
                    + '\n\ndata: {"code":20000000}\n\n'
                ).encode(),
            )

        app.state.volc_voice.transport = httpx.MockTransport(fixture)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
            client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]

            def post(path, body):
                r = client.post("/api" + path, json=body)
                assert r.is_success, (path, r.status_code, r.text[:1000])
                return r.json()

            p = post(
                "/customer-projects",
                {
                    "title": LABEL,
                    "settings": {
                        "auto_select": False,
                        "reference_only": False,
                        "strict_product": False,
                        "action_timing": False,
                        "brief": {"format": "narrated"},
                    },
                },
            )
            pid = p["id"]
            product_base = "/products/" + pid
            customer_base = "/customer-projects/" + pid

            def project():
                return client.get("/api" + customer_base).json()

            script = (ROOT / "examples/client-demo/social/script.txt").read_text().strip()
            r = client.post(
                "/api" + product_base + "/documents",
                data={"revision": p["product"]["revision"]},
                files={"file": ("sample.txt", script.encode(), "text/plain")},
            )
            assert r.is_success, r.text
            product = r.json()
            facts = [f["id"] for f in product["facts"]]
            product = post(
                product_base + "/facts/confirm",
                {
                    "revision": product["revision"],
                    "fact_ids": facts,
                    "reviewer": LABEL,
                    "note": "示例稿的可见场景，技术验收fixture",
                    "confirmed": True,
                },
            )
            product = post(
                product_base + "/scripts",
                {
                    "revision": product["revision"],
                    "scenes": [{"text": line, "fact_ids": facts} for line in script.splitlines()],
                },
            )
            post(
                product_base + "/scripts/confirm",
                {
                    "revision": product["revision"],
                    "draft_id": product["current_draft_id"],
                    "reviewer": LABEL,
                    "note": "技术验收fixture，不代替客户核对",
                    "confirmed": True,
                    "seconds": 3,
                },
            )
            footage = ROOT / "examples/p9-real/originals/6177761.mp4"
            with footage.open("rb") as f:
                r = client.post(
                    "/api" + customer_base + "/assets",
                    data={"revision": project()["revision"], "role": "product"},
                    files={"file": (footage.name, f, "video/mp4")},
                )
            assert r.is_success, r.text
            check("isolated_product_facts_script_and_real_licensed_footage_fixture")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(r):
                    if not r.request.url.startswith(base + "/"):
                        unexpected.append(r.request.url)
                        return r.abort()
                    if r.request.method not in ("GET", "HEAD") and any(
                        x in r.request.url
                        for x in ["/qianchuan/", "/distribution/tasks", "/reports/syncs"]
                    ):
                        unexpected.append(r.request.url)
                        return r.abort()
                    r.continue_()

                page.route("**/*", route)
                page.goto(base + "/create?project=" + pid)
                expect(page.locator("#saveSettings")).to_be_enabled(timeout=30000)
                expect(page.locator("#directions .direction")).to_have_count(3)
                for style, label, rate in [
                    ("cinema", "轻声克制", "-5"),
                    ("social", "朋友分享", "+5"),
                    ("lab", "自然讲解", "0"),
                ]:
                    page.locator(f'[data-style="{style}"]').click()
                    expect(page.locator("#volcVoiceProfile")).to_contain_text(label)
                    expect(page.locator("#volcVoiceProfile")).to_contain_text("语速 " + rate)
                assert not calls
                check("three_style_profiles_select_without_cloud")
                page.locator('[data-style="social"]').click()
                page.locator("#volcVoiceConsent").check()
                page.locator("#volcVoiceSpeaker").select_option(
                    "zh_female_gaolengyujie_uranus_bigtts"
                )
                expect(page.locator("#volcVoiceConsent")).not_to_be_checked()
                page.locator("#volcVoiceSpeaker").select_option("zh_female_vv_uranus_bigtts")
                page.reload()
                expect(page.locator("#saveSettings")).to_be_enabled()
                expect(page.locator('[data-style="social"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(page.locator("#volcVoiceConsent")).not_to_be_checked()
                check("speaker_change_revokes_consent_and_selection_survives_reload")
                before = project()
                page.locator("#volcVoiceConsent").check()
                page.locator("#volcVoicePreview").click()
                expect(page.locator("#message")).to_contain_text("首句试听已保存", timeout=120000)
                assert len(calls) == 1 and calls[0]["text_length"] == len(script.splitlines()[0])
                assert (
                    project()["revision"] == before["revision"]
                    and project()["job"] == before["job"]
                )
                expect(page.locator("#volcVoicePreviewPlayer")).to_be_visible()
                page.locator("#volcVoicePreviewPlayer").evaluate("(e)=>e.play()")
                page.locator("#volcVoicePreviewPlayer").evaluate("(e)=>e.pause()")
                page.locator("#volcVoiceConsent").check()
                page.locator("#volcVoicePreview").click()
                expect(page.locator("#message")).to_contain_text("首句试听已保存", timeout=120000)
                assert len(calls) == 1
                check("first_sentence_audio_preview_cache_keeps_production_unchanged")
                page.locator("#volcVoiceConsent").check()
                page.locator("#volcVoiceGenerate").click()
                expect(page.locator("#alignmentState")).to_contain_text("待听核", timeout=180000)
                expect(page.locator("#saveSettings")).to_be_enabled(timeout=180000)
                current = project()
                assert len(calls) == 2 and calls[1]["text_length"] == len(script)
                assert current["alignment"]["status"] == "needs_review"
                # Neither the new voice nor a confirmed script grants listening approval.
                jid = current["job"]["id"]
                denied = client.post("/api/jobs/" + jid + "/submit")
                assert denied.status_code == 409, denied.text
                assert current["job"]["status"] == "draft"
                check("full_style_voice_real_asr_stops_for_manual_listening_legacy_submit_denied")
                page.locator("#voiceReviewer").fill(LABEL)
                page.locator("#voiceChecked").check()
                page.locator("#makeBoard").click()
                expect(page.locator("#shotList .customer-shot")).to_have_count(7, timeout=30000)
                expect(page.get_by_role("button", name="试听此镜当前版本配音")).to_have_count(7)
                page.get_by_role("button", name="试听此镜当前版本配音").first.click()
                assert page.locator("#voicePlayer").evaluate("(e)=>!e.paused")
                page.locator("#voicePlayer").evaluate("(e)=>e.pause()")
                check("manual_listening_and_each_shot_has_voice_preview")

                def render():
                    with (data / "render.log").open("a") as log:
                        proc = subprocess.Popen(
                            [
                                sys.executable,
                                "-m",
                                "ecom_video.worker",
                                "--once",
                                "--data",
                                str(runtime),
                            ],
                            cwd=ROOT,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                        )
                        deadline = time.monotonic() + 240
                        while proc.poll() is None and time.monotonic() < deadline:
                            page.wait_for_timeout(500)
                        if proc.poll() is None:
                            proc.terminate()
                            proc.wait(timeout=10)
                            raise AssertionError("render deadline")
                        assert proc.returncode == 0
                    expect(page.locator("#jobState")).to_have_text("待人工审片", timeout=20000)
                    assert project()["job"]["status"] == "needs_review"

                page.locator("#render").click()
                expect(page.locator("#jobState")).to_contain_text("排队", timeout=10000)
                render()
                parent = project()["job"]
                voice = next(
                    a for a in parent["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                downloaded = client.get("/api/jobs/" + parent["id"] + "/artifacts/video")
                assert downloaded.status_code == 200 and len(downloaded.content) > 100000
                parent_output = downloaded.content
                (data / "client-voice-film.mp4").write_bytes(parent_output)
                check("real_remotion_film_stops_at_human_film_review")
                page.locator("#filmReviewer").fill(LABEL)
                page.locator("#filmNote").fill("技术验收fixture，不代表客户主观听审")
                page.locator("#filmChecked").check()
                page.locator("#acceptFilm").click()
                expect(page.locator("#jobState")).to_have_text("已人工复核")
                page.get_by_label("第 2 镜字卡", exact=True).fill("咖啡先倒好")
                page.locator(".customer-shot").nth(1).get_by_role(
                    "button", name="仅修改此镜并生成新版"
                ).click()
                expect(page.locator("#jobState")).to_contain_text("排队", timeout=20000)
                render()
                revised = project()["job"]
                revised_voice = next(
                    a for a in revised["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                assert revised["id"] != parent["id"] and revised_voice["sha256"] == voice["sha256"]
                assert client.get("/api/jobs/" + parent["id"]).json()["status"] == "ready"
                assert (
                    client.get("/api/jobs/" + parent["id"] + "/artifacts/video").content
                    == parent_output
                )
                manifest = client.get("/api/jobs/" + revised["id"] + "/artifacts/manifest").json()
                assert manifest["cache"] == {"hits": 6, "rendered": 1, "total": 7}, manifest[
                    "cache"
                ]
                assert len(calls) == 2
                check("single_visual_shot_revision_preserves_voice_parent_and_manual_review")
                for width in [1440, 390]:
                    page.set_viewport_size({"width": width, "height": 1050})
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), width
                    page.locator(".customer-voice").scroll_into_view_if_needed()
                    page.screenshot(path=str(data / f"voice-panel-{width}.png"))
                voice_card = page.locator("#mediaList article").filter(has=page.locator("audio"))
                voice_card.get_by_role("button", name="移除", exact=True).click()
                expect(page.locator("#message")).to_contain_text("已从项目素材库移除")
                page.locator(".customer-voice summary").click()
                page.get_by_role("button", name="采用此完整声音", exact=True).click()
                deadline = time.monotonic() + 120
                while True:
                    restored_ui = project()
                    if (
                        restored_ui["job"]["id"] != revised["id"]
                        and restored_ui.get("alignment")
                        and restored_ui["alignment"]["status"] == "needs_review"
                    ):
                        break
                    assert time.monotonic() < deadline, restored_ui.get("alignment")
                    page.wait_for_timeout(200)
                expect(page.locator("#alignmentState")).to_contain_text("待听核", timeout=10000)
                expect(page.locator("#voiceChecked")).not_to_be_checked()
                expect(page.locator("#render")).to_be_disabled()
                assert project()["job"]["id"] != revised["id"] and len(calls) == 2
                check("history_restore_ui_stops_for_new_manual_listening_without_cloud")
                assert not errors and not unexpected, (errors, unexpected)
                check("desktop_mobile_no_overflow_no_page_errors_no_platform_calls")
                browser.close()
            # Restore a full historical voice using a fresh input identity; no cloud or inherited hearing.
            current = project()
            tid = next(t["id"] for t in current["voice_takes"] if t["scope"] == "full")
            removed = client.request(
                "DELETE",
                "/api"
                + customer_base
                + "/assets/"
                + next(a["id"] for a in current["media"] if a["role"] == "voice"),
                json={"revision": current["revision"]},
            )
            assert removed.is_success, removed.text
            current = project()
            restored = post(
                customer_base + "/voice/takes/" + tid + "/use",
                {
                    "revision": current["revision"],
                    "product_revision": current["product"]["revision"],
                    "draft_id": current["product"]["current_draft_id"],
                },
            )
            assert restored["inputs_changed"] and len(calls) == 2
            fresh = post(customer_base + "/prepare", {"revision": restored["revision"]})
            assert fresh["job"]["id"] != revised["id"] and fresh["alignment"] is None
            assert client.post("/api/jobs/" + fresh["job"]["id"] + "/submit").status_code == 409
            check("history_restore_no_cloud_new_version_requires_listening_again")
            manifest = {
                "project_id": pid,
                "parent_job": parent["id"],
                "revised_job": revised["id"],
                "voice_sha256": voice["sha256"],
                "film_sha256": hashlib.sha256(parent_output).hexdigest(),
                "provider_calls": len(calls),
                "data": str(data),
            }
            (data / "versions.json").write_text(json.dumps(manifest, indent=2))
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
