"""Offline P15 acceptance using an existing playable sample, fixture reports and real SQLite/API."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE P15，非客户账户或真人审批"
HEADER = "date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n"
FIRST = HEADER + "2026-10-01,123,10,100,5,1,20,50,10\n2026-10-01,456,0,0,0,,0,,\n"
SECOND = HEADER + "2026-10-01,123,15,100,5,1,20,50,10\n"


def forbidden(*args, **kwargs):
    raise AssertionError("P15 acceptance forbids network, model, production and platform dispatch")


def business_digest(store):
    from ecom_video.creative_features import sha

    with store.connect() as c:
        # Report imports / labels / review snapshots are intentionally separate from production.
        names = [
            r[0]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if not r[0].startswith(("sqlite_", "report_", "review_", "creative_"))
        ]
        return {
            name: sha([tuple(r) for r in c.execute('SELECT * FROM "' + name + '" ORDER BY rowid')])
            for name in names
        }


def browser_check(data, aid, old, exported):
    import httpx
    from playwright.sync_api import expect, sync_playwright

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    errors = []
    with (data / "browser-server.log").open("w") as log:
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
                raise AssertionError("isolated API did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(url + "/")
                        else route.abort()
                    ),
                )
                page.goto(url + "/distribution")
                expect(page.locator("#account")).to_have_value(aid)
                expect(page.locator("#frozenPanel")).to_be_visible()
                page.locator("#startDate").fill("2026-10-01")
                page.locator("#endDate").fill("2026-10-03")
                # Open historical evidence independently of the current live date filter.
                page.locator("#frozenId").fill(old["review_id"])
                page.locator("#openFrozenId").click()
                expect(page.locator("#frozenHash")).to_contain_text(old["snapshot_hash"])
                expect(page.locator("#frozenRows")).to_contain_text("缺少当天报表")
                expect(page.locator("#frozenRows")).to_contain_text("已覆盖但无数据行")
                expect(page.locator("#frozenFeatures")).to_contain_text(
                    old["snapshot"]["materials"][0]["creative_feature"]["video_sha256"]
                )
                page.locator("#startDate").fill("2026-10-02")
                page.locator("#startDate").dispatch_event("change")
                page.locator("#filterForm button").click()
                expect(page.locator("#frozenHash")).to_contain_text(old["snapshot_hash"])
                with page.expect_download() as download:
                    page.locator("#frozenDownload").click()
                destination = data / "browser-export.json"
                download.value.save_as(destination)
                assert destination.read_bytes() == exported
                page.locator("#verifyFrozen").click()
                expect(page.locator("#reviewNotice")).to_contain_text("冻结哈希：有效")
                # New explicit freeze and human annotation, all marked fixture.
                page.locator("#startDate").fill("2026-10-01")
                page.locator("#reviewActor").fill(LABEL)
                page.locator("#freezeCheck").check()
                page.locator("#freezeButton").click()
                expect(page.locator("#reviewNotice")).to_contain_text("已保存不可变复盘")
                expect(page.locator("#frozenHash")).not_to_contain_text(old["snapshot_hash"])
                card = (
                    page.locator("#frozenFeatures article")
                    .filter(has=page.locator("details"))
                    .first
                )
                card.locator("summary").click()
                card.get_by_placeholder("标签内容").fill("fixture 浏览器人工标签")
                card.get_by_placeholder("记录人").fill(LABEL)
                card.locator('input[type="checkbox"]').check()
                card.get_by_role("button", name="保存人工标签").click()
                expect(page.locator("#reviewNotice")).to_contain_text("当前冻结内容保持不变")
                page.locator("#frozenHistory").select_option(old["review_id"])
                expect(page.locator("#frozenHash")).to_contain_text(old["snapshot_hash"])
                expect(page.locator("#frozenFeatures")).not_to_contain_text(
                    "fixture 浏览器人工标签"
                )
                # Known incompatible sources retain raw values, never standard payment ROI.
                from ecom_video.db import Store
                from ecom_video.reporting import Reporting

                Reporting(data, Store(data / "workflow.db")).ingest(
                    aid,
                    "2026-10-01",
                    "2026-10-01",
                    [{"date": "2026-10-01", "material_id": "123", "spend": "10", "revenue": "20"}],
                    b"P15 fixture incompatible source",
                    "qianchuan_api",
                    LABEL,
                    {"metric_basis": "roi2", "currency": "USD"},
                )
                page.locator("#freezeCheck").check()
                page.locator("#freezeButton").click()
                expect(page.locator("#frozenIssues")).to_contain_text("来源口径不一致")
                expect(page.locator("#frozenRows tr").first.locator("td").nth(6)).to_have_text(
                    "未知"
                )
                expect(page.locator("#frozenRows tr").first.locator("td").nth(3)).to_have_text("10")
                page.locator("#frozenHistory").select_option(old["review_id"])
                expect(page.locator("#frozenHash")).to_contain_text(old["snapshot_hash"])
                page.screenshot(path=str(data / "browser.png"), full_page=True)
                browser.close()
            assert not errors, errors
            return {"checks": 15, "page_errors": errors, "screenshot": str(data / "browser.png")}
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
        parser.error("Use an empty acceptance directory outside the repository")
    data.mkdir(parents=True)
    os.environ["ECOM_REVIEW_SNAPSHOTS_ENABLED"] = "1"
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.creative_features import sha
    from ecom_video.db import Store
    from ecom_video.distribution import Distribution
    from ecom_video.media import digest
    from ecom_video.reporting import Reporting

    # Reuse a real, already rendered and licensed P14 sample, without any new rendering/inference.
    frozen = json.loads((ROOT / "examples/p15/submission-fixture.json").read_text())
    evidence = frozen["fixture_provenance"]
    video = data / "sample.mp4"
    shutil.copy2(ROOT / "examples/p14/desktop-cup-local-narrated.mp4", video)
    assert digest(video) == evidence["video_sha256"]
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)]
        )
    )
    assert any(s["codec_type"] == "video" for s in probe["streams"])
    store = Store(data / "workflow.db")
    job = store.create_job(LABEL, frozen["script"], 3)
    with store.transaction() as c:
        c.execute(
            "UPDATE jobs SET snapshot=?,status='needs_review',script_hash=? WHERE id=?",
            (json.dumps(frozen, ensure_ascii=False), sha(frozen), job["id"]),
        )
        c.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
            (
                "a" * 32,
                job["id"],
                "video",
                video.name,
                digest(video),
                video.stat().st_size,
                time.time(),
            ),
        )
    store.review(
        job["id"], "ready", LABEL, "fixture：复用既有 P14 实拍成片，不代表真人客户核验", True
    )
    account = Distribution(data, store).add_account(LABEL, "qianchuan", "123")
    aid = account["id"]
    reports = Reporting(data, store)
    reports.bind(aid, "123", job["id"], LABEL)
    reports.import_csv(aid, "2026-10-01", "2026-10-02", FIRST.encode(), LABEL, True)
    before = business_digest(store)
    with ExitStack() as stack:
        for target in [
            "socket.socket.connect",
            "ecom_video.vision_model.observe",
            "ecom_video.clip_matching.generate",
            "ecom_video.reporting.Reporting.enqueue",
            "ecom_video.distribution.Distribution.create",
            "ecom_video.distribution.Distribution.approve",
            "ecom_video.db.Store.submit",
            "ecom_video.db.Store.review",
        ]:
            stack.enter_context(patch(target, forbidden))
        client = stack.enter_context(TestClient(create_app(data), base_url="http://localhost"))
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]

        def call(method, path, **kw):
            response = client.request(method, "/api" + path, **kw)
            assert response.status_code < 400, (response.status_code, response.text)
            return response.json()

        command = {
            "request_id": "p15-accept-old",
            "account_id": aid,
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
            "actor": LABEL,
        }
        old = call("POST", "/reviews/snapshots", json=command)
        base = "/reviews/snapshots/" + old["review_id"]
        exported = client.get("/api" + base + "/export").content
        feature = old["snapshot"]["materials"][0]["creative_feature"]
        assert feature["video_sha256"] == digest(video)
        assert old["snapshot"]["totals"]["spend"] is None
        assert old["snapshot"]["observed_totals"]["spend"] == "10"
        assert old["snapshot"]["metric_contract"]["attribution_window"] is None
        fid = feature["feature_id"]
        for origin in ["human", "model"]:
            call(
                "POST",
                "/creative-features/" + fid + "/labels",
                json={
                    "request_id": "p15-label-" + origin,
                    "label_key": "hook_type",
                    "value": "fixture 桌面场景开头",
                    "origin": origin,
                    "actor": LABEL,
                    "evidence_field": "hook_text",
                    "confirmed": origin == "human",
                    **(
                        {"model_name": "fixture-no-model-call", "model_version": "v1"}
                        if origin == "model"
                        else {}
                    ),
                },
            )
        reports.import_csv(aid, "2026-10-01", "2026-10-01", SECOND.encode(), LABEL, True)
        assert call("POST", "/reviews/snapshots", json=command) == old
        fresh = call("POST", "/reviews/snapshots", json={**command, "request_id": "p15-accept-new"})
        assert fresh["snapshot"]["observed_totals"]["spend"] == "15"
        assert fresh["snapshot_hash"] != old["snapshot_hash"]
        assert (
            fresh["snapshot"]["materials"][0]["creative_feature"]["labels"]["model"][0]["verified"]
            is False
        )
        assert client.get("/api" + base + "/export").content == exported
        verification = call("GET", base + "/verify")
        assert verification["snapshot_hash_valid"] and all(
            s["available"] for s in verification["sources"]
        )
        assert business_digest(store) == before
    fresh_process = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import sys;from pathlib import Path;from ecom_video.db import Store;from ecom_video.review_snapshots import Reviews;r=Path(sys.argv[1]);sys.stdout.buffer.write(Reviews(r,Store(r/'workflow.db')).export(sys.argv[2]))",
            str(data),
            old["review_id"],
        ],
        cwd=ROOT,
    )
    assert fresh_process == exported
    (data / "frozen-original.json").write_bytes(exported)
    result = {
        "phase": "P15",
        "evidence_level": "offline_fixture_with_existing_real_video",
        "data": str(data),
        "account_id": aid,
        "job_id": job["id"],
        "video_sha256": digest(video),
        "video_source": "examples/p14/desktop-cup-local-narrated.mp4; existing P14 render, not rerendered",
        "license_source": "examples/p9-real/LICENSE-SOURCES.md",
        "human_checks_are_automated_fixture": True,
        "snapshot_old": {k: old[k] for k in ["review_id", "snapshot_hash"]},
        "snapshot_new": {k: fresh[k] for k in ["review_id", "snapshot_hash"]},
        "old_export_unchanged": True,
        "fresh_process_export_identical": True,
        "production_records_unchanged": True,
        "source_verification": verification,
        "cloud_calls": 0,
        "model_calls": 0,
        "platform_writes": 0,
        "p16_implemented": False,
    }
    if args.browser:
        result["browser"] = browser_check(data, aid, old, exported)
    (data / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
