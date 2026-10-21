"""Isolated real-stock acceptance. All confirmations are fixtures; zero cloud synthesis."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE 脚本与审核验收，非客户人工确认"


def main():
    from fastapi.testclient import TestClient

    from ecom_video.analysis_worker import Worker as AnalysisWorker
    from ecom_video.api import create_app
    from ecom_video.media import digest, safe_path
    from ecom_video.worker import Worker

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--stage", required=True, choices=["intake", "scan", "produce"])
    args = ap.parse_args()
    data = args.data.resolve()
    assert not data.is_relative_to(ROOT), "Use a new external isolated directory"
    data.mkdir(parents=True, exist_ok=True)
    runtime = data / "runtime"
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_MEDIA_AUDIT"] = "1"
    app = create_app(runtime)
    with TestClient(app, base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def save(name, value):
            (data / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

        def request(method, url, **kwargs):
            r = c.request(method, "/api" + url, **kwargs)
            assert r.is_success, (url, r.text)
            return r.json()

        def post(url, value):
            return request("POST", url, json=value)

        if not (data / "identity.json").exists():
            assert args.stage == "intake"
            p = post(
                "/customer-projects",
                {
                    "title": "示例耳机 · 脚本与综合审核",
                    "settings": {
                        "brief": {
                            "format": "recommendation",
                            "category": "数码耳机",
                            "audience": "年轻学生和通勤人群",
                            "tone": "亲切生活分享，温暖",
                        },
                        "sfx": False,
                    },
                },
            )
            save("identity.json", {"id": p["id"], "fixture": LABEL})
        pid = json.loads((data / "identity.json").read_text())["id"]
        base, product = "/customer-projects/" + pid, "/products/" + pid

        def current():
            return request("GET", base)

        def upload(path, role):
            p = current()
            with path.open("rb") as f:
                return request(
                    "POST",
                    base + "/assets",
                    data={"revision": p["revision"], "role": role},
                    files={"file": (path.name, f, "application/octet-stream")},
                )

        p = current()
        if args.stage == "intake":
            if not p["product"]["sources"]:
                doc = "黑色头戴耳机，弧形头梁连接两侧耳罩。\n把两侧耳罩向内转动，看看收起后的样子。\n再看戴在耳边时，头梁和两侧耳罩的位置。"
                request(
                    "POST",
                    product + "/documents",
                    data={"revision": p["product"]["revision"]},
                    files={"file": ("示例观察资料.txt", doc.encode(), "text/plain")},
                )
                p = current()
                prod = post(
                    product + "/facts/confirm",
                    {
                        "revision": p["product"]["revision"],
                        "fact_ids": [f["id"] for f in p["product"]["facts"]],
                        "reviewer": LABEL,
                        "note": "示例可见外观与操作，商业SKU未知，不证明性能",
                        "confirmed": True,
                    },
                )
                prod = post(
                    product + "/scripts/generate",
                    {
                        "revision": prod["revision"],
                        "mode": "directed",
                        "brief": p["settings"]["brief"],
                    },
                )
                save("generated-script.json", prod["script_drafts"][-1])
                before = request("GET", base + "/preflight")
                assert before["gap_count"] > 0 and not before["script_confirmed"]
                save("preflight-empty.json", before)
                post(
                    product + "/scripts/confirm",
                    {
                        "revision": prod["revision"],
                        "draft_id": prod["current_draft_id"],
                        "reviewer": LABEL,
                        "note": "fixture逐句事实引用，不代表客户认可脚本",
                        "confirmed": True,
                    },
                )
            sources = json.loads(
                (ROOT / "docs/evidence/category-validation/sources.json").read_text()
            )
            sources = [r for r in sources if r.get("key") in ("headphones", "headphones-wear")]
            assert len(sources) == 2
            for row in sources:
                path = ROOT / row["path"]
                assert digest(path) == row["sha256"]
                if not any(a["name"] == path.name for a in current()["media"]):
                    upload(path, "product")
            save("sources.json", [{k: r[k] for k in ("key", "path", "sha256")} for r in sources])
            p = current()
            save("preflight-unscanned.json", request("GET", base + "/preflight"))
            for a in p["media"]:
                post(base + "/assets/" + a["id"] + "/analysis", {})
            print(
                "Intake, directed script, pending/human fixture and preflight done; local scans queued",
                flush=True,
            )
            return
        if args.stage == "scan":
            worker = AnalysisWorker(runtime)
            while any(
                (a.get("analysis") or {}).get("status") == "queued" for a in current()["media"]
            ):
                assert worker.once()
                print("Completed one local source scan", flush=True)
            p = current()
            assert all(
                (a.get("analysis") or {}).get("status") == "ready"
                for a in p["media"]
                if a["kind"] != "audio"
            ), p["media"]
            save(
                "observations.json",
                {a["name"]: a["analysis"] for a in p["media"] if a["kind"] != "audio"},
            )
            save("preflight-scanned.json", request("GET", base + "/preflight"))
            print("Fresh real local vision and material readiness saved", flush=True)
            return
        assert (data / "observations.json").exists(), "Run intake and scan first"
        p = current()
        if not any(a["role"] == "voice" for a in p["media"]):
            draft = next(
                d
                for d in p["product"]["script_drafts"]
                if d["id"] == p["product"]["current_draft_id"]
            )
            text = data / "script.txt"
            text.write_text("\n".join(s["text"] for s in draft["payload"]))
            subprocess.run(
                [
                    "say",
                    "-v",
                    "Tingting",
                    "-r",
                    "230",
                    "-f",
                    str(text),
                    "-o",
                    str(data / "voice.aiff"),
                ],
                check=True,
                timeout=60,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(data / "voice.aiff"),
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    str(data / "voice.wav"),
                ],
                check=True,
                timeout=30,
            )
            upload(data / "voice.wav", "voice")

        def prepare_aligned():
            p = current()
            if not p["job"] or p["inputs_changed"]:
                p = post(base + "/prepare", {"revision": p["revision"]})
            jid = p["job"]["id"]
            if not p["alignment"]:
                voice = next(
                    a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice"
                )
                post("/jobs/" + jid + "/alignments", {"asset_id": voice["id"]})
            deadline = time.monotonic() + 240
            while (current().get("alignment") or {}).get("status") in ("queued", "running"):
                assert time.monotonic() < deadline
                time.sleep(0.25)
            p = current()
            assert p["alignment"]["status"] in ("needs_review", "confirmed"), p["alignment"]
            if p["alignment"]["status"] != "confirmed":
                post(
                    "/jobs/" + jid + "/alignments/" + p["alignment"]["id"] + "/confirm",
                    {"reviewer": LABEL, "confirmed": True},
                )
            p = current()
            return p

        p = current()
        if not p["job"] and not (data / "automatic-plan-rejection.json").exists():
            p = request(
                "PUT",
                base,
                json={
                    "revision": p["revision"],
                    "settings": {**p["settings"], "auto_select": True},
                },
            )
        p = prepare_aligned()
        coverage = request("GET", base + "/preflight")
        if p["settings"]["auto_select"] and coverage["gap_count"]:
            r = c.post(
                "/api" + base + "/plan",
                json={
                    "revision": p["revision"],
                    "job_id": p["job"]["id"],
                    "board_revision": p["job"]["storyboard_revision"],
                    "style_id": p["recommendations"]["options"][0]["id"],
                    "fingerprint": p["recommendations"]["fingerprint"],
                    "alignment_id": p["alignment"]["id"],
                },
            )
            assert r.status_code == 422 and "素材缺口" in r.text, r.text
            save(
                "automatic-plan-rejection.json",
                {
                    "status": r.status_code,
                    "detail": r.json(),
                    "job_id": p["job"]["id"],
                    "coverage": coverage,
                },
            )
            print(
                "Actual automatic planning rejected missing action evidence before inference; switching explicitly to manual",
                flush=True,
            )
            request(
                "PUT",
                base,
                json={
                    "revision": p["revision"],
                    "settings": {**p["settings"], "auto_select": False},
                },
            )
            p = prepare_aligned()
        jid = p["job"]["id"]
        save("alignment.json", p["alignment"])
        save("preflight-measured.json", request("GET", base + "/preflight"))
        rec = p["recommendations"]
        assert len(rec["options"]) == 3
        save("recommendations.json", rec)
        if not p["job"]["storyboard"]:
            p = post(
                base + "/plan",
                {
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                    "style_id": rec["options"][0]["id"],
                    "fingerprint": rec["fingerprint"],
                    "alignment_id": p["alignment"]["id"],
                },
            )
            board = p["job"]["storyboard"]
            # Inspected real source intervals, deliberately separate from model proposals.
            assets = p["job"]["assets"]
            fold = next(a for a in assets if a["name"] == "headphones.mp4")
            wear = next(a for a in assets if a["name"] == "headphones-wear.mp4")
            selection = []
            for i, shot in enumerate(board["shots"]):
                line = p["job"]["script"].splitlines()[i]
                a, start = (
                    (fold, 4.0)
                    if "转动" in line
                    else (wear, 4.5)
                    if "戴在" in line
                    else (fold, 0.2)
                    if "头戴耳机" in line
                    else (wear, 13.0)
                    if i == len(board["shots"]) - 1
                    else (fold, 8.0)
                )
                assert start + shot["duration"] <= a["metadata"]["duration"], (
                    line,
                    start,
                    shot["duration"],
                )
                shot.update(asset_id=a["id"], source_in=start, fit="contain", motion="static")
                selection.append(
                    {
                        "line": i + 1,
                        "text": line,
                        "source": a["name"],
                        "sha256": a["sha256"],
                        "start": start,
                        "end": start + shot["duration"],
                        "basis": "manual_reviewed_demo_ranges",
                    }
                )
            board["creative"]["review_context"] = LABEL + "；实拍区间人工回看校正，非自动识别正确率"
            request(
                "PUT",
                "/jobs/" + jid + "/storyboard",
                json={"revision": p["job"]["storyboard_revision"], "board": board},
            )
            save("manual-selection.json", {"fixture": LABEL, "job_id": jid, "shots": selection})
        p = current()
        if p["job"]["status"] == "draft":
            post(
                base + "/submit",
                {
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                },
            )
        if current()["job"]["status"] == "queued":
            assert Worker(runtime).run_once()
        job = current()["job"]
        assert job["status"] == "needs_review", job["error"]
        assert not job["reviews"] and not current()["voice_takes"]
        save("snapshot.json", job["snapshot"])
        report = job["audit"]
        assert any(s["id"] == "ocr" and s["status"] == "sampled" for s in report["sections"]), (
            report["sections"]
        )
        assert any(s["id"] == "asr" and s["status"] == "checked" for s in report["sections"])
        dest = data / "deliverables"
        dest.mkdir(exist_ok=True)
        for a in job["artifacts"]:
            shutil.copy2(safe_path(runtime, a["path"]), dest / Path(a["path"]).name)
        save(
            "acceptance.json",
            {
                "fixture": LABEL,
                "project_id": pid,
                "job_id": jid,
                "status": job["status"],
                "local_voice": "macOS Tingting",
                "cloud_calls": 0,
                "automatic_selection_claimed": False,
                "output_sha256": report["output_sha256"],
                "snapshot_sha256": report["snapshot_sha256"],
                "duration": json.loads((dest / "manifest.json").read_text())["duration"],
            },
        )
        print(
            "Actual local voice, alignment, selected direction, real-film OCR/ASR and pending review passed",
            flush=True,
        )


if __name__ == "__main__":
    main()
