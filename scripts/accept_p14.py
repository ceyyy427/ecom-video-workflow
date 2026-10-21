"""Isolated P14 acceptance: real queues/render; fixtures or existing local VLM only."""

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
LABEL = "AUTOMATED FIXTURE P14 演示，非客户核验或真人听核"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--local-model", action="store_true")
    parser.add_argument("--narrated", action="store_true")
    parser.add_argument("--fault-matrix", action="store_true")
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if data.is_relative_to(ROOT) or data == ROOT or (data.exists() and any(data.iterdir())):
        parser.error("Use an empty acceptance data directory outside the repository")
    data.mkdir(parents=True)
    os.environ["ECOM_AGENT_ENABLED"] = "1"
    os.environ["ECOM_AGENT_EXECUTION_ENABLED"] = "1"
    original_connect = socket.socket.connect

    def guarded(sock, address):
        if args.local_model and isinstance(address, tuple) and address[:2] == ("127.0.0.1", 11434):
            return original_connect(sock, address)
        raise AssertionError(
            "P14 forbids external network; local-model only allows 127.0.0.1:11434"
        )

    def fixture_observe(images, model):
        from ecom_video.agent_guard import reserve_call

        reserve_call()
        return {
            "description": "桌面上的咖啡杯，旁边放着电脑。",
            "subjects": ["咖啡杯", "桌面", "电脑"],
            "actions": [],
            "framing": "context",
            "usable": True,
            "uncertainty": "AUTOMATED FIXTURE; not real visual evidence",
        }

    def fixture_rank(prompt, schema, **kwargs):
        from ecom_video.agent_guard import reserve_call

        reserve_call()
        return {
            "lines": [
                {
                    "line": schema["$defs"]["LineRanking"]["properties"]["line"]["enum"][0],
                    "choices": [
                        {
                            "clip_id": schema["$defs"]["Choice"]["properties"]["clip_id"]["enum"][
                                0
                            ],
                            "score": 3,
                            "reason": "fixture 匹配桌面画面",
                        }
                    ],
                }
            ]
        }

    fixture_model = {"model": "fixture-not-real-model", "digest": "fixture", "provider": "fixture"}
    with ExitStack() as stack:
        stack.enter_context(patch("socket.socket.connect", guarded))
        if args.offline:
            stack.enter_context(patch("ecom_video.vision_model.identity", lambda: fixture_model))
            stack.enter_context(patch("ecom_video.vision_model.observe", fixture_observe))
            stack.enter_context(patch("ecom_video.clip_matching.identity", lambda: fixture_model))
            stack.enter_context(patch("ecom_video.clip_matching.generate", fixture_rank))
        from fastapi.testclient import TestClient

        from ecom_video.agent_runtime import Runtime
        from ecom_video.analysis_worker import Worker as AnalysisWorker
        from ecom_video.api import create_app
        from ecom_video.media import digest, safe_path
        from ecom_video.worker import Worker as RenderWorker

        c = stack.enter_context(
            TestClient(create_app(data / "runtime"), base_url="http://localhost")
        )
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]

        def call(method, path, **kw):
            r = c.request(method, "/api" + path, **kw)
            assert r.status_code < 400, (path, r.status_code, r.text[:1200])
            return r.json()

        p = call(
            "POST",
            "/customer-projects",
            json={
                "title": "P14 独立演示 · 桌面咖啡杯",
                "settings": {
                    "auto_select": True,
                    "brief": {"format": "narrated" if args.narrated else "showcase"},
                },
            },
        )
        pid = p["id"]
        base = "/customer-projects/" + pid
        prod = "/products/" + pid
        video = data / "input.mp4"
        if args.local_model:
            shutil.copyfile(ROOT / "examples/p9-real/originals/6177761.mp4", video)
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=240x320:rate=30",
                    "-t",
                    "8",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
        with video.open("rb") as f:
            p = call(
                "POST",
                base + "/assets",
                data={"revision": p["revision"], "role": "product"},
                files={"file": ("实拍.mp4", f, "video/mp4")},
            )
        line = "桌面上的咖啡杯，旁边放着电脑。"
        if args.narrated:
            wav = data / "voice.wav"
            aiff = data / "voice.aiff"
            subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), line], check=True)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(aiff), "-ar", "24000", "-ac", "1", str(wav)],
                check=True,
            )
            with wav.open("rb") as f:
                p = call(
                    "POST",
                    base + "/assets",
                    data={"revision": p["revision"], "role": "voice"},
                    files={"file": ("演示本机旁白.wav", f, "audio/wav")},
                )
        product = call("GET", prod)
        product = call(
            "POST",
            prod + "/documents",
            data={"revision": product["revision"]},
            files={"file": ("演示可见事实.txt", line.encode(), "text/plain")},
        )
        facts = [f["id"] for f in product["facts"]]
        product = call(
            "POST",
            prod + "/facts/confirm",
            json={
                "revision": product["revision"],
                "fact_ids": facts,
                "reviewer": LABEL,
                "note": LABEL,
                "confirmed": True,
            },
        )
        product = call(
            "POST",
            prod + "/scripts",
            json={"revision": product["revision"], "scenes": [{"text": line, "fact_ids": facts}]},
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
        command = {
            "schema_version": 1,
            "request_id": "p14-accept",
            "operation": "project.produce",
            "input": {
                "project_id": pid,
                "expected_revision": p["revision"],
                "expected_product_revision": p["product"]["revision"],
                "policy": {
                    "policy_id": "local-v1",
                    "max_steps": 30,
                    "max_elapsed_s": 1800,
                    "max_model_calls": 40,
                    "max_cost_cny": "0",
                },
            },
        }
        proposal = call("POST", "/agent/runs", json=command)
        rid = proposal["run_id"]
        agent = "/agent/runs/" + rid

        def binding(e):
            return {"revision": e["revision"], "plan_hash": e["plan_hash"], "policy_id": "local-v1"}

        e = call("GET", agent + "/execution")
        e = call(
            "POST",
            agent + "/style",
            json={
                **binding(e),
                "style_id": "social",
                "direction_basis": p["direction_basis"],
                "reviewer": LABEL,
                "confirmed": True,
            },
        )
        e = call("POST", agent + "/execute", json=binding(e))
        runtime = Runtime(data / "runtime", c.app.state.store)
        analysis = AnalysisWorker(data / "runtime")
        render = RenderWorker(data / "runtime")
        began = time.monotonic()
        listening_fixture = False
        while time.monotonic() - began < 1800:
            runtime.tick()
            analysis.once()
            e = runtime.get(rid)
            if e["status"] in ("failed", "cancelled", "unknown"):
                raise AssertionError(e)
            if e["waiting_for"] == "listening":
                p = call("GET", base)
                a = p["alignment"]
                call(
                    "POST",
                    f"/jobs/{p['job']['id']}/alignments/{a['id']}/confirm",
                    json={"confirmed": True, "reviewer": LABEL},
                )
                listening_fixture = True
                call("POST", agent + "/resume", json=binding(e))
            if e["waiting_for"] == "alignment_failed":
                raise AssertionError(call("GET", base)["alignment"])
            render.run_once()
            runtime.tick()
            e = runtime.get(rid)
            if e["waiting_for"] == "film_review":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("P14 acceptance deadline reached")
        p = call("GET", base)
        job = p["job"]
        assert job["status"] == "needs_review" and e["status"] == "waiting_human"
        assert job["storyboard"]["shots"][0]["asset_id"] in {
            a["id"] for a in job["assets"] if a["kind"] == "video"
        }
        artifact = next(a for a in job["artifacts"] if a["kind"] == "video")
        output = safe_path(data / "runtime", artifact["path"])
        shutil.copyfile(output, data / "p14-sample.mp4")
        (data / "command.json").write_text(json.dumps(command, ensure_ascii=False, indent=2))
        report = {
            "phase": "P14",
            "evidence_level": "local_verified" if args.local_model else "fixture_with_real_render",
            "data": str(data),
            "project_id": pid,
            "run_id": rid,
            "job_id": job["id"],
            "status": e["status"],
            "waiting_for": e["waiting_for"],
            "video_status": job["status"],
            "video": str(data / "p14-sample.mp4"),
            "video_sha256": digest(output),
            "steps_used": e["steps_used"],
            "usage": e["usage"],
            "listening_confirmation_fixture": listening_fixture,
            "human_checks_are_automated_fixture": True,
            "source_license": "examples/p9-real/LICENSE-SOURCES.md"
            if args.local_model
            else "generated synthetic fixture",
            "analysis": p["media"][0]["analysis"]["result"],
            "board": job["storyboard"],
            "live_cloud_verified": False,
            "platform_writes": 0,
        }
        (data / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
    if args.fault_matrix:
        with (data / "fault-matrix.log").open("w") as log:
            child = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_agent_recovery.py",
                    "tests/test_agent_review.py",
                    "-q",
                    "--basetemp",
                    str(data / "faults"),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        assert child.returncode == 0, (data / "fault-matrix.log").read_text()
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("analysis", "board")},
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
