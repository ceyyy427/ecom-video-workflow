"""Isolated three-style production acceptance; each invocation authorizes 3 TTS requests.

All confirmation records are AUTOMATED FIXTURE, never customer approvals.
Requires --live and one recommended --style; reruns reuse completed receipts.
"""

import argparse
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
LABEL = "AUTOMATED FIXTURE 商品风格全链路验收，非客户人工确认"
BRIEF = {
    "format": "narrated",
    "category": "家居杯具",
    "audience": "办公室咖啡爱好者",
    "tone": "精致温暖，清楚讲解",
}


def main():
    import httpx
    import numpy as np
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from ecom_video.api import create_app
    from ecom_video.media import digest
    from ecom_video.shot_voice import RATE, read_pcm
    from ecom_video.volc_voice import ENDPOINT

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--style", required=True, choices=["quiet", "editorial", "evidence"])
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    data = args.data.resolve()
    if not args.live or data.is_relative_to(ROOT):
        ap.error("Use --live and an isolated path outside the repository")
    data.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    app = create_app(runtime)
    receipt = data / "provider-calls.json"
    calls = json.loads(receipt.read_text()) if receipt.exists() else []
    checks, errors, unexpected = [], [], []

    def save(name):
        checks.append(name)
        (data / "acceptance.json").write_text(
            json.dumps(
                {
                    "label": LABEL,
                    "style": args.style,
                    "checks": checks,
                    "calls": calls,
                    "page_errors": errors,
                    "unexpected": unexpected,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(args.style + " CHECK " + name, flush=True)

    class Cloud(httpx.BaseTransport):
        def handle_request(self, req):
            assert str(req.url) == ENDPOINT and len(calls) < 3
            p = json.loads(req.content)["req_params"]
            calls.append(
                {
                    "text": p["text"],
                    "speaker": p["speaker"],
                    "speech_rate": p["audio_params"]["speech_rate"],
                }
            )
            receipt.write_text(json.dumps(calls, ensure_ascii=False, indent=2))
            with httpx.HTTPTransport(retries=0, trust_env=False) as transport:
                response = transport.handle_request(req)
                return httpx.Response(
                    response.status_code, headers=response.headers, content=response.read()
                )

    app.state.volc_voice.transport = Cloud()
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
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        with httpx.Client(base_url=base, timeout=240, trust_env=False) as c:
            c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

            def post(path, body):
                r = c.post("/api" + path, json=body)
                assert r.is_success, (path, r.status_code, r.text[:1500])
                return r.json()

            project_receipt = data / "project.json"
            if not project_receipt.exists():
                p = post(
                    "/customer-projects",
                    {
                        "title": "透明咖啡杯 · 日常桌边 " + args.style,
                        "settings": {"brief": BRIEF, "auto_select": False},
                    },
                )
                project_receipt.write_text(json.dumps({"id": p["id"], "label": LABEL}))
            else:
                pid = json.loads(project_receipt.read_text())["id"]
                p = c.get("/api/customer-projects/" + pid).json()
            pid = p["id"]
            pb, cb = "/products/" + pid, "/customer-projects/" + pid

            def current():
                return c.get("/api" + cb).json()

            script = (ROOT / "examples/client-demo/social/script.txt").read_text().strip()
            if not p["product"]["current_draft_id"]:
                product = c.post(
                    "/api" + pb + "/documents",
                    data={"revision": p["product"]["revision"]},
                    files={
                        "file": (
                            "product.txt",
                            (
                                "示例道具：透明咖啡杯。只描述画面可见的桌边、咖啡、手持和倒入，不承诺材质规格或性能。\n"
                                + script
                            ).encode(),
                            "text/plain",
                        )
                    },
                ).json()
                facts = [f["id"] for f in product["facts"]]
                product = post(
                    pb + "/facts/confirm",
                    {
                        "revision": product["revision"],
                        "fact_ids": facts,
                        "reviewer": LABEL,
                        "note": "示例可见场景核对fixture，非客户SKU认证",
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
                        "note": "技术验收fixture",
                        "confirmed": True,
                        "seconds": 3,
                    },
                )
            # Frozen, already licensed same-cup cuts; no stock downloads or inferred SKU claims.
            visuals = [ROOT / f"examples/client-demo/work/social/visual-{i}.mp4" for i in range(7)]
            existing_names = {a["name"] for a in current()["media"]}
            for visual in visuals:
                if visual.name in existing_names:
                    continue
                with visual.open("rb") as f:
                    r = c.post(
                        "/api" + cb + "/assets",
                        data={"revision": current()["revision"], "role": "product"},
                        files={"file": (visual.name, f, "video/mp4")},
                    )
                assert r.is_success, r.text
            p = current()
            if p["settings"]["brief"] != BRIEF and not p["job"]:
                restored = c.put(
                    "/api" + cb,
                    json={"revision": p["revision"], "settings": {**p["settings"], "brief": BRIEF}},
                )
                assert restored.is_success
                p = restored.json()
            assert p["recommendations"]["version"] == 2
            assert len(p["recommendations"]["options"]) == 3
            assert args.style in {s["id"] for s in p["recommendations"]["options"]}
            (data / "recommendations.json").write_text(
                json.dumps(p["recommendations"], ensure_ascii=False, indent=2)
            )
            save("same_product_document_script_and_seven_licensed_live_action_cuts")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def guard(route):
                    url = route.request.url
                    if not url.startswith(base + "/") or (
                        route.request.method == "POST"
                        and any(
                            x in url for x in ("/qianchuan/", "/distribution/", "/reports/syncs")
                        )
                    ):
                        unexpected.append(url)
                        return route.abort()
                    route.continue_()

                page.route("**/*", guard)
                page.goto(base + "/create?project=" + pid)
                expect(page.locator("#directions .direction")).to_have_count(3)
                if not current()["job"]:
                    before = current()["recommendations"]
                    page.locator("#tone").fill("活泼节奏运动")
                    expect(page.locator("#selectionHint")).to_contain_text("尚未保存")
                    page.locator("#audience").fill("年轻学生潮流人群")
                    with page.expect_response(
                        lambda r: r.url == base + "/api" + cb and r.request.method == "PUT"
                    ) as saved:
                        page.locator("#saveSettings").click()
                    assert saved.value.ok
                    expect(page.locator("#saveSettings")).to_be_enabled()
                    other = current()["recommendations"]
                    assert {s["id"] for s in before["options"]} != {
                        s["id"] for s in other["options"]
                    }
                    page.locator("#tone").fill(BRIEF["tone"])
                    page.locator("#audience").fill(BRIEF["audience"])
                    with page.expect_response(
                        lambda r: r.url == base + "/api" + cb and r.request.method == "PUT"
                    ) as saved:
                        page.locator("#saveSettings").click()
                    assert saved.value.ok
                    expect(page.locator("#saveSettings")).to_be_enabled()
                    assert current()["recommendations"]["fingerprint"] == before["fingerprint"]
                    save(
                        "ui_product_audience_tone_recompute_three_actual_layouts_deterministically"
                    )
                    page.locator(f'[data-style="{args.style}"]').click()
                    expect(page.locator("#volcVoiceProfile")).not_to_have_text("")
                    if not any(t["scope"] == "preview" for t in current()["voice_takes"]):
                        assert len(calls) == 0, (
                            "An uncommitted cloud result must be reconciled, not resent"
                        )
                        page.locator("#volcVoiceConsent").check()
                        page.locator("#volcVoicePreview").click()
                        expect(page.locator("#message")).to_contain_text(
                            "首句试听已保存", timeout=120000
                        )
                    page.locator("#volcVoicePreviewPlayer").evaluate("e=>e.play()")
                    page.wait_for_timeout(150)
                    page.locator("#volcVoicePreviewPlayer").evaluate("e=>e.pause()")
                    if not any(a["role"] == "voice" for a in current()["media"]):
                        assert len(calls) == 1
                        page.locator("#volcVoiceConsent").check()
                        page.locator("#volcVoiceGenerate").click()
                        expect(page.locator("#message")).to_contain_text("配音", timeout=120000)
                        expect(page.locator("#volcVoiceGenerate")).to_have_text(
                            "换声并保留旧声音", timeout=120000
                        )
                    save("style_profile_first_sentence_preview_and_full_cloud_voice_two_requests")
                    page.locator("#prepare").click()
                    expect(page.locator("#alignmentState")).to_contain_text(
                        "待听核", timeout=180000
                    )
                    assert current()["alignment"]["status"] == "needs_review"
                    page.locator("#voiceReviewer").fill(LABEL)
                    page.locator("#voiceChecked").check()
                    page.locator("#makeBoard").click()
                    expect(page.locator("#shotList .customer-shot")).to_have_count(7, timeout=30000)
                    # Explicitly set the scene-to-cut mapping, retaining human-adjustment support.
                    p = current()
                    job = p["job"]
                    board = job["storyboard"]
                    mapping = {a["name"]: a for a in job["assets"] if a["kind"] == "video"}
                    for i, shot in enumerate(board["shots"]):
                        asset = mapping[f"visual-{i}.mp4"]
                        assert shot["duration"] <= asset["metadata"]["duration"], (
                            i,
                            shot["duration"],
                            asset["metadata"]["duration"],
                        )
                        shot.update(
                            asset_id=asset["id"],
                            source_in=0,
                            transition="cut",
                            motion="static",
                            treatment="footage",
                        )
                    r = c.put(
                        "/api/jobs/" + job["id"] + "/creative",
                        json={"revision": job["storyboard_revision"], "board": board},
                    )
                    assert r.is_success, r.text
                    page.reload()

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
                        deadline = time.monotonic() + 300
                        while proc.poll() is None:
                            assert time.monotonic() < deadline, (
                                "render exceeded acceptance deadline"
                            )
                            page.wait_for_timeout(400)
                        assert proc.returncode == 0
                    page.reload()
                    expect(page.locator("#jobState")).to_have_text("待人工审片", timeout=20000)

                patch = next(iter(current()["voice_patches"]), None)
                if not patch:
                    if current()["job"]["status"] == "draft":
                        page.locator("#render").click()
                        expect(page.locator("#jobState")).to_contain_text("排队")
                        render()
                    assert current()["job"]["status"] == "needs_review", current()["job"].get(
                        "error"
                    )
                    parent = current()["job"]
                    (data / "parent.json").write_text(json.dumps(parent, ensure_ascii=False))
                    panel = page.locator(".customer-shot").nth(2).locator(".shot-voice")
                    panel.get_by_label("第3句配音音色", exact=True).select_option(
                        "zh_female_gaolengyujie_uranus_bigtts"
                        if args.style != "evidence"
                        else "zh_female_vv_uranus_bigtts"
                    )
                    panel.locator("label.check input").first.check()
                    assert len(calls) == 2
                    panel.get_by_role("button", name="重新合成这一句并对比试听", exact=True).click()
                    expect(page.locator("#message")).to_contain_text("新句已保存", timeout=180000)
                    assert current()["job"] == parent
                parent = json.loads((data / "parent.json").read_text())
                p = current()
                patch = p["voice_patches"][0]
                assert not patch["alignment"].get("diagnostic"), patch["alignment"]
                panel = page.locator(".customer-shot").nth(2).locator(".shot-voice")
                for audio in panel.locator("audio").all():
                    audio.evaluate("e=>e.play()")
                    page.wait_for_timeout(100)
                    audio.evaluate("e=>e.pause()")
                if not patch["result_job_id"]:
                    panel.get_by_label("采用确认人", exact=True).fill(LABEL)
                    panel.locator(".voice-take label.check input").check()
                    panel.get_by_role("button", name="采用此句，创建待听核新版", exact=True).click()
                    expect(page.locator("#message")).to_contain_text(
                        "单句已替换到新版", timeout=30000
                    )
                child = current()
                if child["alignment"]["status"] == "needs_review":
                    expect(page.locator("#render")).to_be_disabled()
                    expect(page.locator("#voiceChecked")).not_to_be_checked()
                    page.locator("#voiceReviewer").fill(LABEL)
                    page.locator("#voiceChecked").check()
                    page.locator("#confirmListening").click()
                    expect(page.locator("#render")).to_be_enabled()
                if current()["job"]["status"] == "draft":
                    page.locator("#render").click()
                    expect(page.locator("#jobState")).to_contain_text("排队")
                    render()
                child = current()
                assert child["job"]["status"] == "needs_review"
                assert (
                    len(calls) == 3
                    and calls[0]["text"] == script.splitlines()[0]
                    and calls[1]["text"] == script
                    and calls[2]["text"] == script.splitlines()[2]
                )
                manifest = c.get("/api/jobs/" + child["job"]["id"] + "/artifacts/manifest").json()
                assert manifest["cache"] == {"hits": 6, "rendered": 1, "total": 7}, manifest[
                    "cache"
                ]
                for i, shot in enumerate(parent["storyboard"]["shots"]):
                    if i != 2:
                        actual = child["job"]["storyboard"]["shots"][i]
                        assert {k: v for k, v in shot.items() if k != "asset_id"} == {
                            k: v for k, v in actual.items() if k != "asset_id"
                        }
                        assert next(
                            a["sha256"] for a in parent["assets"] if a["id"] == shot["asset_id"]
                        ) == next(
                            a["sha256"]
                            for a in child["job"]["assets"]
                            if a["id"] == actual["asset_id"]
                        )
                old_voice = next(
                    a for a in parent["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                new_voice = next(
                    a
                    for a in child["job"]["assets"]
                    if a["metadata"].get("customer_role") == "voice"
                )
                original = data / "old-24k.wav"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
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
                start, end = [
                    round(patch["params"][k] * RATE) for k in ("audio_start", "audio_end")
                ]
                delta = round(
                    (patch["duration"] - parent["storyboard"]["shots"][2]["duration"]) * RATE
                )
                assert np.array_equal(before[:start], after[:start]) and np.array_equal(
                    before[end:], after[end + delta : len(before) + delta]
                )
                assert c.get("/api/jobs/" + parent["id"]).json() == parent
                save(
                    "single_sentence_compare_adopt_realign_pcm_other_six_shots_unchanged_six_cache_hits"
                )
                out = data / "deliverables"
                out.mkdir(exist_ok=True)
                for label, jid in (("parent", parent["id"]), ("revised", child["job"]["id"])):
                    for kind, ext in (
                        ("video", "mp4"),
                        ("subtitles", "srt"),
                        ("shotbook", "json"),
                        ("manifest", "json"),
                    ):
                        r = c.get("/api/jobs/" + jid + "/artifacts/" + kind)
                        assert r.is_success
                        (out / f"{label}-{kind}.{ext}").write_bytes(r.content)
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1050})
                    page.reload()
                    expect(page.locator("#jobState")).to_have_text("待人工审片")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.locator(".customer-shot").nth(2).locator(
                        ".shot-voice"
                    ).scroll_into_view_if_needed()
                    page.screenshot(path=str(data / f"comparison-{width}.png"))
                assert not errors and not unexpected
                save(
                    "reload_old_new_audio_comparison_responsive_zero_page_errors_no_platform_writes"
                )
                versions = {
                    "project_id": pid,
                    "style": args.style,
                    "parent": parent["id"],
                    "revised": child["job"]["id"],
                    "voice_patch_id": patch["id"],
                    "cache": manifest["cache"],
                    "status": "needs_review",
                    "outside_pcm_equal": True,
                    "other_shots_equal": True,
                    "parent_film_sha256": digest(out / "parent-video.mp4"),
                    "child_film_sha256": digest(out / "revised-video.mp4"),
                }
                (data / "versions.json").write_text(
                    json.dumps(versions, ensure_ascii=False, indent=2)
                )
                browser.close()
    finally:
        server.should_exit = True
        thread.join(10)


if __name__ == "__main__":
    main()
