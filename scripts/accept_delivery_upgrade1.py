"""Main-workbench API acceptance in a new external directory; all approvals are fixtures."""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE 交付升级一期，非客户事实/听核/签收"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--application", type=Path, help="验证已安装副本的运行源码")
    ap.add_argument("--case", type=Path, required=True)
    ap.add_argument("--stage", choices=["intake", "produce", "retake", "verify"], required=True)
    ap.add_argument("--simulate-confirmations", action="store_true")
    args = ap.parse_args()
    application = args.application.resolve() if args.application else ROOT
    sys.path.insert(0, str(application))
    import ecom_video

    assert Path(ecom_video.__file__).resolve().is_relative_to(application), "必须使用目标应用源码"
    work = args.workspace.resolve()
    if work.is_relative_to(ROOT) or not args.simulate_confirmations:
        ap.error("须使用仓库外专用目录和显式--simulate-confirmations")
    case = json.loads(args.case.read_text())
    runtime = work / "runtime"
    work.mkdir(parents=True, exist_ok=True)
    if (runtime / "workflow.db").exists() and not (work / "project.json").exists():
        ap.error("目录已有未知数据，不能覆盖")
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_MEDIA_AUDIT"] = "0"
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.media import digest, safe_path
    from ecom_video.worker import Worker

    def save(name, value):
        (work / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    with TestClient(create_app(runtime), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def request(method, url, **kwargs):
            response = c.request(method, "/api" + url, **kwargs)
            if not response.is_success:
                raise RuntimeError(f"{method} {url}: {response.status_code} {response.text[:1200]}")
            return response.json()

        def post(url, body):
            return request("POST", url, json=body)

        if args.stage == "intake":
            assert not (work / "project.json").exists(), "已存在验收工程，请续跑下一阶段"
            p = post(
                "/customer-projects",
                {
                    "title": LABEL + " · 藏蓝山甲LT",
                    "settings": {
                        "delivery_version": 1,
                        "identity_lock": case["identity"],
                        "brief": case["brief"],
                        "auto_select": False,
                        "sfx": False,
                        "review_context": LABEL,
                    },
                },
            )
            pid = p["id"]
            save("project.json", {"id": pid, "fixture": LABEL})
        else:
            pid = json.loads((work / "project.json").read_text())["id"]
        base, product = "/customer-projects/" + pid, "/products/" + pid

        def current():
            return request("GET", base)

        def version(p):
            return {
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
            }

        def confirm(p, stage):
            return post(
                base + "/style-reviews",
                {
                    "revision": p["revision"],
                    "stage": stage,
                    "style_id": case["style_id"],
                    "basis": p["delivery_reviews"][stage + "_basis"],
                    "confirmed": True,
                    "reviewer": LABEL,
                },
            )

        if args.stage == "intake":
            p = current()
            for path in case["documents"]:
                source = Path(path)
                with source.open("rb") as src:
                    request(
                        "POST",
                        product + "/documents",
                        data={"revision": p["product"]["revision"]},
                        files={"file": (source.name, src, "application/octet-stream")},
                    )
                p = current()
            for item in case["visuals"]:
                source = Path(item["path"])
                assert digest(source) == item["sha256"]
                with source.open("rb") as src:
                    p = request(
                        "POST",
                        base + "/assets",
                        data={"revision": p["revision"], "role": item["role"]},
                        files={"file": (source.name, src, "video/mp4")},
                    )
                asset = p["media"][-1]
                p = request(
                    "PUT",
                    base + "/assets/" + asset["id"],
                    json={
                        "revision": p["revision"],
                        "role": asset["role"],
                        "note": LABEL + "；复用此前人工选段，不代表新模型识别",
                        "identity": {**case["identity"], "reviewer": LABEL, "confirmed": True},
                    },
                )
                print("INTAKE", source.name, flush=True)
            for path, role in [(case["voice"], "voice"), (case["music"], "music")]:
                source = Path(path)
                with source.open("rb") as src:
                    p = request(
                        "POST",
                        base + "/assets",
                        data={"revision": p["revision"], "role": role},
                        files={"file": (source.name, src, "audio/wav")},
                    )
            lines = Path(case["script"]).read_text().strip().splitlines()
            facts = {f["text"]: f["id"] for f in p["product"]["facts"]}
            assert all(line in facts for line in lines), "工程文稿来源须完整提取"
            prod = post(
                product + "/facts/confirm",
                {
                    "revision": p["product"]["revision"],
                    "fact_ids": [facts[s] for s in lines],
                    "reviewer": LABEL,
                    "note": "既有确认稿作为隔离工程输入，不代客户审批",
                    "confirmed": True,
                },
            )
            prod = post(
                product + "/scripts",
                {
                    "revision": prod["revision"],
                    "scenes": [{"text": s, "fact_ids": [facts[s]]} for s in lines],
                },
            )
            post(
                product + "/scripts/confirm",
                {
                    "revision": prod["revision"],
                    "draft_id": prod["current_draft_id"],
                    "reviewer": LABEL,
                    "note": LABEL,
                    "confirmed": True,
                    "seconds": 4,
                },
            )
            p = current()
            save("directions.json", p["recommendations"])
            assert case["style_id"] in {o["id"] for o in p["recommendations"]["options"]}
            p = confirm(p, "direction")
            p = post(base + "/prepare", {"revision": p["revision"]})
            save("prepared.json", p)
            print("PREPARED", pid, flush=True)
        elif args.stage == "produce":
            p = current()
            if p["job"]["storyboard"] and p["job"]["status"] == "failed":
                post("/jobs/" + p["job"]["id"] + "/retry", {})
                assert Worker(runtime).run_once()
                p = current()
                save("parent.json", p["job"])
                assert p["job"]["status"] == "needs_review", p["job"]["error"]
                print("PARENT retry", p["job"]["id"], flush=True)
                return
            assert not p["job"]["storyboard"], "已生成分镜，请用新目录或继续下一阶段"
            voice = next(
                a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice"
            )
            if not p["alignment"]:
                post("/jobs/" + p["job"]["id"] + "/alignments", {"asset_id": voice["id"]})
            deadline = time.monotonic() + 360
            while (current()["alignment"] or {}).get("status") in ("running", "queued"):
                assert time.monotonic() < deadline, "本机对齐超时，保留数据"
                time.sleep(0.5)
            p = current()
            save("fresh-alignment.json", p["alignment"])
            assert p["alignment"]["status"] == "needs_review", p["alignment"]
            # Replay the exact previously listened timestamp corrections through the editor.
            known = json.loads(Path(case["alignment"]).read_text())
            post(
                "/jobs/" + p["job"]["id"] + "/alignments/" + p["alignment"]["id"] + "/confirm",
                {
                    "reviewer": LABEL,
                    "confirmed": True,
                    "result": {
                        "sentences": [
                            {"words": [{"start": w["start"], "end": w["end"]} for w in s["words"]]}
                            for s in known["sentences"]
                        ]
                    },
                },
            )
            p = current()
            p = post(
                base + "/plan",
                {
                    **version(p),
                    "style_id": case["style_id"],
                    "fingerprint": p["recommendations"]["fingerprint"],
                    "alignment_id": p["alignment"]["id"],
                },
            )
            board = copy.deepcopy(p["job"]["storyboard"])
            assets = {Path(a["name"]).stem: a for a in p["job"]["assets"]}
            for i, (shot, spec) in enumerate(zip(board["shots"], case["shots"], strict=True)):
                cuts = [{**cut, "asset_id": assets[cut["source"]]["id"]} for cut in spec["cuts"]]
                for cut in cuts:
                    cut.pop("source")
                shot.update(
                    source_cuts=cuts,
                    asset_id=cuts[0]["asset_id"],
                    source_in=cuts[0]["source_in"],
                    duration=spec["duration"],
                    motion="static",
                    fit="cover",
                    treatment="footage",
                    transition="cut",
                    headline="",
                    shot_recipe="none",
                    motion_plan={
                        "version": 2,
                        "strength": "subtle",
                        "visual_finish": "polished-v1",
                        "protect_action": True,
                        "windows": [],
                        "intent": "action" if i == 4 else "detail",
                    },
                )
            request(
                "PUT",
                "/jobs/" + p["job"]["id"] + "/storyboard",
                json={"revision": p["job"]["storyboard_revision"], "board": board},
            )
            p = current()
            blocked = c.post("/api/jobs/" + p["job"]["id"] + "/submit")
            assert blocked.status_code == 409
            p = confirm(p, "storyboard")
            post(base + "/submit", version(p))
            assert Worker(runtime).run_once()
            p = current()
            save("parent.json", p["job"])
            assert p["job"]["status"] == "needs_review", p["job"]["error"]
            print("PARENT", p["job"]["id"], flush=True)
        elif args.stage == "retake":
            p = current()
            parent = json.loads((work / "parent.json").read_text())
            assert p["job"]["id"] == parent["id"]
            p = post(
                base + "/revise-shot",
                {
                    **version(p),
                    "shot_id": parent["storyboard"]["shots"][0]["shot_id"],
                    "request_id": "delivery1-single-" + pid,
                    "changes": {"headline": "穿得利落"},
                },
            )
            assert not p["delivery_reviews"]["storyboard"]
            p = confirm(p, "storyboard")
            post(base + "/submit", version(p))
            assert Worker(runtime).run_once()
            p = current()
            save("retake.json", p["job"])
            assert p["job"]["status"] == "needs_review", p["job"]["error"]
            assert request("GET", "/jobs/" + parent["id"]) == parent
            print("RETAKE", p["job"]["id"], flush=True)
        else:
            jobs = [
                json.loads((work / name).read_text()) for name in ["parent.json", "retake.json"]
            ]
            manifests, folders = [], []
            pcm = []
            for job in jobs:
                video = next(a for a in job["artifacts"] if a["kind"] == "video")
                path = safe_path(runtime, video["path"])
                folder = path.parent
                folders.append(folder)
                manifests.append(json.loads((folder / "manifest.json").read_text()))
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                    check=True,
                    timeout=120,
                )
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-f",
                        "hash",
                        "-hash",
                        "sha256",
                        "-",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120,
                )
                pcm.append(result.stdout.strip())
            equal = [
                digest(folders[0] / f"scene-{i:03d}.mp4")
                == digest(folders[1] / f"scene-{i:03d}.mp4")
                for i in range(6)
            ]
            assert equal == [False, True, True, True, True, True], equal
            assert pcm[0] == pcm[1]
            assert (folders[0] / "subtitles.srt").read_bytes() == (
                folders[1] / "subtitles.srt"
            ).read_bytes()
            assert manifests[1]["cache"] == {"hits": 5, "rendered": 1, "total": 6}
            assert all(j["status"] == "needs_review" and not j["reviews"] for j in jobs)
            save(
                "acceptance.json",
                {
                    "fixture": LABEL,
                    "customer_film_review": "pending",
                    "only_first_scene_changed": True,
                    "other_scenes_unchanged": equal[1:],
                    "pcm_equal": True,
                    "srt_equal": True,
                    "cache": manifests[1]["cache"],
                    "duration": manifests[0]["duration"],
                    "clock": manifests[0]["delivery_timeline"],
                    "project_id": pid,
                    "jobs": [j["id"] for j in jobs],
                    "new_cloud_calls": 0,
                    "selection_method": "replayed existing manual source choices; no new VLM inference",
                    "computer_use": False,
                    "platform_writes": False,
                },
            )
            print("VERIFIED", json.dumps(manifests[1]["cache"]), flush=True)


if __name__ == "__main__":
    main()
