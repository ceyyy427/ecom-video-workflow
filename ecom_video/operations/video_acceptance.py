"""Replay explicitly marked engineering media through the unchanged production renderer.

This does not create customer approvals. Runtime gate tests are a separate acceptance leg.
"""

import copy
import json
import re
import shutil
import time
from pathlib import Path


def validate_video_cases(cases):
    from ..creative import CATALOG
    from ..media import digest

    if not 2 <= len(cases) <= 8 or len({c.get("category") for c in cases}) < 2:
        raise ValueError("需要两个品类的隔离工程样例")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("样例ID不可重复")
    for c in cases:
        path = Path(c["source_job"])
        root = Path(c["source_root"])
        if (
            not re.fullmatch(r"[a-z0-9_-]{1,60}", c["id"])
            or not c.get("usage_scope")
            or c["style_id"] not in {s["id"] for s in CATALOG}
        ):
            raise ValueError("样例范围或风格不合法")
        if (
            not root.is_absolute()
            or not root.is_dir()
            or root.is_symlink()
            or not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 16 * 1024**2
            or digest(path) != c["source_job_sha256"]
        ):
            raise ValueError("源工程与声明不符")


def copy_sources(snapshot, source, root):
    from ..media import digest, safe_path

    refs = {a["path"]: a["sha256"] for a in snapshot["assets"]}
    refs.update(
        {s["path"]: s["sha256"] for s in (snapshot.get("provenance") or {}).get("sources", [])}
    )
    for a in snapshot["assets"]:
        meta = a["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        original = meta.get("intake") or {}
        if original.get("original_path"):
            refs[original["original_path"]] = original["original_sha256"]
    if len(refs) > 128:
        raise ValueError("源文件过多")
    for relative, sha in refs.items():
        src = safe_path(source, relative)
        target = safe_path(root, relative)
        if not src.is_file() or src.is_symlink() or digest(src) != sha:
            raise ValueError("原始文件指纹不符")
        if target.exists():
            if digest(target) != sha:
                raise ValueError("隔离副本冲突")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        if digest(target) != sha:
            raise ValueError("复制不完整")


def measured_audio(path):
    import subprocess

    return subprocess.check_output(
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
        text=True,
        timeout=60,
    ).strip()


def queue_snapshot(store, snapshot, label):
    from ..products import encoded

    job = store.create_job(label, snapshot["script"])
    with store.transaction() as c:
        c.execute(
            "UPDATE jobs SET snapshot=?,storyboard=?,status='queued' WHERE id=?",
            (encoded(snapshot), encoded(snapshot["storyboard"]), job["id"]),
        )
    return job["id"]


def run_video(work, bundle, data, mode):
    from ..creative import CATALOG, recommend
    from ..db import Store
    from ..maintenance import verify
    from ..media import digest, inspect_media, probe, safe_path
    from ..worker import Worker
    from .acceptance import contact_sheet

    validate_video_cases(data["cases"])
    verified = verify(bundle)
    if mode != "engineering":
        raise ValueError("本脚本只重放工程样例；客户确认须在工作台实际完成")
    work.mkdir(mode=0o700)
    (work / ".domestic-video-acceptance").write_text(
        "AUTOMATED FIXTURE D2, never customer approvals\n"
    )
    root = work / "runtime"
    store = Store(root / "workflow.db")
    results = []
    for case in data["cases"]:
        started = time.monotonic()
        original = json.loads(Path(case["source_job"]).read_text())
        snap = copy.deepcopy(original["snapshot"])
        if isinstance(snap, str):
            snap = json.loads(snap)
        if not 20 <= sum(s["duration"] for s in snap["storyboard"]["shots"]) <= 30:
            raise ValueError("样例应为20–30秒")
        copy_sources(snap, Path(case["source_root"]), root)
        board = snap["storyboard"]
        style = next(s for s in CATALOG if s["id"] == case["style_id"])
        board["creative"]["style_id"] = style["id"]
        board["style"] = style["family"]
        board["creative"]["brand"].update(
            name=case.get("product_name", ""),
            paper=style["colors"][0],
            ink=style["colors"][1],
            accent=style["colors"][2],
        )
        for shot in board["shots"]:
            shot["presentation"] = "client"
            # The action/cut/timing/word evidence is replayed intact; only non-action styling varies.
            if not any(c.get("complete_action") for c in shot.get("source_cuts", [])):
                shot["shot_recipe"] = {
                    "kinetic": "media-punch-in",
                    "cinema": "product-hero-stage",
                    "evidence": "product-detail-bracket",
                }.get(style["id"], shot.get("shot_recipe", "none"))
        snap.setdefault("provenance", {})["engineering_replay"] = {
            "label": "AUTOMATED FIXTURE D2",
            "source_job_sha256": case["source_job_sha256"],
            "customer_signoff": False,
        }
        for a in snap["assets"]:
            meta = a["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            a["metadata"] = {**meta, **inspect_media(safe_path(root, a["path"]), a["kind"])}
        board["creative"]["brief"]["tone"] = {
            "cinema": "电影 克制 留白 质感 自然分享",
            "kinetic": "生活 轻快 年轻 节奏",
            "evidence": "细节 参数 实证 清楚 理性",
        }.get(style["id"], board["creative"]["brief"]["tone"])
        rec = recommend(snap, board["creative"]["brief"])
        if style["id"] not in {o["id"] for o in rec["options"]}:
            raise ValueError("当前输入不支持所选工程风格，须重新规划")
        board["creative"]["fingerprint"] = rec["fingerprint"]
        jid = queue_snapshot(store, snap, "AUTOMATED FIXTURE D2 " + case["id"])
        print("D2 render " + case["id"], flush=True)
        Worker(root).run_once()
        parent = store.get(jid)
        if parent["status"] != "needs_review":
            raise ValueError(parent["error"] or "render failed")
        video = safe_path(
            root, next(a["path"] for a in parent["artifacts"] if a["kind"] == "video")
        )
        duration = float(probe(video)["format"]["duration"])
        frames = contact_sheet(
            video, video.parent, tuple(duration * x for x in (0.03, 0.2, 0.4, 0.6, 0.8, 0.97))
        )
        item = {
            "case": case["id"],
            "category": case["category"],
            "job_id": jid,
            "video": str(video.relative_to(work)),
            "sha256": digest(video),
            "duration_s": float(probe(video)["format"]["duration"]),
            "seconds": round(time.monotonic() - started, 2),
            "status": "engineering_needs_review",
            "customer_approval_inherited": False,
            "source_job_sha256": case["source_job_sha256"],
            "styling_only_replay": True,
            "usage_scope": case["usage_scope"],
            **frames,
        }
        if not results:
            retake = copy.deepcopy(snap)
            shot = retake["storyboard"]["shots"][0]
            phrase = next(
                (
                    p
                    for p in re.split("[，。！？]", snap["script"].splitlines()[0])
                    if p and len(p) <= 8
                ),
                "",
            )
            if not phrase:
                raise ValueError("工程单镜对比须有完整短语")
            shot.update(headline=phrase, typography={"mode": "contrast", "keyword": phrase})
            child_id = queue_snapshot(store, retake, "AUTOMATED FIXTURE D2 local edit")
            Worker(root).run_once()
            child = store.get(child_id)
            if child["status"] != "needs_review":
                raise ValueError(child["error"] or "retake failed")
            child_video = safe_path(
                root, next(a["path"] for a in child["artifacts"] if a["kind"] == "video")
            )
            n = len(board["shots"])
            equal = [
                digest(video.parent / f"scene-{i:03d}.mp4")
                == digest(child_video.parent / f"scene-{i:03d}.mp4")
                for i in range(n)
            ]
            if equal != [False, *([True] * (n - 1))] or measured_audio(video) != measured_audio(
                child_video
            ):
                raise ValueError("单镜修改影响了无关镜头或声音")
            old_srt = next(a for a in parent["artifacts"] if a["kind"] == "subtitles")
            new_srt = next(a for a in child["artifacts"] if a["kind"] == "subtitles")
            if old_srt["sha256"] != new_srt["sha256"]:
                raise ValueError("画面修改改变了字幕")
            item["single_shot"] = {
                "job_id": child_id,
                "unchanged_other_scenes": n - 1,
                "pcm_unchanged": True,
                "srt_unchanged": True,
                "old_video_unchanged": digest(video) == item["sha256"],
            }
        results.append(item)
        (work / "progress.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        )
    with store.connect() as c:
        if c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]:
            raise ValueError("工程回放不可新增成片审批")
    report = {
        "phase": "D2",
        "status": "engineering_replay_passed_manual_pending",
        "cases": results,
        "customer_signoff": False,
        "cloud_calls": 0,
        "model_calls": 0,
        "platform_writes": 0,
        "voice_policy": "replay_existing_audio; no new paid synthesis",
        "runtime_bridge": "tested separately; this leg verifies actual renderer and cache with frozen sample evidence",
        "backup_verified": verified,
    }
    (work / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
