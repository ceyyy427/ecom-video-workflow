"""Explicit isolated installation fixture with original synthetic footage. No human final approval."""

import argparse
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABEL = "AUTOMATED FIXTURE INSTALL 非客户事实确认/听核/签收"


def original_footage(folder):
    from PIL import Image, ImageDraw, ImageFilter

    path = folder / "synthetic-jar.mp4"
    p = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "480x854",
            "-r",
            "24",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        for frame in range(144):
            image = Image.new("RGB", (480, 854), "#ebe7df")
            shadow = Image.new("RGBA", image.size)
            draw = ImageDraw.Draw(shadow)
            draw.ellipse((90, 583, 390, 640), fill=(40, 35, 30, 90))
            image = Image.alpha_composite(
                image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14))
            )
            draw = ImageDraw.Draw(image)
            shift = round(15 * math.sin(frame / 144 * math.tau))
            left, right = 136 + shift, 344 + shift
            draw.rounded_rectangle(
                (left, 327, right, 605), 30, fill="#fafaf5", outline="#c9c8c0", width=2
            )
            draw.ellipse((left, 572, right, 618), fill="#e7e7df", outline="#c9c8c0", width=2)
            draw.rectangle((left + 8, 356, right - 8, 589), fill="#fafaf5")
            draw.rectangle((left + 24, 365, left + 40, 577), fill="#ffffff")
            draw.rounded_rectangle((left - 5, 300, right + 5, 357), 13, fill="#c86b32")
            draw.ellipse(
                (left - 5, 280, right + 5, 328), fill="#e48b48", outline="#b95e28", width=2
            )
            draw.ellipse((left + 12, 288, right - 12, 319), fill="#ed9d5d")
            draw.text((205 + shift, 453), "DEMO", fill="#b26338", font_size=28)
            draw.text((126, 730), "SYNTHETIC INSTALL DEMO", fill="#716b63", font_size=16)
            rgb = image.convert("RGB")
            if frame == 48:
                rgb.save(folder / "synthetic-jar.jpg")
            p.stdin.write(rgb.tobytes())
        p.stdin.close()
        if p.wait(timeout=30):
            raise RuntimeError("演示素材编码失败")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--simulate-confirmations", action="store_true")
    ap.add_argument(
        "--voice-file", type=Path, help="与本轮生成script.txt对应的本机配音，不自动改稿"
    )
    ap.add_argument("--data", type=Path, help="已停止的同级空白首次配置数据目录")
    args = ap.parse_args()
    workspace = args.workspace.expanduser().absolute()
    if not args.simulate_confirmations:
        ap.error("须显式--simulate-confirmations；只用于隔离安装验收，不能替客户审批")
    if workspace.exists() or workspace.is_symlink():
        ap.error("验收工作目录必须不存在；不能覆盖既有项目")
    if workspace.resolve().is_relative_to(ROOT):
        ap.error("使用安装目录之外的新工作目录，不能在正式数据内运行")
    workspace.mkdir(mode=0o700)
    from fastapi.testclient import TestClient

    from ecom_video.analysis_worker import Worker as AnalysisWorker
    from ecom_video.api import create_app
    from ecom_video.customer_setup import customer_profile
    from ecom_video.maintenance import backup, check, digest, restore
    from ecom_video.media import probe, safe_path
    from ecom_video.worker import Worker

    customer_profile()
    os.environ["ECOM_MEDIA_AUDIT"] = "0"
    # Only local directed generation and uploaded local speech are used below.
    for name in list(os.environ):
        if name.startswith(("DOUBAO_", "ARK_", "ECOM_LLM_")):
            os.environ.pop(name)
    os.environ["ECOM_VOLC_VOICE_CONFIG"] = str(workspace / "not-configured.json")
    from ecom_video.customer_demo_speech import demo_data

    runtime = demo_data(workspace, args.data)

    def save(name, value):
        (workspace / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))

    footage = original_footage(workspace)
    print("原创合成视频已生成；不是实拍商品证据", flush=True)
    with TestClient(create_app(runtime), base_url="http://localhost") as client:
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]

        def request(method, path, **kwargs):
            response = client.request(method, "/api" + path, **kwargs)
            if not response.is_success:
                raise RuntimeError(f"{path}: {response.status_code} {response.text[:600]}")
            return response.json()

        def post(path, data):
            return request("POST", path, json=data)

        p = post(
            "/customer-projects",
            {
                "title": "安装演练 · 原创合成圆罐",
                "settings": {
                    "brief": {
                        "format": "narrated",
                        "category": "家居收纳演示",
                        "audience": "首次使用工作台的客户",
                        "tone": "克制、清楚地讲解外观",
                    },
                    "sfx": False,
                    "auto_select": False,
                    "review_context": LABEL + "；原创合成素材，不证明真实商品性能",
                },
            },
        )
        pid = p["id"]
        base, product = "/customer-projects/" + pid, "/products/" + pid

        def current():
            return request("GET", base)

        doc = "这是安装演练中的合成圆罐示例。\n罐身为白色。\n顶盖为橙色。"
        request(
            "POST",
            product + "/documents",
            data={"revision": p["product"]["revision"]},
            files={"file": ("原创示例说明.txt", doc.encode(), "text/plain")},
        )
        p = current()
        prod = post(
            product + "/facts/confirm",
            {
                "revision": p["product"]["revision"],
                "fact_ids": [f["id"] for f in p["product"]["facts"]],
                "reviewer": LABEL,
                "note": "隔离技术测试；非客户事实审批",
                "confirmed": True,
            },
        )
        prod = post(
            product + "/scripts/generate",
            {"revision": prod["revision"], "mode": "directed", "brief": p["settings"]["brief"]},
        )
        save("generated-script.json", prod["script_drafts"][-1])
        post(
            product + "/scripts/confirm",
            {
                "revision": prod["revision"],
                "draft_id": prod["current_draft_id"],
                "reviewer": LABEL,
                "note": "隔离测试，原稿保留事实引用",
                "confirmed": True,
            },
        )

        def upload(path, role):
            with path.open("rb") as source:
                return request(
                    "POST",
                    base + "/assets",
                    data={"revision": current()["revision"], "role": role},
                    files={"file": (path.name, source, "application/octet-stream")},
                )

        upload(footage, "product")
        media = current()["media"][0]
        post(base + "/assets/" + media["id"] + "/analysis", {})
        assert AnalysisWorker(runtime).once()
        analysis = current()["media"][0]["analysis"]
        save("local-vision.json", analysis)
        assert analysis["status"] == "ready", "实际本机识别未完成；不冒充模型验收成功"
        print("新安装目录已完成真实本机视觉识别", flush=True)
        p = current()
        draft = next(
            d for d in p["product"]["script_drafts"] if d["id"] == p["product"]["current_draft_id"]
        )
        text = workspace / "script.txt"
        text.write_text("\n".join(s["text"] for s in draft["payload"]))
        voice = workspace / "voice.wav"
        if args.voice_file:
            from ecom_video.media import inspect_media

            inspect_media(args.voice_file, "audio")
            shutil.copyfile(args.voice_file, voice)
        else:
            from ecom_video.customer_demo_speech import synthesize

            synthesize(text, voice)
        upload(voice, "voice")
        p = post(base + "/prepare", {"revision": current()["revision"]})
        jid = p["job"]["id"]
        asset = next(a for a in p["job"]["assets"] if a["kind"] == "audio")
        post("/jobs/" + jid + "/alignments", {"asset_id": asset["id"]})
        deadline = time.monotonic() + 240
        while (current().get("alignment") or {}).get("status") in ("queued", "running"):
            if time.monotonic() > deadline:
                raise RuntimeError("本机对齐超时；保留本次数据，不做伪匹配")
            time.sleep(0.25)
        p = current()
        save("alignment.json", p["alignment"])
        assert p["alignment"]["status"] == "needs_review", p["alignment"]
        post(
            "/jobs/" + jid + "/alignments/" + p["alignment"]["id"] + "/confirm",
            {"reviewer": LABEL, "confirmed": True},
        )
        p = current()
        rec = p["recommendations"]
        assert len(rec["options"]) == 3
        save("recommendations.json", rec)
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
        assert all(s["duration"] <= 6 for s in p["job"]["storyboard"]["shots"])
        post(
            base + "/submit",
            {
                "revision": p["revision"],
                "job_id": jid,
                "board_revision": p["job"]["storyboard_revision"],
            },
        )
        assert Worker(runtime).run_once()
        job = current()["job"]
        save("job.json", job)
        assert job["status"] == "needs_review", job["error"]
        assert not job["reviews"]
        assert job["snapshot"]["alignment"]["timing_review"]["automated_fixture"] is True
        video = next(a for a in job["artifacts"] if a["kind"] == "video")
        shutil.copyfile(safe_path(runtime, video["path"]), workspace / "output.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(workspace / "output.mp4"), "-f", "null", "-"],
            check=True,
            timeout=60,
        )
    frozen = backup(runtime, workspace / "backup")
    recovered = workspace / "restored"
    restore(workspace / "backup", recovered)
    with (
        closing(
            sqlite3.connect((runtime / "workflow.db").as_uri() + "?mode=ro", uri=True)
        ) as original,
        closing(
            sqlite3.connect((recovered / "workflow.db").as_uri() + "?mode=ro", uri=True)
        ) as copied,
    ):
        tables = [
            r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        assert all(
            original.execute(f'SELECT * FROM "{t}"').fetchall()
            == copied.execute(f'SELECT * FROM "{t}"').fetchall()
            for t in tables
        )
    assert digest(recovered / video["path"]) == video["sha256"]
    report = {
        "fixture": LABEL,
        "project_id": pid,
        "job_id": jid,
        "status": job["status"],
        "final_reviews": 0,
        "cloud_calls": 0,
        "platform_writes": 0,
        "source": "original synthetic animated footage, not real product evidence",
        "models": {"vision": analysis["result"].get("model"), "asr": "actual_local_firered"},
        "automatic_selection_claimed": False,
        "video_sha256": digest(workspace / "output.mp4"),
        "probe": probe(workspace / "output.mp4"),
        "backup": frozen,
        "restored_tables_equal": len(tables),
        "environment": check(runtime),
    }
    save("acceptance.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "job_id",
                    "status",
                    "final_reviews",
                    "cloud_calls",
                    "platform_writes",
                    "restored_tables_equal",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
