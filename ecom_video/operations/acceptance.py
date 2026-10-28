"""Real silent previews; isolated data only, no synthesized human confirmations."""

import copy
import html
import json
import time
from pathlib import Path

from .api import ContentRequest


def validate_cases(cases):
    if not 2 <= len(cases) <= 4 or len({c.get("category") for c in cases}) < 2:
        raise ValueError("至少两个不同品类，最多四组")
    for case in cases:
        data = ContentRequest.model_validate(case["request"])
        if (
            not case.get("id")
            or not case.get("source_refs")
            or not case["asset_paths"]
            or len(case["asset_paths"]) > 8
        ):
            raise ValueError("须提供样例标识、素材、许可和来源")
        if (
            data.brief.project_id
            or data.brief.content_brief is None
            or data.brief.content_brief.materials
        ):
            raise ValueError("隔离样例只能导入本机清单中的素材，不继承项目或审批")


def contact_sheet(video, directory):
    from PIL import Image, ImageOps

    from ..media import digest, run_checked

    frames = []
    for i, at in enumerate((0.4, 1.8, 2.8, 3.7, 5.1, 6.6)):
        target = directory / f"frame-{i}.png"
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(at),
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(target),
            ]
        )
        frames.append(target)
    if len({digest(p) for p in frames}) < 4:
        raise ValueError("预览缺少可观察的动态变化")
    sheet = Image.new("RGB", (600, 360), "#eee8dd")
    for i, p in enumerate(frames):
        with Image.open(p) as img:
            sheet.paste(ImageOps.contain(img, (100, 355)), (i * 100, 0))
    sheet.save(directory / "contact.jpg")
    return {"sampled_frames": len(frames), "distinct_frames": len({digest(p) for p in frames})}


