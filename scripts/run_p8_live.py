"""Resumable live local-model acceptance on a clearly fictional demo product.

No model mocks, injected rankings, or prewritten analysis are used. Demo confirmations
are explicitly automated; the resulting film remains needs_review for the user.
"""

import argparse
import json
import mimetypes
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/p8-live"
INPUT = ROOT / "examples/p8-live"
STATE = OUT / "run.json"
LABEL = "Codex 演示自动确认，非客户确认或真人听核"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-only", action="store_true")
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=900) as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def call(method, path, **kw):
            r = c.request(method, "/api" + path, **kw)
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:1200]}")
            return r.json()

        def save():
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

        if not state.get("project_id"):
            p = call(
                "POST",
                "/customer-projects",
                json={
                    "title": "拾光随行杯 · 虚构商品 · 本机视觉实测 v2",
                    "settings": {
                        "auto_select": True,
                        "brief": {
                            "format": "narrated",
                            "category": "家居 杯子",
                            "audience": "喜欢简洁桌面的人",
                            "tone": "克制 清晰",
                        },
                        "brand_name": "拾光 · 演示",
                    },
                },
            )
            state["project_id"] = p["id"]
            save()
        pid = state["project_id"]
        base = "/customer-projects/" + pid
        prod = "/products/" + pid
        p = call("GET", base)
        for file, role in [
            ("商品图.png", "product"),
            ("素材01.mp4", "product"),
            ("voice.wav", "voice"),
            ("music.wav", "music"),
        ]:
            if not any(a["name"] == file for a in p["media"]):
                with (INPUT / file).open("rb") as f:
                    p = call(
                        "POST",
                        base + "/assets",
                        data={"revision": p["revision"], "role": role},
                        files={"file": (file, f, mimetypes.guess_type(file)[0])},
                    )
        product = call("GET", prod)
        if not product["sources"]:
            with (INPUT / "product.txt").open("rb") as f:
                product = call(
                    "POST",
                    prod + "/documents",
                    data={"revision": product["revision"]},
                    files={"file": ("product.txt", f, "text/plain")},
                )
        if not product["current_review_id"]:
            facts = [
                f
                for f in product["facts"]
                if any(t in f["text"] for t in ["奶白", "深色杯盖", "桌边场景"])
            ]
            assert len(facts) >= 3, product["facts"]
            product = call(
                "POST",
                prod + "/facts/confirm",
                json={
                    "revision": product["revision"],
                    "fact_ids": [f["id"] for f in facts],
                    "reviewer": LABEL,
                    "note": "用户授权创建虚构商品。只核对可见外观；不宣称性能。不是真实客户资料审核。",
                    "confirmed": True,
                },
            )
        if product["status"] != "script_confirmed":
            facts = [
                f["id"]
                for f in product["facts"]
                if any(t in f["text"] for t in ["奶白", "深色杯盖", "桌边场景"])
            ]
            product = call(
                "POST",
                prod + "/scripts",
                json={
                    "revision": product["revision"],
                    "scenes": [
                        {"text": line, "fact_ids": facts}
                        for line in (INPUT / "script.txt").read_text().splitlines()
                    ],
                },
            )
            call(
                "POST",
                prod + "/scripts/confirm",
                json={
                    "revision": product["revision"],
                    "draft_id": product["current_draft_id"],
                    "confirmed": True,
                    "reviewer": LABEL,
                    "note": "演示文稿，自动化演示流程记录，不代表客户签字。",
                    "seconds": 3,
                },
            )
        print("DEMO PROJECT", pid, flush=True)
        if args.inputs_only:
            return
        p = call("GET", base)
        for a in p["media"]:
            if a["kind"] != "audio" and (a.get("analysis") or {}).get("status") != "ready":
                call("POST", base + "/assets/" + a["id"] + "/analysis")
        previous = None
        started = time.monotonic()
        while True:
            p = call("GET", base)
            visual = [a for a in p["media"] if a["kind"] != "audio"]
            status = [
                (
                    a["name"],
                    (a.get("analysis") or {}).get("status"),
                    (a.get("analysis") or {}).get("stage"),
                )
                for a in visual
            ]
            if status != previous:
                print("ANALYSIS", status, flush=True)
                previous = status
            if all(a.get("analysis") and a["analysis"]["status"] == "ready" for a in visual):
                break
            failed = [
                a
                for a in visual
                if a.get("analysis")
                and a["analysis"]["status"] in ("partial", "failed", "cancelled")
            ]
            if failed:
                (OUT / "failed-analysis.json").write_text(
                    json.dumps(failed, ensure_ascii=False, indent=2)
                )
                raise RuntimeError("Live analysis did not complete; see failed-analysis.json")
            if time.monotonic() - started > 1800:
                raise TimeoutError("analysis deadline")
            time.sleep(3)
        (OUT / "analyses.json").write_text(json.dumps(visual, ensure_ascii=False, indent=2))
        state["analysis_seconds"] = round(time.monotonic() - started, 2)
        save()
        p = call("POST", base + "/prepare", json={"revision": p["revision"]})
        job = p["job"]
        jid = job["id"]
        state["job_id"] = jid
        save()
        if not p["alignment"]:
            voice = next(a for a in job["assets"] if a["metadata"].get("customer_role") == "voice")
            call("POST", f"/jobs/{jid}/alignments", json={"asset_id": voice["id"]})
        deadline = time.monotonic() + 300
        while True:
            p = call("GET", base)
            alignment = p["alignment"]
            if alignment["status"] != "running":
                break
            if time.monotonic() > deadline:
                raise TimeoutError("alignment deadline")
            time.sleep(2)
        if alignment["status"] == "needs_review":
            call(
                "POST",
                f"/jobs/{jid}/alignments/{alignment['id']}/confirm",
                json={"confirmed": True, "reviewer": LABEL},
            )
        elif alignment["status"] != "confirmed":
            raise RuntimeError(str(alignment))
        p = call("GET", base)
        if not p["job"]["storyboard"]:
            started = time.monotonic()
            p = call(
                "POST",
                base + "/plan",
                json={
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                    "style_id": "lab",
                    "fingerprint": p["recommendations"]["fingerprint"],
                    "alignment_id": p["alignment"]["id"],
                },
            )
            state["matching_seconds"] = round(time.monotonic() - started, 2)
            save()
        (OUT / "auto-plan.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        print("REAL MODEL PLAN", p["planning_notes"], flush=True)
        # Free this demo's VLM before Chromium rendering on the 8 GB acceptance machine.
        # No other models are unloaded or changed.
        if p["job"]["status"] == "draft":
            config = json.loads((ROOT / "var/models/vision.json").read_text())
            with httpx.Client(trust_env=False, timeout=60) as local:
                unload = local.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": config["model"], "keep_alive": 0},
                )
                unload.raise_for_status()
                (OUT / "model-unload.json").write_text(unload.text)
        if p["job"]["status"] == "draft":
            p = call(
                "POST",
                base + "/submit",
                json={
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                },
            )
        previous = None
        deadline = time.monotonic() + 600
        while p["job"]["status"] not in ("needs_review", "ready"):
            if p["job"]["status"] != previous:
                print("RENDER", p["job"]["status"], flush=True)
                previous = p["job"]["status"]
            if p["job"]["status"] in ("failed", "blocked", "cancelled"):
                raise RuntimeError(str(p["job"].get("error")))
            if time.monotonic() > deadline:
                raise TimeoutError("render deadline")
            time.sleep(2)
            p = call("GET", base)
        (OUT / "result.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        state["status"] = p["job"]["status"]
        state["video"] = str(
            ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
        )
        state["source_notice"] = (
            "Fictional product, animated stills, synthetic voice; REAL local VLM outputs. Human film review pending."
        )
        save()
        print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
