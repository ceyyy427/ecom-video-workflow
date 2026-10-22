"""Real-media regression on an existing isolated fixture; never grants customer approval."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE P0 编辑验收，非客户审批"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--application", type=Path, help="验证已安装副本的运行源码")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulate-confirmations", action="store_true")
    args = parser.parse_args()
    application = args.application.resolve() if args.application else ROOT
    sys.path.insert(0, str(application))
    import ecom_video

    assert Path(ecom_video.__file__).resolve().is_relative_to(application), "必须使用目标应用源码"
    work, out = args.workspace.resolve(), args.output.resolve()
    project = json.loads((work / "project.json").read_text())
    if (
        work.is_relative_to(ROOT)
        or out.exists()
        or not args.simulate_confirmations
        or "FIXTURE" not in project.get("fixture", "")
    ):
        parser.error("仅支持已知仓库外工程夹具、全新输出目录及显式模拟确认")
    out.mkdir(parents=True)
    os.environ["ECOM_QIANCHUAN_WRITES"] = "0"
    os.environ["ECOM_MEDIA_AUDIT"] = "0"
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app
    from ecom_video.media import digest, safe_path
    from ecom_video.worker import Worker

    runtime = work / "runtime"
    base = "/api/customer-projects/" + project["id"]
    with TestClient(create_app(runtime), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def req(method, url, **kw):
            r = c.request(method, url, **kw)
            assert r.is_success, (r.status_code, r.text[:2000])
            return r.json()

        def current():
            return req("GET", base)

        def version(p):
            return {
                "revision": p["revision"],
                "job_id": p["job"]["id"],
                "board_revision": p["job"]["storyboard_revision"],
            }

        def save(name, data):
            (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))

        def preserved(job):
            return {k: v for k, v in job.items() if k not in ("events", "updated_at")}

        original = json.loads((work / "parent.json").read_text())
        original_now = req("GET", "/api/jobs/" + original["id"])
        assert preserved(original_now) == preserved(original)
        p = req(
            "POST",
            base + "/restore-version",
            json={
                **version(current()),
                "target_job_id": original["id"],
                "confirmed": True,
                "reviewer": LABEL,
            },
        )
        assert preserved(p["job"]) == preserved(original)
        parents = []
        for index, changes in [
            (4, {"caption_note": "防泼水演示，非防水等级测试"}),
            (0, {"headline": "穿得利落"}),
        ]:
            sid = p["job"]["storyboard"]["shots"][index]["shot_id"]
            body = {**version(p), "shot_id": sid, "changes": changes}
            impact = req("POST", base + "/edit-impact", json=body)
            assert impact["affected_shots"] == [sid] and impact["audio_changed"] is False
            save(f"impact-{index}.json", impact)
            p = req(
                "POST",
                base + "/revise-shot",
                json={**body, "request_id": "p0-" + out.name + "-" + str(index)},
            )
            p = req(
                "POST",
                base + "/style-reviews",
                json={
                    "revision": p["revision"],
                    "stage": "storyboard",
                    "style_id": "cinema",
                    "basis": p["delivery_reviews"]["storyboard_basis"],
                    "confirmed": True,
                    "reviewer": LABEL,
                },
            )
            req("POST", base + "/submit", json=version(p))
            assert Worker(runtime).run_once()
            p = current()
            assert p["job"]["status"] == "needs_review", p["job"].get("error")
            assert not p["job"]["reviews"]
            parents.append(p["job"])
            save("parent.json" if index == 4 else "retake.json", p["job"])
            print("rendered", p["job"]["id"], flush=True)
        a, b = parents
        comparison = req(
            "GET", base + "/version-comparison", params={"before": a["id"], "after": b["id"]}
        )
        assert comparison["changed_shots"] == [a["storyboard"]["shots"][0]["shot_id"]]
        assert not comparison["audio_changed"] and not comparison["script_changed"]
        folders = []
        pcm = []
        for job in parents:
            video = safe_path(
                runtime, next(x["path"] for x in job["artifacts"] if x["kind"] == "video")
            )
            folders.append(video.parent)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"],
                check=True,
                timeout=120,
            )
            pcm.append(
                subprocess.check_output(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(video),
                        "-map",
                        "0:a:0",
                        "-f",
                        "hash",
                        "-hash",
                        "sha256",
                        "-",
                    ],
                    timeout=120,
                )
                .decode()
                .strip()
            )
        equal = [
            digest(folders[0] / f"scene-{i:03d}.mp4") == digest(folders[1] / f"scene-{i:03d}.mp4")
            for i in range(6)
        ]
        assert equal == [False, True, True, True, True, True]
        assert pcm[0] == pcm[1]
        assert (folders[0] / "subtitles.srt").read_bytes() == (
            folders[1] / "subtitles.srt"
        ).read_bytes()
        cache = json.loads((folders[1] / "manifest.json").read_text())["cache"]
        assert cache == {"hits": 5, "rendered": 1, "total": 6}
        p = req(
            "POST",
            base + "/restore-version",
            json={**version(p), "target_job_id": a["id"], "confirmed": True, "reviewer": LABEL},
        )
        assert (
            preserved(p["job"]) == preserved(a)
            and preserved(req("GET", "/api/jobs/" + b["id"])) == preserved(b)
            and preserved(req("GET", "/api/jobs/" + original["id"])) == preserved(original)
        )
        timeline = req("GET", base + "/timeline")
        assert timeline["captions"] and timeline["caption_status"] == "rendered"
        receipt = req("POST", base + "/handoffs", json=version(p))
        assert not receipt["approved_for_handoff"]
        data = c.get(receipt["download_url"]).content
        assert hashlib.sha256(data).hexdigest() == receipt["sha256"]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            assert z.testzip() is None
            assert hashlib.sha256(z.read("video.mp4")).hexdigest() == next(
                x["sha256"] for x in a["artifacts"] if x["kind"] == "video"
            )
            assert not json.loads(z.read("reviews.json"))["status"]["approved_for_handoff"]
        (out / receipt["filename"]).write_bytes(data)
        save(
            "acceptance.json",
            {
                "fixture": LABEL,
                "jobs": [a["id"], b["id"]],
                "scene_equal": equal,
                "pcm_equal": True,
                "srt_equal": True,
                "cache": cache,
                "old_job_unchanged": True,
                "restore_preserves_both": True,
                "timeline_captions": len(timeline["captions"]),
                "export_sha256": receipt["sha256"],
                "customer_approved": False,
                "computer_use": False,
                "platform_writes": False,
            },
        )
        print(
            "PASS: current engine, one-shot edit, restore, timeline and pending export", flush=True
        )


if __name__ == "__main__":
    main()