def run_content(work, bundle, data, mode):
    from fastapi.testclient import TestClient

    from scripts.accept_domestic_suite import fingerprints

    from ..api import create_app
    from ..db import Store
    from ..idea_media import upload
    from ..idea_plans import IdeaPlans
    from ..maintenance import verify
    from ..media import digest, probe, safe_path
    from ..worker import Worker
    from .resources import load_resources

    validate_cases(data["cases"])
    verified = verify(bundle)
    before = fingerprints(bundle / "workflow.db")
    work.mkdir(mode=0o700)
    (work / ".domestic-content-acceptance").write_text("isolated D1; no customer approvals\n")
    root = work / "runtime"
    store = Store(root / "workflow.db")
    plans = IdeaPlans(root, store)
    rows = []
    started = time.monotonic()
    with TestClient(create_app(root), base_url="http://localhost") as client:
        client.headers["X-Workflow-Token"] = client.get("/api/session").json()["token"]
        for case in data["cases"]:
            request = copy.deepcopy(case["request"])
            refs = []
            for file, sha in zip(case["asset_paths"], case["asset_sha256"], strict=True):
                path = Path(file)
                if digest(path) != sha:
                    raise ValueError("source changed")
                with path.open("rb") as stream:
                    ref = upload(root, store, stream, path.name, case["usage_scope"])
                if digest(path) != sha:
                    raise ValueError("source changed during intake")
                refs.append({"origin": "upload", "id": ref["id"]})
            request["brief"]["content_brief"]["materials"] = refs
            response = client.post("/api/operations/plans", json=request)
            if response.status_code != 201:
                raise ValueError(response.text[:500])
            row = response.json()
            if client.post("/api/operations/plans", json=request).json()["id"] != row["id"]:
                raise ValueError("duplicate plan")
            client.post(
                f"/api/idea-plans/{row['id']}/previews", json={"basis": row["basis"]}
            ).raise_for_status()
            tick = time.monotonic()
            print(f"D1 {case['id']}: rendering six real silent previews", flush=True)
            Worker(root).run_once()
            row = plans.get(row["id"])
            if row["status"] != "ready" or row["repair_needed"]:
                raise ValueError(row["error"] or "preview failed")
            option_reports = []
            for option in row["plan"]["options"]:
                video = plans.preview(row["id"], option["id"], "video")
                video = safe_path(root, video["path"]) if isinstance(video, dict) else video
                measured = probe(video)
                if abs(float(measured["format"]["duration"]) - 7) > 0.05 or any(
                    s["codec_type"] == "audio" for s in measured["streams"]
                ):
                    raise ValueError("not a seven-second silent preview")
                frames = contact_sheet(video, video.parent)
                option_reports.append(
                    {
                        "id": option["id"],
                        "narrative": option["narrative"],
                        "script": option["script"],
                        "video": str(video.relative_to(work)),
                        "sha256": digest(video),
                        "feasibility": option["feasibility"],
                        **frames,
                    }
                )
            candidate = next(
                (o for o in row["plan"]["options"] if o["feasibility"] != "needs_materials"), None
            )
            adopted = None
            if candidate:
                result = client.post(
                    f"/api/idea-plans/{row['id']}/adopt",
                    json={"basis": row["basis"], "option_id": candidate["id"]},
                )
                result.raise_for_status()
                project = result.json()
                if (
                    project["product"]["current_review_id"]
                    or project["product"]["script_approvals"]
                    or project["job"]
                ):
                    raise ValueError("adoption manufactured approval")
                adopted = project["id"]
            if (
                len({o["script"] for o in option_reports}) != 6
                or len({o["narrative"] for o in option_reports}) != 3
            ):
                raise ValueError("insufficient narrative diversity")
            rows.append(
                {
                    "case": case["id"],
                    "category": case["category"],
                    "source_refs": case["source_refs"],
                    "usage_scope": case["usage_scope"],
                    "plan_id": row["id"],
                    "basis": row["basis"],
                    "seconds": round(time.monotonic() - tick, 2),
                    "project_id": adopted,
                    "options": option_reports,
                    "manual_review": "pending",
                    "planning_backend": "bounded_rules",
                    "source_state": row["plan"]["source_context"]["source_state"],
                }
            )
            print(f"D1 {case['id']}: six previews ready; approvals remain empty", flush=True)
        old = client.post(
            "/api/idea-plans", json={"idea": "D1 工程旧协议兼容，不是客户审批"}
        ).json()
        if old["plan"]["version"] != "creative-plan-v1":
            raise ValueError("old protocol changed")
    with store.connect() as c:
        gates = {
            r[0]: c.execute('SELECT COUNT(*) FROM "' + r[0] + '"').fetchone()[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%review%' OR name LIKE '%approval%')"
            )
        }
        counts = {
            t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("jobs", "qianchuan_tasks", "agent_executions")
        }
    if (
        any(gates.values())
        or any(counts.values())
        or fingerprints(bundle / "workflow.db") != before
    ):
        raise ValueError("approval or original data changed")
    resources = load_resources()
    report = {
        "phase": "D1",
        "stage": "content",
        "status": "engineering_passed_manual_pending",
        "mode": mode,
        "cases": rows,
        "preview_count": len(rows) * 6,
        "total_seconds": round(time.monotonic() - started, 2),
        "approvals_added": 0,
        "approval_tables": gates,
        "original_backup_unchanged": True,
        "old_v1_compatible": True,
        "model_calls": 0,
        "cloud_calls": 0,
        "platform_writes": 0,
        "computer_use": False,
        "customer_signoff": False,
        "fork_commit": resources.fork_commit,
        "backup_verified": verified,
    }
    (work / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    cards = []
    for case in rows:
        cards.append("<h2>" + html.escape(case["case"]) + " · 待人工选择</h2>")
        for o in case["options"]:
            cards.append(
                "<article><h3>"
                + html.escape(o["id"])
                + '</h3><video controls preload="none" src="'
                + html.escape(o["video"], quote=True)
                + '"></video><p>'
                + html.escape(o["script"])
                + "</p></article>"
            )
    (work / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>D1 工程预览·未审批</title><style>body{max-width:1100px;margin:32px auto;font-family:system-ui;background:#f5f2eb}article{display:inline-block;vertical-align:top;width:30%;padding:1%;white-space:pre-line}video{width:100%;max-height:400px}p{line-height:1.7}</style><h1>D1 国内内容方案</h1><p>七秒静音预览；不是已听核或已审核成片。</p>'
        + "".join(cards)
    )
    return report
