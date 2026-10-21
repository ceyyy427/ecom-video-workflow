"""Resume actual local VLM/ASR/render acceptance; no injected visual outputs."""

import argparse
import json
import mimetypes
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LABEL = "Codex 自动演示确认，非客户确认或真人听核"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", choices=["opening", "pouring", "pouring-flask"])
    parser.add_argument("--inputs-only", action="store_true")
    args = parser.parse_args()
    name = args.demo
    out = ROOT / "docs/evidence/p10" / name
    out.mkdir(exist_ok=True)
    inp = ROOT / "examples/p10-real" / name
    d = json.loads((inp.parent / "demos.json").read_text())[name]
    sf = out / "run.json"
    state = json.loads(sf.read_text()) if sf.exists() else {}

    def save():
        sf.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=1800) as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def call(method, path, **kw):
            r = c.request(method, "/api" + path, **kw)
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:1500]}")
            return r.json()

        if not state.get("project_id"):
            p = call(
                "POST",
                "/customer-projects",
                json={
                    "title": d.get("title")
                    or (
                        ("红盖透明瓶 · 开盖" if name == "opening" else "深色玻璃瓶 · 倒水")
                        + "实拍动作演示"
                    ),
                    "settings": {
                        "auto_select": True,
                        "strict_product": True,
                        "action_timing": True,
                        "brief": {
                            "format": "narrated",
                            "category": "家居 瓶子",
                            "tone": "简洁 克制",
                        },
                        "brand_name": "实拍动作 · 演示",
                    },
                },
            )
            state["project_id"] = p["id"]
            save()
        pid = state["project_id"]
        base = "/customer-projects/" + pid
        prod = "/products/" + pid
        p = call("GET", base)
        negative = "3756147" if name == "opening" else "7551085"
        for file, path, role in [
            ("商品参照.jpg", inp / "reference.jpg", "product"),
            ("素材A.mp4", inp.parent / "originals" / f"pexels-{d['id']}.mp4", "product"),
            ("素材B.mp4", inp.parent / "originals" / f"pexels-{negative}.mp4", "product"),
            ("配音.wav", inp / "voice.wav", "voice"),
        ]:
            if not any(a["name"] == file for a in p["media"]):
                with path.open("rb") as f:
                    p = call(
                        "POST",
                        base + "/assets",
                        data={"revision": p["revision"], "role": role},
                        files={"file": (file, f, mimetypes.guess_type(file)[0])},
                    )
        ref = next(a for a in p["media"] if a["name"] == "商品参照.jpg")
        if p["settings"].get("product_reference_id") != ref["id"]:
            p = call(
                "PUT",
                base,
                json={
                    "revision": p["revision"],
                    "settings": {**p["settings"], "product_reference_id": ref["id"]},
                },
            )
        if not p["settings"].get("reference_only"):
            p = call(
                "PUT",
                base,
                json={
                    "revision": p["revision"],
                    "settings": {**p["settings"], "reference_only": True},
                },
            )
        product = call("GET", prod)
        if not product["sources"]:
            with (inp / "product.txt").open("rb") as f:
                product = call(
                    "POST",
                    prod + "/documents",
                    data={"revision": product["revision"]},
                    files={"file": ("product.txt", f, "text/plain")},
                )
        facts = [product["facts"][0]["id"]]
        if not product["current_review_id"]:
            product = call(
                "POST",
                prod + "/facts/confirm",
                json={
                    "revision": product["revision"],
                    "fact_ids": facts,
                    "reviewer": LABEL,
                    "note": "许可实拍外观动作演示，不声称品牌或SKU；不同款素材B仅作为负例。",
                    "confirmed": True,
                },
            )
        if product["status"] != "script_confirmed":
            product = call(
                "POST",
                prod + "/scripts",
                json={
                    "revision": product["revision"],
                    "scenes": [{"text": line, "fact_ids": facts} for line in d["lines"]],
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
                    "note": "演示流程自动记录，不代表客户签字。",
                    "seconds": 3,
                },
            )
        print("PROJECT", pid, flush=True)
        if args.inputs_only:
            return
        p = call("GET", base)
        for a in p["media"]:
            if a["kind"] != "audio" and (
                a.get("analysis_stale") or (a.get("analysis") or {}).get("status") != "ready"
            ):
                call("POST", base + "/assets/" + a["id"] + "/analysis")
        previous = None
        start = time.monotonic()
        while True:
            p = call("GET", base)
            visual = [a for a in p["media"] if a["kind"] != "audio"]
            status = [(a["name"], a["analysis"]["status"], a["analysis"]["stage"]) for a in visual]
            if status != previous:
                print("ANALYSIS", status, flush=True)
                previous = status
            if all(a["analysis"]["status"] == "ready" for a in visual):
                break
            if any(a["analysis"]["status"] in ("partial", "failed", "cancelled") for a in visual):
                (out / "failed-analysis.json").write_text(
                    json.dumps(visual, ensure_ascii=False, indent=2)
                )
                raise RuntimeError("Analysis failed; see artifact")
            if time.monotonic() - start > 2700:
                raise TimeoutError("analysis deadline")
            time.sleep(3)
        (out / "analyses.json").write_text(json.dumps(visual, ensure_ascii=False, indent=2))
        state["analysis_seconds"] = time.monotonic() - start
        save()
        p = call("POST", base + "/prepare", json={"revision": p["revision"]})
        jid = p["job"]["id"]
        if state.get("job_id") != jid:
            for key in ("status", "video", "manual_job_id", "final_video"):
                state.pop(key, None)
        state["job_id"] = jid
        save()
        if not p["alignment"]:
            voice = next(
                a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice"
            )
            call("POST", f"/jobs/{jid}/alignments", json={"asset_id": voice["id"]})
        deadline = time.monotonic() + 300
        while True:
            p = call("GET", base)
            a = p["alignment"]
            if a["status"] != "running":
                break
            if time.monotonic() > deadline:
                raise TimeoutError("alignment")
            time.sleep(2)
        if a["status"] == "needs_review":
            call(
                "POST",
                f"/jobs/{jid}/alignments/{a['id']}/confirm",
                json={"confirmed": True, "reviewer": LABEL},
            )
        elif a["status"] != "confirmed":
            raise RuntimeError(str(a))
        p = call("GET", base)
        if not p["job"]["storyboard"]:
            p = call(
                "POST",
                base + "/plan",
                json={
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                    "style_id": "social",
                    "fingerprint": p["recommendations"]["fingerprint"],
                    "alignment_id": p["alignment"]["id"],
                },
            )
        (out / "auto-plan.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        print("PLAN", p["planning_notes"], flush=True)
        if p["job"]["status"] == "draft":
            model = json.loads((ROOT / "var/models/vision.json").read_text())["model"]
            httpx.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=60,
                trust_env=False,
            ).raise_for_status()
            p = call(
                "POST",
                base + "/submit",
                json={
                    "revision": p["revision"],
                    "job_id": jid,
                    "board_revision": p["job"]["storyboard_revision"],
                },
            )
        deadline = time.monotonic() + 900
        previous = None
        while p["job"]["status"] not in ("needs_review", "ready"):
            if p["job"]["status"] != previous:
                print("RENDER", p["job"]["status"], flush=True)
                previous = p["job"]["status"]
            if p["job"]["status"] in ("failed", "blocked", "cancelled"):
                raise RuntimeError(str(p["job"]))
            if time.monotonic() > deadline:
                raise TimeoutError("render")
            time.sleep(3)
            p = call("GET", base)
        (out / "result.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        state["status"] = p["job"]["status"]
        state["video"] = str(
            ROOT / "var" / next(a["path"] for a in p["job"]["artifacts"] if a["kind"] == "video")
        )
        save()
        print(state, flush=True)


if __name__ == "__main__":
    main()
