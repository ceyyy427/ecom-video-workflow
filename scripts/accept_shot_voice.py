"""Isolated real ASR/render acceptance. --live authorizes exactly one short TTS retake."""

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
LABEL = "AUTOMATED FIXTURE 单句换声验收，非客户人工审批"


def main():
    import httpx
    import numpy as np
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from ecom_video.api import create_app
    from ecom_video.shot_voice import RATE, read_pcm
    from ecom_video.volc_voice import ENDPOINT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="从尚未采用单句的隔离父片继续；不重复已记录的云请求"
    )
    args = parser.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or (not args.resume and data.exists() and any(data.iterdir())):
        parser.error("Use an empty directory outside the repository")
    data.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    app = create_app(runtime)
    calls = []
    checks = []
    if args.resume:
        previous = json.loads((data / "acceptance.json").read_text())
        assert previous["label"] == LABEL
        checks = previous["checks"]
        calls = (
            json.loads((data / "provider-calls.json").read_text())
            if (data / "provider-calls.json").exists()
            else []
        )
    errors = []
    outside = []

    def check(name):
        if name not in checks:
            checks.append(name)
        (data / "acceptance.json").write_text(
            json.dumps(
                {
                    "label": LABEL,
                    "live": args.live,
                    "checks": checks,
                    "provider_calls": calls,
                    "page_errors": errors,
                    "unexpected": outside,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("CHECK " + name, flush=True)

    class Cloud(httpx.BaseTransport):
        def handle_request(self, request):
            assert str(request.url) == ENDPOINT and len(calls) < 1
            p = json.loads(request.content)["req_params"]
            calls.append(
                {
                    "text": p["text"],
                    "speaker": p["speaker"],
                    "speech_rate": p["audio_params"]["speech_rate"],
                }
            )
            (data / "provider-calls.json").write_text(
                json.dumps(calls, ensure_ascii=False, indent=2)
            )
            self.inner = httpx.HTTPTransport(retries=0, trust_env=False)
            return self.inner.handle_request(request)

        def close(self):
            self.inner.close()

    if args.live:
        app.state.volc_voice.transport = Cloud()
    else:
        parser.error(
            "This acceptance currently requires --live; unit tests use isolated HTTP fixtures"
        )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.1)
        with httpx.Client(base_url=base, trust_env=False, timeout=120) as c:
            c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

            def post(path, body):
                r = c.post("/api" + path, json=body)
                assert r.is_success, (path, r.status_code, r.text[:1200])
                return r.json()

            if args.resume:
                projects = c.get("/api/customer-projects").json()
                assert len(projects) == 1
                pid = projects[0]["id"]
                pb = "/products/" + pid
                cb = "/customer-projects/" + pid
                script = (ROOT / "examples/client-demo/social/script.txt").read_text().strip()
            else:
                p = post(
                    "/customer-projects",
                    {
                        "title": LABEL,
                        "settings": {
                            "brief": {"format": "narrated"},
                            "auto_select": False,
                            "action_timing": False,
                        },
                    },
                )
                pid = p["id"]
                pb = "/products/" + pid
                cb = "/customer-projects/" + pid

                def project():
                    return c.get("/api" + cb).json()

                script = (ROOT / "examples/client-demo/social/script.txt").read_text().strip()
                product = c.post(
                    "/api" + pb + "/documents",
                    data={"revision": p["product"]["revision"]},
                    files={"file": ("product.txt", script.encode(), "text/plain")},
                ).json()
                facts = [f["id"] for f in product["facts"]]
                product = post(
                    pb + "/facts/confirm",
                    {
                        "revision": product["revision"],
                        "fact_ids": facts,
                        "reviewer": LABEL,
                        "note": "示例资料/可见场景，不宣称性能",
                        "confirmed": True,
                    },
                )
                product = post(
                    pb + "/scripts",
                    {
                        "revision": product["revision"],
                        "scenes": [
                            {"text": line, "fact_ids": facts} for line in script.splitlines()
                        ],
                    },
                )
                post(
                    pb + "/scripts/confirm",
                    {
                        "revision": product["revision"],
                        "draft_id": product["current_draft_id"],
                        "reviewer": LABEL,
                        "note": "fixture",
                        "confirmed": True,
                        "seconds": 3,
                    },
                )
                for path, role, kind in [
                    (ROOT / "examples/p9-real/originals/6177761.mp4", "product", "video/mp4"),
                    (ROOT / "examples/client-demo/social/narration.wav", "voice", "audio/wav"),
                ]:
                    with path.open("rb") as f:
                        r = c.post(
                            "/api" + cb + "/assets",
                            data={"revision": project()["revision"], "role": role},
                            files={"file": (path.name, f, kind)},
                        )
                    assert r.is_success, r.text
                post(cb + "/prepare", {"revision": project()["revision"]})
                check("isolated_real_product_copy_footage_and_existing_voice_no_cloud")

            def project():
                return c.get("/api" + cb).json()

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(r):
                    if not r.request.url.startswith(base + "/"):
                        outside.append(r.request.url)
                        return r.abort()
                    if r.request.method == "POST" and any(
                        k in r.request.url
                        for k in ("/qianchuan/", "/reports/syncs", "/distribution/")
                    ):
                        outside.append(r.request.url)
                        return r.abort()
                    r.continue_()

                page.route("**/*", route)
                page.goto(base + "/create?project=" + pid)
                if not args.resume:
                    expect(page.locator("#alignmentState")).to_contain_text(
                        "待听核", timeout=180000
                    )
                    page.locator('[data-style="social"]').click()
                    page.locator("#voiceReviewer").fill(LABEL)
                    page.locator("#voiceChecked").check()
                    page.locator("#makeBoard").click()
                    expect(page.locator("#shotList .customer-shot")).to_have_count(7, timeout=30000)

                else:
                    expect(page.locator("#shotList .customer-shot")).to_have_count(7, timeout=30000)

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
                        while proc.poll() is None:
                            if time.monotonic() > deadline:
                                proc.terminate()
                                proc.wait(10)
                                raise AssertionError("render timeout")
                            page.wait_for_timeout(400)
                        assert proc.returncode == 0
                    expect(page.locator("#jobState")).to_have_text("待人工审片", timeout=20000)

                if project()["job"]["status"] == "draft":
                    page.locator("#render").click()
                    expect(page.locator("#jobState")).to_contain_text("排队")
                    render()
                else:
                    expect(page.locator("#jobState")).to_have_text("待人工审片")
                parent = project()
                old_job = json.loads(json.dumps(parent["job"]))
                parent_film = c.get("/api/jobs/" + old_job["id"] + "/artifacts/video").content
                assert len(parent_film) > 100000
                check("real_parent_asr_and_render_stop_at_film_review")
                target = page.locator(".customer-shot").nth(2).locator(".shot-voice")
                if not project()["voice_patches"]:
                    target.get_by_label("第3句配音音色", exact=True).select_option(
                        "zh_female_gaolengyujie_uranus_bigtts"
                    )
                    target.locator("label.check input").first.check()
                    target.get_by_role(
                        "button", name="重新合成这一句并对比试听", exact=True
                    ).click()
                    expect(page.locator("#message")).to_contain_text("新句已保存", timeout=180000)
                else:
                    assert len(calls) == 1 and not project()["voice_patches"][0]["result_job_id"]
                preview = project()
                take = preview["voice_patches"][0]
                assert len(calls) == 1 and calls[0]["text"] == script.splitlines()[2]
                assert (
                    preview["revision"] == parent["revision"]
                    and preview["job"] == old_job
                    and preview["media"] == parent["media"]
                )
                assert not take["alignment"].get("diagnostic"), take["alignment"]
                for audio in target.locator("audio").all():
                    audio.evaluate("(e)=>e.play()")
                    page.wait_for_timeout(100)
                    audio.evaluate("(e)=>e.pause()")
                check("one_cloud_sentence_real_segment_asr_preview_preserves_parent_and_inputs")
                target.get_by_label("采用确认人", exact=True).fill(LABEL)
                target.locator(".voice-take label.check input").check()
                target.get_by_role("button", name="采用此句，创建待听核新版", exact=True).click()
                expect(page.locator("#message")).to_contain_text("单句已替换到新版", timeout=30000)
                fresh = project()
                assert (
                    fresh["alignment"]["status"] == "needs_review" and not fresh["inputs_changed"]
                )
                expect(page.locator("#voiceChecked")).not_to_be_checked()
                expect(page.locator("#render")).to_be_disabled()
                denied = c.post("/api/jobs/" + fresh["job"]["id"] + "/submit")
                assert denied.status_code in (409, 422)
                assert c.get("/api/jobs/" + old_job["id"]).json() == old_job
                old_voice = next(
                    a for a in old_job["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                new_voice = next(
                    a
                    for a in fresh["job"]["assets"]
                    if a["metadata"].get("customer_role") == "voice"
                )
                original = data / "original-24k.wav"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(runtime / old_voice["path"]),
                        "-ar",
                        str(RATE),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(original),
                    ],
                    check=True,
                )
                before, after = read_pcm(original), read_pcm(runtime / new_voice["path"])
                start = round(take["params"]["audio_start"] * RATE)
                end = round(take["params"]["audio_end"] * RATE)
                delta = round(
                    (take["duration"] - old_job["storyboard"]["shots"][2]["duration"]) * RATE
                )
                assert np.array_equal(before[:start], after[:start]) and np.array_equal(
                    before[end:], after[end + delta : len(before) + delta]
                )
                check("manual_adopt_new_version_pcm_outside_target_exact_and_legacy_submit_blocked")
                page.locator("#voiceReviewer").fill(LABEL)
                page.locator("#voiceChecked").check()
                page.locator("#confirmListening").click()
                expect(page.locator("#render")).to_be_enabled()
                page.locator("#render").click()
                expect(page.locator("#jobState")).to_contain_text("排队")
                render()
                revised = project()
                manifest = c.get("/api/jobs/" + revised["job"]["id"] + "/artifacts/manifest").json()
                assert manifest["cache"] == {"hits": 6, "rendered": 1, "total": 7}, manifest[
                    "cache"
                ]
                assert (
                    c.get("/api/jobs/" + old_job["id"] + "/artifacts/video").content == parent_film
                )
                check(
                    "retimed_subtitles_real_child_render_one_scene_six_cache_and_human_film_review"
                )
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1050})
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    page.locator(".customer-shot").nth(2).locator(
                        ".shot-voice"
                    ).scroll_into_view_if_needed()
                    page.screenshot(path=str(data / f"shot-{width}.png"))
                assert not errors and not outside
                check("desktop_mobile_comparison_no_page_errors_no_platform_writes")
                result = {
                    "project_id": pid,
                    "parent_job": old_job["id"],
                    "child_job": revised["job"]["id"],
                    "voice_patch_id": take["id"],
                    "new_sentence_matches": [s["match"] for s in take["alignment"]["sentences"]],
                    "new_slot_duration": take["duration"],
                    "cache": manifest["cache"],
                    "old_film_sha256": hashlib.sha256(parent_film).hexdigest(),
                    "status": revised["job"]["status"],
                    "outside_pcm_unchanged": True,
                }
                (data / "versions.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2)
                )
                browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


if __name__ == "__main__":
    main()
