"""Whole UI workflow acceptance with real local ASR/render; explicitly simulated human/report data."""

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE 全流程验收，非客户人工审批"
HEADER = "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"


def main():
    import httpx
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if data.is_relative_to(ROOT):
        parser.error("Use an isolated directory outside the repository")
    marker = data / "workflow-checkpoint.json"
    if args.resume:
        state = json.loads(marker.read_text())
        assert state["fixture_label"] == LABEL and state["data"] == str(data)
    else:
        if data.exists() and any(data.iterdir()):
            parser.error("Use an empty directory")
        data.mkdir(parents=True, exist_ok=True)
        state = {"fixture_label": LABEL, "data": str(data), "phase": 0, "checks": []}

    def save():
        marker.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    def check(name):
        if name not in state["checks"]:
            state["checks"].append(name)
        save()
        print("CHECK " + name, flush=True)

    save()
    inputs = data / "inputs"
    inputs.mkdir(exist_ok=True)
    script = json.loads((ROOT / "examples/p15/submission-fixture.json").read_text())["script"]
    (inputs / "product.txt").write_text(script + "\n")
    (inputs / "script.txt").write_text(script)
    footage = ROOT / "examples/p9-real/originals/6177761.mp4"
    if not (inputs / "product.jpg").exists():
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                "1.5",
                "-i",
                str(footage),
                "-frames:v",
                "1",
                str(inputs / "product.jpg"),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(ROOT / "examples/p14/desktop-cup-local-narrated.mp4"),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(inputs / "voice.wav"),
            ],
            check=True,
        )
    for key in [
        "ECOM_AGENT_ENABLED",
        "ECOM_AGENT_EXECUTION_ENABLED",
        "ECOM_REVIEW_SNAPSHOTS_ENABLED",
        "ECOM_EXPERIMENTS_ENABLED",
    ]:
        os.environ[key] = "1"
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    guard_dir = data / "python-network-guard"
    guard_dir.mkdir(exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(r"""import ipaddress, json, os, sys
from pathlib import Path
def audit(event, args):
    if event not in ("socket.connect", "socket.getaddrinfo"): return
    address = args[1] if event == "socket.connect" else args[0]
    if event == "socket.connect" and isinstance(address, str): return  # Unix domain socket
    host = address[0] if event == "socket.connect" else address
    if host in (None, "", "localhost", b"localhost"): return
    try:
        if ipaddress.ip_address(host).is_loopback: return
    except ValueError: pass
    with Path(os.environ["ECOM_ACCEPT_EGRESS_LOG"]).open("a") as log:
        log.write(json.dumps({"pid":os.getpid(),"event":event,"host":str(host)})+"\n")
    raise PermissionError("Acceptance forbids non-loopback Python networking")
sys.addaudithook(audit)
""")
    guarded_env = {
        **os.environ,
        "PYTHONPATH": str(guard_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "ECOM_ACCEPT_EGRESS_LOG": str(data / "python-egress.jsonl"),
    }
    probe = subprocess.run(
        [sys.executable, "-c", "import socket; socket.getaddrinfo('example.invalid',443)"],
        env={**guarded_env, "ECOM_ACCEPT_EGRESS_LOG": str(data / "guard-self-test.jsonl")},
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0 and "Acceptance forbids" in probe.stderr
    check("python_non_loopback_guard_self_test")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    errors = []
    unexpected = []
    writes = list(state.get("business_requests", []))
    with (data / "server.log").open("a") as log:
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
            env=guarded_env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/session", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("API not ready")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(r):
                    url = r.request.url
                    if not url.startswith(base + "/"):
                        unexpected.append(url)
                        return r.abort()
                    if r.request.method not in ("GET", "HEAD"):
                        writes.append({"method": r.request.method, "path": url[len(base) :]})
                        state["business_requests"] = writes
                        save()
                        if any(
                            x in url
                            for x in [
                                "/qianchuan/",
                                "/reports/syncs",
                                "/volc-voice/",
                                "/distribution/tasks",
                                "/agent/",
                            ]
                        ):
                            unexpected.append(url)
                            return r.abort()
                    r.continue_()

                page.route("**/*", route)

                def get(path):
                    response = page.request.get(base + "/api" + path)
                    assert response.status == 200, (path, response.status, response.text()[:1000])
                    return response.json()

                def project():
                    return get("/customer-projects/" + state["project_id"])

                def settle():
                    expect(page.locator("#work")).to_be_visible(timeout=120000)
                    expect(page.locator("#saveSettings")).to_be_enabled(timeout=120000)

                def screenshot(name):
                    page.screenshot(path=str(data / (name + ".png")), full_page=True)

                def render(jid):
                    if get("/jobs/" + jid)["status"] == "draft":
                        expect(page.locator("#render")).to_be_enabled()
                        page.locator("#render").click()
                        expect(page.locator("#jobState")).to_contain_text("排队", timeout=20000)
                    with (data / (jid + "-worker.log")).open("a") as worker_log:
                        worker = subprocess.Popen(
                            [
                                sys.executable,
                                "-m",
                                "ecom_video.worker",
                                "--once",
                                "--data",
                                str(data / "runtime"),
                            ],
                            cwd=ROOT,
                            env=guarded_env,
                            stdout=worker_log,
                            stderr=subprocess.STDOUT,
                        )
                        deadline = time.monotonic() + 240
                        while worker.poll() is None:
                            if time.monotonic() > deadline:
                                worker.terminate()
                                worker.wait(timeout=10)
                                raise AssertionError("render deadline exceeded")
                            page.wait_for_timeout(500)
                        assert worker.returncode == 0
                    expect(page.locator("#jobState")).to_have_text("待人工审片", timeout=20000)
                    assert get("/jobs/" + jid)["status"] == "needs_review"
                    # A generated movie never approves itself.
                    check("render_stops_at_human_film_review_" + jid)
                    page.locator("#filmReviewer").fill(LABEL)
                    page.locator("#filmNote").fill(
                        "自动化确认 fixture：技术链路检查，不代表客户审片"
                    )
                    page.locator("#filmChecked").check()
                    page.locator("#acceptFilm").click()
                    expect(page.locator("#jobState")).to_have_text("已人工复核")

                for width in [1440, 390]:
                    page.set_viewport_size({"width": width, "height": 1050})
                    for path in ["/create", "/distribution", "/experiments", "/guide"]:
                        page.goto(base + path)
                        for target in ["/create", "/distribution", "/experiments", "/guide"]:
                            expect(page.locator('header a[href="' + target + '"]')).to_be_visible()
                        overflow = page.locator("header").evaluate(
                            '(e)=>Math.max(...Array.from(e.querySelectorAll("a")).map(a=>a.getBoundingClientRect().bottom))-e.getBoundingClientRect().bottom'
                        )
                        assert overflow <= 0.5, (path, width, overflow)
                    expect(page.locator("main section")).to_have_count(6)
                    screenshot("guide-" + str(width))
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.locator('main a[href="/create"]').click()
                expect(page.locator("#createProject")).to_be_enabled()
                check("workflow_navigation_and_six_step_guide")
                if state["phase"] < 1:
                    page.goto(base + "/")
                    page.locator('header a[href="/create"]').click()
                    page.locator("#newTitle").fill("验收演示 · 桌面咖啡杯（模拟复盘）")
                    page.locator("#createProject").click()
                    settle()
                    # This acceptance covers manual source selection and real ASR, not VLM accuracy.
                    for key in ["autoSelect", "referenceOnly", "strictProduct", "actionTiming"]:
                        page.locator("#" + key).uncheck()
                    flags = ["autoSelect", "referenceOnly", "strictProduct", "actionTiming"]
                    assert not any(page.locator("#" + key).is_checked() for key in flags)
                    with page.expect_response(
                        lambda r: "/api/customer-projects/" in r.url and r.request.method == "PUT"
                    ) as saved:
                        page.locator("#saveSettings").click()
                    settings = saved.value.json()["settings"]
                    assert not any(
                        settings[k]
                        for k in [
                            "auto_select",
                            "reference_only",
                            "strict_product",
                            "action_timing",
                        ]
                    ), settings
                    settle()
                    page.locator("#documents").set_input_files(str(inputs / "product.txt"))
                    expect(page.locator(".fact-choice")).to_have_count(1)
                    settle()
                    page.locator("#visuals").set_input_files(str(footage))
                    settle()
                    expect(page.locator("#mediaList")).to_contain_text("6177761.mp4")
                    page.locator("#visuals").set_input_files(str(inputs / "product.jpg"))
                    settle()
                    expect(page.locator("#mediaList")).to_contain_text("product.jpg")
                    page.locator("#voiceUpload").set_input_files(str(inputs / "voice.wav"))
                    settle()
                    expect(page.locator("#mediaList")).to_contain_text("voice.wav")
                    # No recommendation or approval exists before explicit fact/script confirmation.
                    expect(page.locator("#directions .direction")).to_have_count(0)
                    before = len(writes)
                    page.locator("#confirmFacts").click()
                    expect(page.locator("#message")).to_contain_text("先核对原文")
                    assert len(writes) == before
                    page.locator(".fact-choice").check()
                    page.locator("#factReviewer").fill(LABEL)
                    page.locator("#factNote").fill("核对已授权实拍中的可见场景，无商品功效推断")
                    page.locator("#factsChecked").check()
                    page.locator("#confirmFacts").click()
                    expect(page.locator("#scriptPanel")).to_be_visible()
                    settle()
                    page.locator("#scriptPaste").fill(script)
                    page.locator("#applyScript").click()
                    page.locator("#scriptReviewer").fill(LABEL)
                    page.locator("#scriptNote").fill("复用配音的同一原稿，已保留事实引用")
                    page.locator("#scriptChecked").check()
                    page.locator("#approveScript").click()
                    expect(page.locator("#directions .direction")).to_have_count(3, timeout=30000)
                    settle()
                    state["project_id"] = page.locator("#projectSelect").input_value()
                    save()
                    check("ui_upload_facts_script_and_three_styles")
                    page.locator('[data-style="social"]').click()
                    expect(page.locator('[data-style="social"]')).to_have_attribute(
                        "aria-pressed", "true"
                    )
                    expect(page.locator("#alignmentState")).to_contain_text(
                        "待听核", timeout=120000
                    )
                    row = project()["alignment"]
                    assert row["status"] == "needs_review" and row["result"]["sentences"]
                    state["real_alignment_id"] = row["id"]
                    check("real_local_asr_no_fixture_timestamps")
                    page.locator("#voiceReviewer").fill(LABEL)
                    page.locator("#voiceChecked").check()
                    page.locator("#makeBoard").click()
                    expect(page.locator("#shotList .customer-shot")).to_have_count(1, timeout=30000)
                    job = project()["job"]
                    state["parent_job_id"] = job["id"]
                    state["phase"] = 1
                    save()
                    screenshot("01-prepared")
                if state["phase"] < 2:
                    page.goto(base + "/create?project=" + state["project_id"])
                    settle()
                    render(state["parent_job_id"])
                    state["parent_hash"] = hashlib.sha256(
                        json.dumps(get("/jobs/" + state["parent_job_id"]), sort_keys=True).encode()
                    ).hexdigest()
                    state["phase"] = 2
                    save()
                    screenshot("02-parent-ready")

                def distribution(day, material, jid, clicks):
                    page.goto(base + "/distribution")
                    expect(page.locator("#account")).to_be_enabled()
                    if "account_id" not in state:
                        page.locator("details").filter(has=page.locator("#accountForm")).locator(
                            "summary"
                        ).click()
                        page.locator("#accountName").fill("验收模拟账户 · 非平台授权")
                        page.locator("#advertiser").fill("123")
                        page.locator("#accountForm button").click()
                        expect(page.locator("#account")).not_to_have_value("")
                        state["account_id"] = page.locator("#account").input_value()
                        save()
                    page.locator("#account").select_option(state["account_id"])
                    page.locator("#startDate").fill(day)
                    page.locator("#endDate").fill(day)
                    page.locator("#filterForm button").click()
                    report = inputs / (material + "-" + str(clicks) + ".csv")
                    report.write_text(HEADER + f"{day},{material},10,100,{clicks},1,20,100,10\n")
                    page.locator("details").filter(has=page.locator("#importForm")).locator(
                        "summary"
                    ).click()
                    page.locator("#reportFile").set_input_files(str(report))
                    page.locator("#importActor").fill(LABEL)
                    page.locator("#importWindow").fill("7d_click")
                    page.locator("#importWindowCheck").check()
                    page.locator("#importCheck").check()
                    with page.expect_response(
                        lambda r: (
                            r.url.endswith("/api/reports/import") and r.request.method == "POST"
                        )
                    ) as response:
                        page.locator("#importForm button").click()
                    assert response.value.status == 201, response.value.text()
                    # Select only an already reviewed local movie; binding is an explicit human action.
                    page.locator("details").filter(has=page.locator("#bindingForm")).locator(
                        "summary"
                    ).click()
                    expect(page.locator('#bindingJob option[value="' + jid + '"]')).to_have_count(1)
                    page.locator("#materialId").fill(material)
                    page.locator("#bindingJob").select_option(jid)
                    page.locator("#bindingActor").fill(LABEL)
                    page.locator("#bindingCheck").check()
                    with page.expect_response(
                        lambda r: (
                            r.url.endswith("/api/reports/bindings") and r.request.method == "POST"
                        )
                    ) as response:
                        page.locator("#bindingForm button").click()
                    assert response.value.status == 200, response.value.text()
                    page.locator("#reviewActor").fill(LABEL)
                    page.locator("#freezeCheck").check()
                    page.locator("#freezeButton").click()
                    expect(page.locator("#reviewNotice")).to_contain_text("已保存不可变复盘")
                    rid = page.locator("#frozenHistory").input_value()
                    assert rid
                    check("ui_report_bind_freeze_" + material + "_" + str(clicks))
                    return rid

                if state["phase"] < 3:
                    state["baseline_review_id"] = distribution(
                        "2026-10-01", "123", state["parent_job_id"], 10
                    )
                    state["baseline"] = get("/reviews/snapshots/" + state["baseline_review_id"])
                    state["phase"] = 3
                    save()
                    screenshot("03-baseline")
                if state["phase"] < 4:
                    page.goto(base + "/distribution")
                    page.locator("#frozenId").fill(state["baseline_review_id"])
                    page.locator("#openFrozenId").click()
                    expect(page.locator("#frozenView")).to_be_visible()
                    page.locator("#frozenFeatures a").filter(has_text="提出创意假设").click()
                    expect(page.locator("#expWorkspace")).to_be_visible()
                    page.locator("#expActor").fill(LABEL)
                    page.locator("#contextForm button").click()
                    expect(page.locator("#proposalForm")).to_be_visible()
                    page.locator("#hypothesis").fill(
                        "模拟假设：将实拍入点改到倒咖啡动作，观察下一轮点击率；未验证原因"
                    )
                    page.locator("#shotChanges").fill('{"source_in":3}')
                    page.locator("#proposalForm button").click()
                    expect(page.locator("#expMeta")).to_contain_text("待人工选择")
                    page.locator("#selectionNote").fill("自动化人工选择 fixture，非客户判断")
                    page.locator("#selectionCheck").check()
                    page.locator("#selectProposal").click()
                    expect(page.locator("#applyProposal")).to_be_visible()
                    page.locator("#applyProposal").click()
                    expect(page.locator("#productionSummary")).to_contain_text("draft")
                    state["experiment_id"] = page.locator("#expId").input_value()
                    state["child_job_id"] = get("/experiments/" + state["experiment_id"])[
                        "result_job_id"
                    ]
                    state["phase"] = 4
                    save()
                    check("ui_hypothesis_selection_atomic_child")
                if state["phase"] < 5:
                    page.goto(base + "/create?project=" + state["project_id"])
                    settle()
                    expect(page.locator("#customerIteration")).to_be_visible()
                    expect(page.locator("#alignmentState")).to_contain_text("待听核")
                    expect(page.locator("#render")).to_be_disabled()
                    page.locator("#voiceReviewer").fill(LABEL)
                    before = len(writes)
                    page.locator("#confirmListening").click()
                    expect(page.locator("#message")).to_contain_text("逐句听核")
                    assert len(writes) == before
                    page.locator("#voiceChecked").check()
                    # A pre-existing storyboard must not hide the only listening-confirm action.
                    expect(page.locator("#confirmListening")).to_be_visible(timeout=5000)
                    page.locator("#confirmListening").click()
                    expect(page.locator("#alignmentState")).to_contain_text("已听核")
                    page.locator("#customerIterationLink").click()
                    expect(page.locator("#productionSummary")).to_contain_text("draft")
                    page.locator("#expActor").fill(LABEL)
                    page.locator("#styleCheck").check()
                    page.locator("#confirmStyle").click()
                    expect(page.locator("#productionSummary")).to_contain_text("当前风格已确认")
                    page.locator("#customerProduction").click()
                    settle()
                    expect(page.locator("#alignmentState")).to_contain_text("已听核")
                    render(state["child_job_id"])
                    state["phase"] = 5
                    save()
                    check("ui_child_fresh_listening_style_and_film_review")
                    screenshot("04-child-ready")
                if state["phase"] < 6:
                    state["next_review_id"] = distribution(
                        "2026-10-02", "456", state["child_job_id"], 20
                    )
                    page.goto(base + "/experiments?id=" + state["experiment_id"])
                    expect(page.locator("#productionSummary")).to_contain_text("ready")
                    page.locator("#expActor").fill(LABEL)
                    page.locator("#awaitData").click()
                    expect(page.locator("#expMeta")).to_contain_text("等待客户数据")

                    def evaluate(rid, count):
                        page.locator("#nextReview").fill(rid)
                        page.locator("#readNextReview").click()
                        expect(page.locator("#newMaterial option")).to_have_count(2)
                        page.locator("#newMaterial").select_option("456")
                        page.locator("#evaluateExperiment").click()
                        expect(page.locator("#evaluations article")).to_have_count(count)

                    evaluate(state["next_review_id"], 1)
                    first = get("/experiments/" + state["experiment_id"])["evaluations"][0]
                    state["old_evaluation"] = first
                    newer = distribution("2026-10-02", "456", state["child_job_id"], 15)
                    page.goto(base + "/experiments?id=" + state["experiment_id"])
                    expect(page.locator("#evaluations article")).to_have_count(1)
                    page.locator("#expActor").fill(LABEL)
                    evaluate(newer, 2)
                    state["second_review_id"] = newer
                    state["phase"] = 6
                    save()
                    screenshot("05-comparison")
                    check("ui_next_round_and_reimport_preserve_old_evaluation")
                page.goto(base + "/experiments?id=" + state["experiment_id"])
                expect(page.locator("#evaluations article")).to_have_count(2)
                final = get("/experiments/" + state["experiment_id"])
                assert [e["absolute_difference"] for e in final["evaluations"]] == [
                    "0.100000",
                    "0.050000",
                ]
                assert final["evaluations"][0] == state["old_evaluation"]
                assert all(
                    e["causal_inference"] is False and e["winner"] is None
                    for e in final["evaluations"]
                )
                assert get("/reviews/snapshots/" + state["baseline_review_id"]) == state["baseline"]
                assert (
                    hashlib.sha256(
                        json.dumps(get("/jobs/" + state["parent_job_id"]), sort_keys=True).encode()
                    ).hexdigest()
                    == state["parent_hash"]
                )
                assert not errors and not unexpected, (errors, unexpected)
                for jid in [state["parent_job_id"], state["child_job_id"]]:
                    artifact = page.request.get(
                        base + f"/api/jobs/{jid}/artifacts/video?download=true"
                    )
                    assert artifact.status == 200
                    assert "attachment" in artifact.headers.get("content-disposition", "")
                    (
                        data / ("parent.mp4" if jid == state["parent_job_id"] else "child.mp4")
                    ).write_bytes(artifact.body())
                with page.expect_download() as download:
                    page.locator("#expExport").click()
                download.value.save_as(data / "iteration.json")
                assert json.loads((data / "iteration.json").read_text()) == final
                with sqlite3.connect(
                    f"file:{data / 'runtime/workflow.db'}?mode=ro", uri=True
                ) as connection:
                    dispatch_counts = {
                        table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                        for table in ["distribution_tasks", "qianchuan_tasks", "report_syncs"]
                    }
                assert not any(dispatch_counts.values()), dispatch_counts
                egress_log = data / "python-egress.jsonl"
                blocked_egress = egress_log.read_text().splitlines() if egress_log.exists() else []
                assert not blocked_egress, blocked_egress
                state.update(
                    completed=True,
                    page_errors=errors,
                    external_or_forbidden_requests=unexpected,
                    business_requests=writes,
                    synthetic_reports=True,
                    human_confirmations_are_automated_fixture=True,
                    real_local_asr=True,
                    python_non_loopback_attempts=blocked_egress,
                    browser_external_attempts=unexpected,
                    platform_dispatch_records=dispatch_counts,
                    network_evidence_scope="Python audit guard + browser route guard; no all-process telemetry for Node/Chromium renderer",
                )
                save()
                (data / "acceptance.json").write_text(
                    json.dumps(state, ensure_ascii=False, indent=2)
                )
                print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
                browser.close()
        except Exception:
            if "page" in locals():
                with suppress(Exception):
                    page.screenshot(path=str(data / "failure.png"), full_page=True)
                    (data / "failure-ui.txt").write_text(page.locator("body").inner_text())
            raise
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
