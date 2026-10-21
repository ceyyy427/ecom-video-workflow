"""P16 isolated end-to-end: real API/SQLite, licensed footage/render, fixture human decisions."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE P16，非客户审批或真实投放数据"
HEADER = "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"


def forbidden(*args, **kwargs):
    raise AssertionError("P16 forbids network/model/platform dispatch")


@contextmanager
def offline():
    with ExitStack() as stack:
        for target in [
            "socket.socket.connect",
            "ecom_video.vision_model.observe",
            "ecom_video.clip_matching.generate",
            "ecom_video.reporting.Reporting.enqueue",
            "ecom_video.distribution.Distribution.create",
            "ecom_video.distribution.Distribution.approve",
        ]:
            stack.enter_context(patch(target, forbidden))
        yield


def fixture_timing(data, store, job):
    """Synthetic timings for a known reused voice, not ASR or real listening verification."""
    from ecom_video.alignment import input_hash
    from ecom_video.local_asr import align

    voice = next(a for a in job["assets"] if a["metadata"].get("customer_role") == "voice")
    duration = voice["metadata"]["duration"]
    result = align(
        job["script"], [{"text": job["script"], "start": 0.1, "end": duration - 0.1}], duration
    )
    aid = uuid.uuid4().hex
    with store.transaction() as c:
        c.execute(
            "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
            (
                aid,
                job["id"],
                input_hash(job, voice),
                "needs_review",
                json.dumps(result),
                None,
                None,
                time.time(),
                time.time(),
            ),
        )
    return aid


def browser_stage(data, stage, **kwargs):
    import httpx
    from playwright.sync_api import expect, sync_playwright

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    errors = []
    with (data / ("browser-" + stage + ".log")).open("w") as log:
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
                    if httpx.get(base + "/api/session", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("browser API not ready")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(base + "/")
                        else route.abort()
                    ),
                )
                if stage == "draft":
                    page.goto(base + "/experiments?review=" + kwargs["review_id"] + "&material=123")
                    expect(page.locator("#expWorkspace")).to_be_visible()
                    page.locator("#expActor").fill(LABEL)
                    page.locator("#contextForm button").click()
                    expect(page.locator("#proposalForm")).to_be_visible()
                    page.locator("#hypothesis").fill(
                        "fixture：修改第一镜实拍入点，观察下一轮点击率；尚无因果结论"
                    )
                    page.locator("#shotChanges").fill('{"source_in":3}')
                    page.locator("#proposalForm button").click()
                    expect(page.locator("#expMeta")).to_contain_text("待人工选择")
                    expect(page.locator("#applyProposal")).to_be_hidden()
                    page.locator("#selectionNote").fill(LABEL)
                    page.locator("#selectionCheck").check()
                    page.locator("#selectProposal").click()
                    expect(page.locator("#expMeta")).to_contain_text("已人工选择")
                    page.locator("#applyProposal").click()
                    expect(page.locator("#productionSummary")).to_contain_text("draft")
                    page.locator("#styleCheck").check()
                    page.locator("#confirmStyle").click()
                    expect(page.locator("#productionSummary")).to_contain_text("当前风格已确认")
                    eid = page.locator("#expId").input_value()
                    page.screenshot(path=str(data / "browser-draft.png"), full_page=True)
                    result = {"experiment_id": eid, "checks": 8}
                else:
                    page.goto(base + "/experiments?id=" + kwargs["experiment_id"])
                    expect(page.locator("#productionSummary")).to_contain_text("ready")
                    page.locator("#expActor").fill(LABEL)
                    page.locator("#awaitData").click()
                    expect(page.locator("#expMeta")).to_contain_text("等待客户数据")

                    def evaluate(review_id):
                        page.locator("#nextReview").fill(review_id)
                        page.locator("#readNextReview").click()
                        expect(page.locator("#newMaterial option")).to_have_count(2)
                        page.locator("#newMaterial").select_option("456")
                        page.locator("#evaluateExperiment").click()

                    evaluate(kwargs["review_id"])
                    expect(page.locator("#evaluations article")).to_have_count(1)
                    expect(page.locator("#evaluations")).to_contain_text("可读取描述性差值")
                    old_hash = kwargs["after_first"]()
                    evaluate(old_hash["next_review_id"])
                    expect(page.locator("#evaluations article")).to_have_count(2)
                    expect(page.locator("#evaluations article").first).to_contain_text(
                        old_hash["evaluation_hash"]
                    )
                    with page.expect_download() as download:
                        page.locator("#expExport").click()
                    download.value.save_as(data / "browser-export.json")
                    page.screenshot(path=str(data / "browser-evaluation.png"), full_page=True)
                    result = {"checks": 8, "export": str(data / "browser-export.json")}
                browser.close()
            assert not errors, errors
            return {**result, "page_errors": errors}
        finally:
            server.terminate()
            server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if data.is_relative_to(ROOT) or (data.exists() and any(data.iterdir())):
        parser.error("Use an empty data directory outside the repository")
    data.mkdir(parents=True)
    os.environ["ECOM_REVIEW_SNAPSHOTS_ENABLED"] = "1"
    os.environ["ECOM_EXPERIMENTS_ENABLED"] = "1"
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.creative_features import sha
    from ecom_video.media import digest, safe_path
    from ecom_video.worker import Worker

    c = TestClient(create_app(data), base_url="http://localhost")
    c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

    def call(method, path, **kw):
        r = c.request(method, "/api" + path, **kw)
        assert r.status_code < 400, (path, r.status_code, r.text[:1200])
        return r.json()

    def controls(e, **extra):
        return {
            "request_id": "p16-" + uuid.uuid4().hex,
            "expected_revision": e["revision"],
            "actor": LABEL,
            **extra,
        }

    store = c.app.state.store
    with offline():
        p = call(
            "POST",
            "/customer-projects",
            json={
                "title": "P16 独立实拍迭代 fixture",
                "settings": {"brief": {"format": "narrated"}, "auto_select": False},
            },
        )
        pid = p["id"]
        base = "/customer-projects/" + pid
        prod = "/products/" + pid
        footage = ROOT / "examples/p9-real/originals/6177761.mp4"
        with footage.open("rb") as f:
            p = call(
                "POST",
                base + "/assets",
                data={"revision": p["revision"], "role": "product"},
                files={"file": ("coffee-cup.mp4", f, "video/mp4")},
            )
        wav = data / "existing-p14-voice.wav"
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
                str(wav),
            ],
            check=True,
        )
        with wav.open("rb") as f:
            p = call(
                "POST",
                base + "/assets",
                data={"revision": p["revision"], "role": "voice"},
                files={"file": ("existing-voice.wav", f, "audio/wav")},
            )
        script = json.loads((ROOT / "examples/p15/submission-fixture.json").read_text())["script"]
        product = call("GET", prod)
        product = call(
            "POST",
            prod + "/documents",
            data={"revision": product["revision"]},
            files={"file": ("visible-fixture.txt", script.encode(), "text/plain")},
        )
        ids = [f["id"] for f in product["facts"]]
        product = call(
            "POST",
            prod + "/facts/confirm",
            json={
                "revision": product["revision"],
                "fact_ids": ids,
                "reviewer": LABEL,
                "note": LABEL,
                "confirmed": True,
            },
        )
        product = call(
            "POST",
            prod + "/scripts",
            json={"revision": product["revision"], "scenes": [{"text": script, "fact_ids": ids}]},
        )
        call(
            "POST",
            prod + "/scripts/confirm",
            json={
                "revision": product["revision"],
                "draft_id": product["current_draft_id"],
                "reviewer": LABEL,
                "note": LABEL,
                "confirmed": True,
                "seconds": 3,
            },
        )
        p = call("GET", base)
        p = call("POST", base + "/prepare", json={"revision": p["revision"]})
        aid = fixture_timing(data, store, p["job"])
        call(
            "POST",
            "/jobs/" + p["job"]["id"] + "/alignments/" + aid + "/confirm",
            json={"confirmed": True, "reviewer": LABEL},
        )
        p = call("GET", base)
        p = call(
            "POST",
            base + "/plan",
            json={
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
                "style_id": "social",
                "fingerprint": p["recommendations"]["fingerprint"],
                "alignment_id": aid,
            },
        )
        parent = p["job"]["id"]
        call("POST", "/jobs/" + parent + "/submit")
        worker = Worker(data)
        assert worker.run_once()
        j = store.get(parent)
        assert j["status"] == "needs_review", j.get("error")
        call(
            "POST",
            "/jobs/" + parent + "/review",
            json={
                "decision": "ready",
                "reviewer": LABEL,
                "note": LABEL,
                "confirmed": True,
            },
        )
        parent_frozen = sha(store.get(parent))
        account = call(
            "POST",
            "/distribution/accounts",
            json={"name": LABEL, "platform": "qianchuan", "advertiser_id": "123"},
        )
        account_id = account["id"]
        call(
            "POST",
            "/reports/bindings",
            json={
                "account_id": account_id,
                "material_id": "123",
                "job_id": parent,
                "actor": LABEL,
                "confirmed": True,
            },
        )

        def report(day, mid, clicks):
            return call(
                "POST",
                "/reports/import",
                data={
                    "account_id": account_id,
                    "start_date": day,
                    "end_date": day,
                    "actor": LABEL,
                    "confirmed": "true",
                    "attribution_window": "7d_click",
                    "context_confirmed": "true",
                },
                files={
                    "file": (
                        "fixture.csv",
                        (HEADER + f"{day},{mid},10,100,{clicks},1,20,100,10\n").encode(),
                        "text/csv",
                    )
                },
            )

        def freeze(day):
            return call(
                "POST",
                "/reviews/snapshots",
                json={
                    "request_id": "freeze-" + uuid.uuid4().hex,
                    "account_id": account_id,
                    "start_date": day,
                    "end_date": day,
                    "actor": LABEL,
                },
            )

        report("2026-10-01", "123", 10)
        baseline = freeze("2026-10-01")
        baseline_bytes = c.get(
            "/api/reviews/snapshots/" + baseline["review_id"] + "/export"
        ).content
    browser = {}
    if args.browser:
        browser["draft"] = browser_stage(data, "draft", review_id=baseline["review_id"])
        e = call("GET", "/experiments/" + browser["draft"]["experiment_id"])
    else:
        with offline():
            e = call(
                "POST",
                "/experiments",
                json={
                    "request_id": "p16-offline-create",
                    "review_id": baseline["review_id"],
                    "material_id": "123",
                    "parent_job_id": parent,
                    "hypothesis": "fixture：修改实拍入点，观察下一轮描述性点击率",
                    "target_metric": "ctr",
                    "change_set": {
                        "kind": "visual",
                        "shot_id": p["job"]["storyboard"]["shots"][0]["shot_id"],
                        "changes": {"source_in": 3},
                    },
                    "comparison_policy": {"min_reported_days": 1, "min_impressions": 100},
                    "actor": LABEL,
                },
            )
            e = call(
                "POST",
                "/experiments/" + e["id"] + "/select",
                json=controls(e, decision="selected", confirmed=True, note=LABEL),
            )
            e = call("POST", "/experiments/" + e["id"] + "/apply", json=controls(e))
            job = store.get(e["result_job_id"])
            e = call(
                "POST",
                "/experiments/" + e["id"] + "/style-confirm",
                json=controls(
                    e,
                    confirmed=True,
                    job_id=job["id"],
                    board_revision=job["storyboard_revision"],
                    style_id="social",
                ),
            )
    eid = e["id"]
    child = e["result_job_id"]
    with offline():
        assert sha(store.get(parent)) == parent_frozen
        j = store.get(child)
        assert j["parent_id"] == parent and j["status"] == "draft"
        # Fresh listening must be required even though visual revision inherited timestamps.
        assert c.post("/api/jobs/" + child + "/submit").status_code == 422
        aid = j["storyboard"]["creative"]["alignment_id"]
        call(
            "POST",
            "/jobs/" + child + "/alignments/" + aid + "/confirm",
            json={"confirmed": True, "reviewer": LABEL},
        )
        call("POST", "/jobs/" + child + "/submit")
        assert worker.run_once()
        j = store.get(child)
        assert j["status"] == "needs_review", j.get("error")
        call(
            "POST",
            "/jobs/" + child + "/review",
            json={
                "decision": "ready",
                "reviewer": LABEL,
                "note": LABEL,
                "confirmed": True,
            },
        )
        call(
            "POST",
            "/reports/bindings",
            json={
                "account_id": account_id,
                "material_id": "456",
                "job_id": child,
                "actor": LABEL,
                "confirmed": True,
            },
        )
        report("2026-10-02", "456", 20)
        nxt = freeze("2026-10-02")

    def after_first():
        with offline():
            old = call("GET", "/experiments/" + eid)["evaluations"][0]
            report("2026-10-02", "456", 15)
            newer = freeze("2026-10-02")
            return {"evaluation_hash": old["evaluation_hash"], "next_review_id": newer["review_id"]}

    if args.browser:
        browser["evaluate"] = browser_stage(
            data, "evaluate", experiment_id=eid, review_id=nxt["review_id"], after_first=after_first
        )
    else:
        with offline():
            e = call("GET", "/experiments/" + eid)
            e = call("POST", "/experiments/" + eid + "/await-data", json=controls(e))
            e = call(
                "POST",
                "/experiments/" + eid + "/evaluate",
                json=controls(e, next_review_id=nxt["review_id"], new_material_id="456"),
            )
            newer = after_first()
            call(
                "POST",
                "/experiments/" + eid + "/evaluate",
                json=controls(e, next_review_id=newer["next_review_id"], new_material_id="456"),
            )
    e = call("GET", "/experiments/" + eid)
    assert (
        len(e["evaluations"]) == 2
        and e["evaluations"][0]["absolute_difference"] == "0.100000"
        and e["evaluations"][1]["absolute_difference"] == "0.050000"
    )
    assert all(not x["causal_inference"] and x["winner"] is None for x in e["evaluations"])
    assert sha(store.get(parent)) == parent_frozen
    assert (
        c.get("/api/reviews/snapshots/" + baseline["review_id"] + "/export").content
        == baseline_bytes
    )
    exported = c.get("/api/experiments/" + eid + "/export").content
    fresh = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from pathlib import Path;import sys;from ecom_video.db import Store;from ecom_video.experiments import Experiments;p=Path(sys.argv[1]);sys.stdout.buffer.write(Experiments(p,Store(p/'workflow.db')).export(sys.argv[2]))",
            str(data),
            eid,
        ],
        cwd=ROOT,
    )
    assert fresh == exported
    result = {
        "phase": "P16",
        "evidence_level": "offline_fixture_with_real_narrated_render",
        "data": str(data),
        "experiment_id": eid,
        "parent_job_id": parent,
        "child_job_id": child,
        "review_id": baseline["review_id"],
        "next_review_ids": [ev["next"]["review_id"] for ev in e["evaluations"]],
        "evaluation_hashes": [ev["evaluation_hash"] for ev in e["evaluations"]],
        "parent_unchanged": True,
        "old_review_unchanged": True,
        "fresh_process_export_identical": True,
        "human_decisions_and_timing_are_automated_fixture": True,
        "synthetic_report_data": True,
        "real_renders": 2,
        "source_license": "examples/p9-real/LICENSE-SOURCES.md",
        "cloud_calls": 0,
        "model_calls": 0,
        "platform_writes": 0,
        "causal_inference": False,
        "browser": browser,
    }
    for name, jid in [("parent", parent), ("child", child)]:
        artifact = next(a for a in store.get(jid)["artifacts"] if a["kind"] == "video")
        video = safe_path(data, artifact["path"])
        result[name + "_video"] = {"path": str(video), "sha256": digest(video)}
    (data / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (data / "experiment.json").write_bytes(exported)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
