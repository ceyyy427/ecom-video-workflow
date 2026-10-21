"""Two-category local vision, speech and immutable-retake acceptance.

All confirmations are AUTOMATED FIXTURE. --live authorizes at most 3 TTS
requests per product; explicit --extra-retake permits a fourth short call.
--prepare-only does not send text to a cloud service.
"""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE 跨品类验收，非客户人工审核"


def selection_mode(data, parent):
    """Resume classification from the frozen parent, never a transient CLI flag."""
    from ecom_video.creative import signature

    path = Path(data) / "manual-selection.json"
    if path.exists():
        record = json.loads(path.read_text())
        if not (
            record["job_id"] == parent["id"]
            and record["board_revision"] == parent["storyboard_revision"]
            and record["board_sha256"] == signature(parent["storyboard"])
        ):
            raise ValueError("人工选段证据与父版不符，停止发布")
        return "manual_after_local_proposals"
    if "人工查看后校正" in (parent["storyboard"].get("creative") or {}).get("review_context", ""):
        raise ValueError("人工选段证据缺失，不能标为自动")
    return "automatic"


def main():
    import httpx
    import numpy as np
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from ecom_video import clip_matching
    from ecom_video.analysis_worker import Worker as AnalysisWorker
    from ecom_video.api import create_app
    from ecom_video.clip_scan import VERSION as SCAN_VERSION
    from ecom_video.creative import recommend
    from ecom_video.media import digest, safe_path
    from ecom_video.shot_voice import RATE, read_pcm
    from ecom_video.volc_voice import ENDPOINT

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--case", required=True, choices=["headphones", "serum"])
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--spec", type=Path, help="Optional frozen category specification JSON")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--music", type=Path, help="Optional locally licensed WAV music bed")
    ap.add_argument(
        "--extra-retake",
        action="store_true",
        help="Explicitly allow one fourth TTS call for a new visual revision",
    )
    ap.add_argument(
        "--retake-speaker",
        choices=["zh_female_vv_uranus_bigtts", "zh_female_gaolengyujie_uranus_bigtts"],
    )
    ap.add_argument(
        "--rank-only", action="store_true", help="Stop after real matching, before render/retake"
    )
    ap.add_argument(
        "--reviewed-ranges",
        type=Path,
        help="Explicitly inspected source ranges; saved separately from model proposals",
    )
    args = ap.parse_args()
    data = args.data.resolve()
    if data.is_relative_to(ROOT) or not (args.live or args.prepare_only):
        ap.error("Use an external isolated directory, with --prepare-only or --live")
    data.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    spec = json.loads(
        (args.spec or ROOT / "docs/evidence/category-validation/cases.json").read_text()
    )[args.case]
    assert spec["script"] == "\n".join(spec["lines"]), "Script and sentence list differ"
    frozen_spec = data / "case-input.json"
    if frozen_spec.exists():
        assert json.loads(frozen_spec.read_text()) == spec, (
            "Resume inputs changed; use a new data directory"
        )
    else:
        frozen_spec.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    app = create_app(runtime)
    calls_file = data / "provider-calls.json"
    calls = json.loads(calls_file.read_text()) if calls_file.exists() else []
    checks = []

    def check(name):
        checks.append(name)
        (data / "acceptance.json").write_text(
            json.dumps(
                {"label": LABEL, "case": args.case, "checks": checks, "provider_calls": calls},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(args.case + " CHECK " + name, flush=True)

    class Cloud(httpx.BaseTransport):
        def handle_request(self, request):
            assert (
                args.live
                and len(calls) < (4 if args.extra_retake else 3)
                and str(request.url) == ENDPOINT
            )
            p = json.loads(request.content)["req_params"]
            calls.append(
                {
                    "text": p["text"],
                    "speaker": p["speaker"],
                    "speech_rate": p["audio_params"]["speech_rate"],
                }
            )
            calls_file.write_text(json.dumps(calls, ensure_ascii=False, indent=2))
            with httpx.HTTPTransport(retries=0, trust_env=False) as transport:
                response = transport.handle_request(request)
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
        with httpx.Client(base_url=base, trust_env=False, timeout=600) as c:
            c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

            def post(path, body=None):
                r = c.post("/api" + path, json=body)
                assert r.is_success, (path, r.status_code, r.text[:1600])
                return r.json()

            receipt = data / "project.json"
            if not receipt.exists():
                p = post(
                    "/customer-projects",
                    {
                        "title": spec["title"],
                        "settings": {"brief": spec["brief"], "auto_select": True},
                    },
                )
                receipt.write_text(json.dumps({"id": p["id"], "label": LABEL}))
            pid = json.loads(receipt.read_text())["id"]
            cb = "/customer-projects/" + pid
            pb = "/products/" + pid

            def current():
                return c.get("/api" + cb).json()

            def version(p):
                return {
                    "revision": p["revision"],
                    "job_id": p["job"]["id"],
                    "board_revision": p["job"]["storyboard_revision"],
                }

            def voice_version(p):
                return {
                    "revision": p["revision"],
                    "product_revision": p["product"]["revision"],
                    "draft_id": p["product"]["current_draft_id"],
                }

            p = current()
            if not p["product"]["current_draft_id"]:
                notes = (
                    "示例商品仅描述许可实拍中可见的颜色、结构和动作，不确认品牌SKU、参数、材质、音质或护肤功效。\n"
                    + spec["script"]
                )
                r = c.post(
                    "/api" + pb + "/documents",
                    data={"revision": p["product"]["revision"]},
                    files={"file": ("product.txt", notes.encode(), "text/plain")},
                )
                assert r.is_success, r.text
                prod = r.json()
                facts = [f["id"] for f in prod["facts"]]
                prod = post(
                    pb + "/facts/confirm",
                    {
                        "revision": prod["revision"],
                        "fact_ids": facts,
                        "reviewer": LABEL,
                        "note": "可见内容fixture，非客户真实性认证",
                        "confirmed": True,
                    },
                )
                prod = post(
                    pb + "/scripts",
                    {
                        "revision": prod["revision"],
                        "scenes": [{"text": line, "fact_ids": facts} for line in spec["lines"]],
                    },
                )
                post(
                    pb + "/scripts/confirm",
                    {
                        "revision": prod["revision"],
                        "draft_id": prod["current_draft_id"],
                        "reviewer": LABEL,
                        "note": "fixture，非客户签收",
                        "confirmed": True,
                        "seconds": 4,
                    },
                )
            sources = json.loads(
                (ROOT / "docs/evidence/category-validation/sources.json").read_text()
            )
            sources = [
                r
                for r in sources
                if r["key"]
                in (
                    ["headphones", "headphones-wear"]
                    if args.case == "headphones"
                    else ["serum-long"]
                )
            ]
            for row in sources:
                name = row["key"] + ".mp4"
                if name in {a["name"] for a in current()["media"]}:
                    continue
                source = Path(row["path"])
                assert digest(source) == row["sha256"]
                with source.open("rb") as f:
                    r = c.post(
                        "/api" + cb + "/assets",
                        data={"revision": current()["revision"], "role": "product"},
                        files={"file": (name, f, "video/mp4")},
                    )
                assert r.is_success, r.text
            p = current()
            if args.music and not any(a["name"] == "music-bed.wav" for a in p["media"]):
                with args.music.open("rb") as f:
                    r = c.post(
                        "/api" + cb + "/assets",
                        data={"revision": p["revision"], "role": "music"},
                        files={"file": ("music-bed.wav", f, "audio/wav")},
                    )
                assert r.is_success, r.text
                p = r.json()
            rec = p["recommendations"]
            assert len(rec["options"]) == 3 and rec["options"][0]["id"] == spec["style"], rec
            job = {"title": p["product"]["title"], "script": spec["script"], "assets": p["media"]}
            variants = {"original": rec}
            for field, value in [
                ("audience", "重视设计与留白的办公人群"),
                ("tone", "安静自然温暖" if args.case == "headphones" else "年轻活泼节奏"),
            ]:
                variants[field] = recommend(job, {**spec["brief"], field: value})
                assert variants[field]["fingerprint"] != rec["fingerprint"]
            assert {s["id"] for s in variants["tone"]["options"]} != {
                s["id"] for s in rec["options"]
            }
            swapped = {
                **job,
                "title": "一只陶瓷咖啡杯",
                "script": "咖啡和茶放在木桌边，看看杯子外观。",
            }
            variants["product_content"] = recommend(swapped, spec["brief"])
            neutral = {"format": "narrated", "category": "数码", "tone": "中性"}
            variants["audience_control_students"] = recommend(
                job, {**neutral, "audience": "年轻学生"}
            )
            variants["audience_control_office"] = recommend(
                job, {**neutral, "audience": "办公咖啡爱好者"}
            )
            assert variants["audience_control_students"]["options"][0]["id"] == "collage"
            assert variants["audience_control_office"]["options"][0]["id"] == "quiet"
            assert (
                "学生"
                in variants["audience_control_students"]["options"][0]["matched_inputs"]["人群"]
            )
            assert (
                "办公"
                in variants["audience_control_office"]["options"][0]["matched_inputs"]["人群"]
            )
            neutral_product = {"format": "narrated", "audience": "普通用户", "tone": "中性"}
            variants["product_control_original"] = recommend(job, neutral_product)
            variants["product_control_coffee"] = recommend(
                {
                    **job,
                    "title": "安静咖啡茶桌",
                    "script": "自然温暖的桌面，放一只咖啡杯，日常品茶。",
                },
                neutral_product,
            )
            assert variants["product_control_coffee"]["options"][0]["id"] == "quiet"
            assert {s["id"] for s in variants["product_control_coffee"]["options"]} != {
                s["id"] for s in variants["product_control_original"]["options"]
            }
            (data / "recommendation-cases.json").write_text(
                json.dumps(variants, ensure_ascii=False, indent=2)
            )
            check("product_audience_tone_three_choices_and_reason_evidence")
            for a in current()["media"]:
                if a["kind"] != "video":
                    continue
                status = a.get("analysis") or {}
                stale = (status.get("result") or {}).get("scan_version") != SCAN_VERSION
                if status.get("status") != "ready" or stale:
                    previous = data / "observations.json"
                    if previous.exists() and not (data / "observations-coarse.json").exists():
                        (data / "observations-coarse.json").write_bytes(previous.read_bytes())
                    post(cb + "/assets/" + a["id"] + "/analysis", {"refresh": stale})
            worker = AnalysisWorker(runtime)
            while any(
                (a.get("analysis") or {}).get("status") == "queued" for a in current()["media"]
            ):
                assert worker.once()
            p = current()
            assert all(
                (a.get("analysis") or {}).get("status") == "ready"
                for a in p["media"]
                if a["kind"] == "video"
            ), [(a["name"], a.get("analysis")) for a in p["media"]]
            (data / "observations.json").write_text(
                json.dumps(
                    {a["name"]: a["analysis"] for a in p["media"] if a["kind"] == "video"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            check("real_local_vlm_scene_scan_source_bound_observations_ready")
            if args.prepare_only:
                return

            def voice_request(p):
                return {
                    **voice_version(p),
                    "style_id": spec["style"],
                    "direction_basis": p["direction_basis"],
                    "external_consent": True,
                }

            if not any(t["scope"] == "preview" for t in p["voice_takes"]):
                assert len(calls) == 0, (
                    "Uncommitted provider call: reconcile, never automatically resend"
                )
                p = post(cb + "/voice/preview", voice_request(p))
            if not any(a["role"] == "voice" for a in p["media"]):
                assert len(calls) == 1
                p = post(cb + "/voice/volcengine", voice_request(p))
            check("real_style_voice_preview_and_full_two_requests")
            if args.reviewed_ranges and p["settings"]["auto_select"]:
                # Same manual fallback exposed in the workbench: save requirements,
                # prepare a new version, and hear-check its alignment again.
                if p["job"] and p["job"]["status"] in ("queued", "rendering"):
                    post("/jobs/" + p["job"]["id"] + "/cancel")
                r = c.put(
                    "/api" + cb,
                    json={
                        "revision": p["revision"],
                        "settings": {**p["settings"], "auto_select": False},
                    },
                )
                assert r.is_success, r.text
                p = r.json()
            if not p["job"] or p["inputs_changed"]:
                p = post(cb + "/prepare", {"revision": p["revision"]})
            if not p["alignment"]:
                voice = next(
                    a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                post("/jobs/" + p["job"]["id"] + "/alignments", {"asset_id": voice["id"]})
            deadline = time.monotonic() + 420
            while current()["alignment"]["status"] in ("queued", "running"):
                assert time.monotonic() < deadline
                time.sleep(0.25)
            p = current()
            assert p["alignment"]["status"] in ("needs_review", "confirmed"), p["alignment"]
            if p["alignment"]["status"] == "needs_review":
                post(
                    "/jobs/" + p["job"]["id"] + "/alignments/" + p["alignment"]["id"] + "/confirm",
                    {"reviewer": LABEL, "confirmed": True},
                )
            p = current()
            if args.reviewed_ranges and not (data / "parent.json").exists():
                from ecom_video.customer_planner import plan_board

                assert (data / "rankings.json").exists(), (
                    "Run automatic ranking before manual review"
                )
                reviewed = json.loads(args.reviewed_ranges.read_text())[args.case]
                board, _ = plan_board(
                    p["job"], {**p["settings"], "auto_select": False}, spec["style"], p["alignment"]
                )
                assert len(reviewed) == len(board["shots"])
                decisions = []
                source_rows = {r["key"]: r for r in sources}
                for shot, selected in zip(board["shots"], reviewed, strict=True):
                    source = source_rows[selected["source"]]
                    asset = next(a for a in p["job"]["assets"] if a["sha256"] == source["sha256"])
                    shot.update(
                        asset_id=asset["id"],
                        source_in=selected["start"],
                        motion="static",
                        fit=selected.get("fit", "contain"),
                        focus_x=selected.get("focus_x", 0.5),
                        focus_y=selected.get("focus_y", 0.5),
                    )
                    decisions.append(
                        {
                            **selected,
                            "end": selected["start"] + shot["duration"],
                            "source_sha256": source["sha256"],
                            "text": spec["lines"][len(decisions)],
                        }
                    )
                board["creative"]["review_context"] = (
                    "AUTOMATED FIXTURE：实拍时点人工查看后校正；不是模型自动动作核验。"
                )
                r = c.put(
                    "/api/jobs/" + p["job"]["id"] + "/storyboard",
                    json={"revision": p["job"]["storyboard_revision"], "board": board},
                )
                assert r.is_success, r.text
                from ecom_video.creative import signature

                p = current()
                (data / "manual-selection.json").write_text(
                    json.dumps(
                        {
                            "label": LABEL,
                            "automatic_proposals_preserved": True,
                            "shots": decisions,
                            "job_id": p["job"]["id"],
                            "board_revision": p["job"]["storyboard_revision"],
                            "board_sha256": signature(p["job"]["storyboard"]),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            if not p["job"]["storyboard"]:
                actual_rank = clip_matching.rank

                def traced_rank(lines, pool, model):
                    rows = actual_rank(lines, pool, model)
                    (data / "rankings.json").write_text(
                        json.dumps(
                            {"lines": lines, "pool": pool, "rows": rows},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return rows

                clip_matching.rank = traced_rank
                p = post(
                    cb + "/plan",
                    {
                        **version(p),
                        "style_id": spec["style"],
                        "fingerprint": p["recommendations"]["fingerprint"],
                        "alignment_id": p["alignment"]["id"],
                    },
                )
            (data / "planning.json").write_text(
                json.dumps(
                    {"notes": p["planning_notes"], "board": p["job"]["storyboard"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            check(
                "reviewed_manual_ranges_after_real_local_rank"
                if (data / "manual-selection.json").exists()
                else "real_local_rank_and_automatic_range_selection_after_fixture_listening"
            )
            if args.rank_only:
                return

            def render(p):
                if p["job"]["status"] == "draft":
                    p = post(cb + "/submit", version(p))
                if p["job"]["status"] == "queued":
                    with (data / "render.log").open("a") as log:
                        subprocess.run(
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
                            check=True,
                            timeout=300,
                        )
                p = current()
                assert p["job"]["status"] == "needs_review", p["job"].get("error")
                return p

            parent_file = data / "parent.json"
            p = current()
            relevant = [
                t for t in p["voice_patches"] if p["job"]["id"] in (t["job_id"], t["result_job_id"])
            ]
            if not relevant:
                p = render(current())
                parent = p["job"]
                parent_file.write_text(json.dumps(parent, ensure_ascii=False))
                data_body = {
                    **version(p),
                    **voice_version(p),
                    "external_consent": True,
                    "speaker": args.retake_speaker
                    or (
                        "zh_female_gaolengyujie_uranus_bigtts"
                        if args.case == "headphones"
                        else "zh_female_vv_uranus_bigtts"
                    ),
                }
                assert len(calls) == (3 if args.extra_retake else 2)
                p = post(
                    cb + "/voice/shots/" + p["job"]["storyboard"]["shots"][2]["shot_id"] + "/takes",
                    data_body,
                )
            p = current()
            patch = next(
                t for t in p["voice_patches"] if p["job"]["id"] in (t["job_id"], t["result_job_id"])
            )
            assert not patch["alignment"].get("diagnostic"), patch["alignment"]
            parent = json.loads(parent_file.read_text())
            if not patch["result_job_id"]:
                p = post(
                    cb + "/voice/shots/takes/" + patch["id"] + "/use",
                    {**version(p), **voice_version(p), "reviewer": LABEL, "confirmed": True},
                )
                assert p["alignment"]["status"] == "needs_review"
                assert c.post("/api/jobs/" + p["job"]["id"] + "/submit").status_code in (409, 422)
            p = current()
            if p["alignment"]["status"] == "needs_review":
                post(
                    "/jobs/" + p["job"]["id"] + "/alignments/" + p["alignment"]["id"] + "/confirm",
                    {"reviewer": LABEL, "confirmed": True},
                )
            p = render(current())
            child = p["job"]
            assert c.get("/api/jobs/" + parent["id"]).json() == parent
            manifest = c.get("/api/jobs/" + child["id"] + "/artifacts/manifest").json()
            n = len(spec["lines"])
            assert manifest["cache"] == {"hits": n - 1, "rendered": 1, "total": n}, manifest[
                "cache"
            ]
            for i, s in enumerate(parent["storyboard"]["shots"]):
                if i == 2:
                    continue
                t = child["storyboard"]["shots"][i]
                assert {k: v for k, v in s.items() if k != "asset_id"} == {
                    k: v for k, v in t.items() if k != "asset_id"
                }
                assert next(
                    a["sha256"] for a in parent["assets"] if a["id"] == s["asset_id"]
                ) == next(a["sha256"] for a in child["assets"] if a["id"] == t["asset_id"])
            before_asset = next(
                a for a in parent["assets"] if a["metadata"].get("customer_role") == "voice"
            )
            after_asset = next(
                a for a in child["assets"] if a["metadata"].get("customer_role") == "voice"
            )
            old = data / "before.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(runtime / before_asset["path"]),
                    "-ar",
                    str(RATE),
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(old),
                ],
                check=True,
            )
            before, after = read_pcm(old), read_pcm(runtime / after_asset["path"])
            a, b = [round(patch["params"][k] * RATE) for k in ("audio_start", "audio_end")]
            delta = round((patch["duration"] - parent["storyboard"]["shots"][2]["duration"]) * RATE)
            assert np.array_equal(before[:a], after[:a]) and np.array_equal(
                before[b:], after[b + delta : len(before) + delta]
            )
            check("one_sentence_retake_unchanged_other_scenes_pcm_parent_and_local_cache")
            out = data / "deliverables"
            out.mkdir(exist_ok=True)
            for label, jid in [("parent", parent["id"]), ("revised", child["id"])]:
                for kind, ext in [
                    ("video", "mp4"),
                    ("subtitles", "srt"),
                    ("shotbook", "json"),
                    ("manifest", "json"),
                ]:
                    r = c.get("/api/jobs/" + jid + "/artifacts/" + kind)
                    assert r.is_success
                    (out / f"{label}-{kind}.{ext}").write_bytes(r.content)
            # Freeze paired audio without exposing provider credentials or original stock.
            with sqlite3.connect(
                "file:" + str(runtime / "workflow.db") + "?mode=ro", uri=True
            ) as db:
                files = json.loads(
                    db.execute(
                        "select files from voice_patches where id=?", (patch["id"],)
                    ).fetchone()[0]
                )
            import shutil

            for kind in ("old", "new"):
                shutil.copy2(safe_path(runtime, files[kind]["path"]), out / (kind + ".wav"))
            errors = []
            writes = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "request",
                    lambda r: (
                        writes.append(r.url)
                        if r.method not in ("GET", "HEAD") and "/direction-previews" not in r.url
                        else None
                    ),
                )
                page.goto(base + "/create?project=" + pid)
                expect(page.locator("#jobState")).to_have_text("待人工审片")
                panel = page.locator(".customer-shot").nth(2).locator(".shot-voice")
                for audio in panel.locator("audio").all():
                    audio.evaluate("e=>e.play()")
                    page.wait_for_timeout(100)
                    audio.evaluate("e=>e.pause()")
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1050})
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    panel.scroll_into_view_if_needed()
                    page.screenshot(path=str(data / f"comparison-{width}.png"))
                assert not errors and not writes, (errors, writes)
                browser.close()
            assert len(calls) == (4 if args.extra_retake else 3)
            assert calls[-1]["text"] == spec["lines"][2], (
                "Retake must send only the target sentence"
            )
            check("old_new_playback_pending_review_responsive_no_approvals_or_platform_requests")
            result = {
                "project_id": pid,
                "style": spec["style"],
                "selection_mode": selection_mode(data, parent),
                "parent": parent["id"],
                "revised": child["id"],
                "cache": manifest["cache"],
                "other_scenes_equal": True,
                "outside_pcm_equal": True,
                "status": "needs_review",
                "duration": manifest["duration"],
                "provider_calls": len(calls),
                "parent_film_sha256": digest(out / "parent-video.mp4"),
                "child_film_sha256": digest(out / "revised-video.mp4"),
                "page_errors": errors,
                "unexpected_writes": writes,
            }
            (data / "versions.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        server.should_exit = True
        thread.join(10)


if __name__ == "__main__":
    main()
