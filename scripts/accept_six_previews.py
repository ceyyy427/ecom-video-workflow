"""Local six-preview acceptance. Regression approvals live only in a marked engineering clone."""

import argparse
import copy
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
LABEL = "AUTOMATED FIXTURE 六方向工程验证，非客户事实/文稿/风格/听审或签收"
SOURCE_SHA = "60298358830713740127118ff7bb7a893cbd0a82f006b1127fbb5f506aeb1779"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="已核对许可的Pexels橙子原片，SHA固定")
    parser.add_argument("--stage", choices=("previews", "regression"), required=True)
    parser.add_argument("--simulate-confirmations", action="store_true")
    args = parser.parse_args()
    work = args.workspace.resolve()
    root = work / "runtime"
    if work.is_relative_to(PROJECT):
        parser.error("请使用仓库外的全新专用目录")
    work.mkdir(parents=True, exist_ok=True)
    marker = work / ".six-preview-validation"
    if not marker.exists():
        if (root / "workflow.db").exists():
            parser.error("已有未标识数据，拒绝覆盖；请换新目录")
        marker.write_text("owned isolated six-preview acceptance, no customer approvals\n")
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_MEDIA_AUDIT"] = "0"
    from fastapi.testclient import TestClient
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

    from ecom_video.api import create_app
    from ecom_video.db import Store
    from ecom_video.idea_plans import IdeaPlans
    from ecom_video.maintenance import backup, restore
    from ecom_video.media import digest, font_path, probe, safe_path
    from ecom_video.worker import Worker

    def save(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    cases_path = work / "cases.json"
    cases = json.loads(cases_path.read_text()) if cases_path.exists() else {}
    if args.stage == "previews":
        if not args.source or digest(args.source) != SOURCE_SHA:
            parser.error("需要指定许可记录对应的鲜橙实拍，SHA不符不能冒用来源")
        with TestClient(create_app(root), base_url="http://localhost") as c:
            c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

            def post(url, body):
                r = c.post("/api" + url, json=body)
                assert r.is_success, (r.status_code, r.text[:1000])
                return r.json()

            if "orange" not in cases:
                with args.source.open("rb") as stream:
                    r = c.post(
                        "/api/idea-uploads",
                        data={
                            "source_note": "Maksim Semashko / Pexels 13107467；https://www.pexels.com/license/；仅示范切片，不作产地、口味或客户SKU依据",
                            "usage_confirmed": "true",
                        },
                        files={"file": ("licensed-orange.mp4", stream, "video/mp4")},
                    )
                assert r.is_success, r.text
                asset = r.json()
                brief = {
                    "idea": "用鲜橙的切面和切片实拍，展示周末准备轻食的一个小片段",
                    "subject": "鲜橙切面",
                    "audience": "准备周末轻食的年轻人",
                    "tone": "清爽、轻快、让细节说话",
                    "mode": "footage",
                    "materials": [{"origin": "upload", "id": asset["id"]}],
                    "facts": [
                        {
                            "text": "橙色果皮，切面可见。",
                            "source": "Pexels 13107467 实拍可见，待人工核对",
                        },
                        {
                            "text": "用实拍观察切片过程。",
                            "source": "Pexels 13107467，仅观察原片，不作性能测试",
                        },
                    ],
                }
                cases["orange"] = post("/idea-plans", brief)["id"]
                save(cases_path, cases)
            if "code" not in cases:
                brief = {
                    "idea": "给中学生解释桥梁怎样把重量传到地面",
                    "subject": "桥梁怎样承重",
                    "audience": "中学生",
                    "tone": "清楚、有好奇心",
                    "facts": [
                        {
                            "text": "先观察桥面、桥墩和地面之间的关系。",
                            "source": "工程预演设定，只展示观察方法；知识结论待资料核对",
                        },
                        {
                            "text": "顺着连接关系，依次观察整体和局部。",
                            "source": "工程预演的镜头安排，不作为结构承载计算",
                        },
                    ],
                }
                cases["code"] = post("/idea-plans", brief)["id"]
                save(cases_path, cases)
            from ecom_video.idea_renderer import engine_key

            for name, pid in list(cases.items()):
                prior = c.get("/api/idea-plans/" + pid).json()
                if prior["plan"]["engine"] != engine_key():
                    save(
                        work / f"prior-{name}-{pid}.json",
                        {
                            "plan_id": pid,
                            "basis": prior["basis"],
                            "engine": prior["plan"]["engine"],
                        },
                    )
                    cases[name] = post("/idea-plans", prior["plan"]["brief"])["id"]
            save(cases_path, cases)
            results = {}
            for name, pid in cases.items():
                p = c.get("/api/idea-plans/" + pid).json()
                if p["status"] != "ready":
                    post("/idea-plans/" + pid + "/previews", {"basis": p["basis"]})
                    print("RENDER", name, pid, flush=True)
                    assert Worker(root).run_once()
                    p = c.get("/api/idea-plans/" + pid).json()
                assert p["status"] == "ready", (name, p["error"])
                assert p["completed"] == 6
                timings = []
                hashes = []
                changes = []
                canvas = Image.new("RGB", (1620, 1060), "#efeee8")
                draw = ImageDraw.Draw(canvas)
                font = ImageFont.truetype(str(font_path()), 22)
                for i, o in enumerate(p["plan"]["options"]):
                    record = p["previews"][o["id"]]
                    video = safe_path(root, record["video"]["path"])
                    meta = probe(video)
                    stream = next(s for s in meta["streams"] if s["codec_type"] == "video")
                    assert (
                        int(stream["nb_frames"]) == 210
                        and abs(float(meta["format"]["duration"]) - 7) < 0.06
                    )
                    assert not any(s["codec_type"] == "audio" for s in meta["streams"])
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"],
                        check=True,
                        timeout=30,
                    )
                    frames = []
                    for t in (0.33, 1.5, 5.2):
                        path = work / f"{name}-{o['id']}-{t}.png"
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-v",
                                "error",
                                "-y",
                                "-ss",
                                str(t),
                                "-i",
                                str(video),
                                "-frames:v",
                                "1",
                                str(path),
                            ],
                            check=True,
                            timeout=30,
                        )
                        frames.append(Image.open(path).convert("RGB"))
                    change = (
                        sum(ImageStat.Stat(ImageChops.difference(frames[0], frames[1])).mean) / 3
                    )
                    assert change > 0.1, (name, o["id"], "missing motion")
                    canvas.paste(frames[1].resize((270, 480)), (270 * i, 45))
                    canvas.paste(frames[2].resize((270, 480)), (270 * i, 560))
                    draw.text((270 * i + 8, 10), o["name"], font=font, fill="#202923")
                    hashes.append(digest(video))
                    timings.append(record["elapsed_seconds"])
                    changes.append(round(change, 4))
                assert len(set(hashes)) == 6
                canvas.save(work / f"{name}-contact.jpg")
                results[name] = {
                    "plan_id": pid,
                    "duration_each": 7,
                    "frames_each": 210,
                    "unique_video_sha256": hashes,
                    "render_seconds": timings,
                    "total_recorded_seconds": round(sum(timings), 3),
                    "within_scene_pixel_change": changes,
                    "human_approvals": [],
                    "status": "ready_for_human_choice",
                }
            # Cache replay consumes no new renderer, changes neither files nor approvals.
            svc = IdeaPlans(root, Store(root / "workflow.db"))
            before = {pid: copy.deepcopy(svc.get(pid)["previews"]) for pid in cases.values()}
            for pid in cases.values():
                svc.enqueue(pid, svc.get(pid)["basis"])
            assert Worker(root).run_once() is False
            assert all(svc.get(pid)["previews"] == before[pid] for pid in cases.values())
            results["cache_replay"] = "no_new_render"
            results["computer_use"] = False
            results["cloud_calls"] = 0
            results["platform_writes"] = 0
            save(work / "preview-acceptance.json", results)
            print("PREVIEWS PASS", flush=True)
        return
    if not args.simulate_confirmations:
        parser.error("工程回归须显式提供 --simulate-confirmations，不在客户项目记录审批")
    run = work / ("engineering-" + uuid.uuid4().hex[:10])
    run.mkdir()
    bundle = run / "backup"
    target = run / "runtime"
    backup(root, bundle)
    restore(bundle, target)
    save(
        run / "FIXTURE.json",
        {"label": LABEL, "source_runtime": str(root), "customer_approvals": False},
    )
    outcomes = {}
    with TestClient(create_app(target), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def get(url):
            r = c.get("/api" + url)
            assert r.is_success, r.text[:1000]
            return r.json()

        def post(url, data):
            r = c.post("/api" + url, json=data)
            assert r.is_success, (url, r.status_code, r.text[:1000])
            return r.json()

        for name, pid in cases.items():
            plan = get("/idea-plans/" + pid)
            option_id = "blueprint" if name == "code" else "kino-montage"
            p = post(
                "/idea-plans/" + pid + "/adopt", {"basis": plan["basis"], "option_id": option_id}
            )
            base = "/customer-projects/" + p["id"]
            product = "/products/" + p["id"]
            assert (
                p["product"]["fact_reviews"] == []
                and p["product"]["script_approvals"] == []
                and not p["job"]
            )
            prod = post(
                product + "/facts/confirm",
                {
                    "revision": p["product"]["revision"],
                    "fact_ids": [f["id"] for f in p["product"]["facts"]],
                    "reviewer": LABEL,
                    "note": LABEL,
                    "confirmed": True,
                },
            )
            prod = post(
                "/idea-plans/" + pid + "/script",
                {"project_id": p["id"], "revision": prod["revision"], "basis": plan["basis"]},
            )
            post(
                product + "/scripts/confirm",
                {
                    "revision": prod["revision"],
                    "draft_id": prod["current_draft_id"],
                    "reviewer": LABEL,
                    "note": LABEL,
                    "confirmed": True,
                    "seconds": 6,
                },
            )
            p = get(base)
            style = p["idea_plan"]["option"]["native_style"]

            def version(p):
                return {
                    "revision": p["revision"],
                    "job_id": p["job"]["id"],
                    "board_revision": p["job"]["storyboard_revision"],
                }

            def confirm(p, stage, base=base, style=style):
                return post(
                    base + "/style-reviews",
                    {
                        "revision": p["revision"],
                        "stage": stage,
                        "basis": p["delivery_reviews"][stage + "_basis"],
                        "style_id": style,
                        "reviewer": LABEL,
                        "confirmed": True,
                    },
                )

            p = confirm(p, "direction")
            p = post(base + "/prepare", {"revision": p["revision"]})
            p = post(
                base + "/plan",
                {
                    **version(p),
                    "style_id": style,
                    "fingerprint": p["recommendations"]["fingerprint"],
                },
            )
            assert [s["shot_id"] for s in p["job"]["storyboard"]["shots"]] == [
                "scene-01",
                "scene-02",
                "scene-03",
                "scene-04",
            ]
            assert sum(s["duration"] for s in p["job"]["storyboard"]["shots"]) == 24
            p = confirm(p, "storyboard")
            post(base + "/submit", version(p))
            assert Worker(target).run_once()
            p = get(base)
            parent = p["job"]
            save(run / f"{name}-parent.json", parent)
            assert parent["status"] == "needs_review", parent["error"]
            assert not parent["reviews"]
            p = post(
                base + "/revise-shot",
                {
                    **version(p),
                    "shot_id": "scene-01",
                    "request_id": uuid.uuid4().hex,
                    "changes": {"source_in": 1} if name == "orange" else {"motion": "push"},
                },
            )
            p = confirm(p, "storyboard")
            post(base + "/submit", version(p))
            assert Worker(target).run_once()
            p = get(base)
            child = p["job"]
            save(run / f"{name}-retake.json", child)
            assert child["status"] == "needs_review", child["error"]
            videos = [
                safe_path(target, next(a["path"] for a in j["artifacts"] if a["kind"] == "video"))
                for j in (parent, child)
            ]
            folders = [v.parent for v in videos]
            equal = [
                digest(folders[0] / f"scene-{i:03d}.mp4")
                == digest(folders[1] / f"scene-{i:03d}.mp4")
                for i in range(4)
            ]
            assert equal == [False, True, True, True], equal
            pcm = []
            for v in videos:
                pcm.append(
                    subprocess.check_output(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-i",
                            str(v),
                            "-map",
                            "0:a:0",
                            "-f",
                            "hash",
                            "-hash",
                            "sha256",
                            "-",
                        ],
                        text=True,
                    ).strip()
                )
            assert pcm[0] == pcm[1]
            assert (folders[0] / "subtitles.srt").read_bytes() == (
                folders[1] / "subtitles.srt"
            ).read_bytes()
            assert json.loads((folders[1] / "manifest.json").read_text())["cache"] == {
                "hits": 3,
                "rendered": 1,
                "total": 4,
            }
            comparison = get(
                base + f"/version-comparison?before={parent['id']}&after={child['id']}"
            )
            assert comparison["changed_shots"] == ["scene-01"] and not comparison["audio_changed"]
            assert get("/jobs/" + parent["id"]) == parent
            p = post(
                base + "/restore-version",
                {**version(p), "target_job_id": parent["id"], "reviewer": LABEL, "confirmed": True},
            )
            assert p["job"]["id"] == parent["id"] and not p["job"]["reviews"]
            for field in ("script", "storyboard", "assets", "artifacts", "provenance", "reviews"):
                assert p["job"][field] == parent[field]
            outcomes[name] = {
                "project_id": p["id"],
                "parent_job": parent["id"],
                "retake_job": child["id"],
                "restored_job": p["job"]["id"],
                "unchanged_other_clips": equal[1:],
                "audio_pcm_equal": True,
                "restored_original_active_version": True,
                "no_new_film_approval": True,
                "fixture": LABEL,
                "film_review": "pending",
            }
            print("REGRESSION PASS", name, flush=True)
    save(run / "acceptance.json", outcomes)
    save(work / "regression-latest.json", {"directory": str(run), "results": outcomes})


if __name__ == "__main__":
    main()
