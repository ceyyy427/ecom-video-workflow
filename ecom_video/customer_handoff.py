"""Bounded, immutable customer result ZIPs; exporting never grants approval."""

import hashlib
import json
import re
import shutil
import threading
import uuid
import zipfile
from pathlib import Path

from .creative import signature
from .db import Conflict
from .media import digest, safe_path

MAX_BYTES = 512 * 1024**2
LOCK = threading.Lock()
FIXTURE = re.compile(r"fixture|工程验收|模拟审批|模拟确认|非客户", re.I)


def fixture(record):
    return bool(
        record.get("automated_fixture")
        or any(
            FIXTURE.search(str(record.get(k) or "")) for k in ("reviewer", "note", "review_context")
        )
    )


def same_board(snapshot_board, current_board):
    """Compare schema values, not JSON's 0/0.0 spelling; retain every editing field."""
    from .storyboard import Board

    # Preserve exact matching of historical snapshots, including earlier schemas.
    if isinstance(snapshot_board, dict) and signature(snapshot_board) == signature(current_board):
        return True
    try:
        return signature(Board.model_validate(snapshot_board).model_dump()) == signature(
            Board.model_validate(current_board).model_dump()
        )
    except (ValueError, TypeError):
        return False


def status(project):
    job = project.get("job") or {}
    provenance = job.get("provenance") or {}
    facts, script = provenance.get("fact_review") or {}, provenance.get("script_approval") or {}
    board = job.get("storyboard") or {}
    creative = board.get("creative") or {}
    timing = ((job.get("snapshot") or {}).get("alignment") or {}).get("timing_review") or {}
    final = next(iter(reversed(job.get("reviews") or [])), {})
    product = project.get("product") or {}
    current_hash = hashlib.sha256(job["script"].encode()).hexdigest() if job.get("script") else None
    spoken = (board.get("narration") or {}).get("mode") not in ("silent", "none")
    alignment = project.get("alignment") or {}
    voice = next(
        (
            a
            for a in job.get("assets", [])
            if a["id"] == (board.get("narration") or {}).get("asset_id") and a["kind"] == "audio"
        ),
        None,
    )
    listening_ok = not spoken
    if spoken and voice and alignment.get("fingerprint"):
        from .alignment import matches_input

        try:
            listening_ok = bool(
                alignment.get("status") == "confirmed"
                and alignment.get("id") == creative.get("alignment_id")
                and alignment.get("job_id") == job.get("id")
                and alignment.get("reviewer") == timing.get("reviewer")
                and timing.get("reviewer")
                and timing.get("confirmed_at")
                and timing.get("input_fingerprint") == alignment["fingerprint"]
                and ((job.get("snapshot") or {}).get("alignment") or {}).get("audio_sha256")
                == voice["sha256"]
                and matches_input(alignment, job, voice)
            )
        except (KeyError, TypeError, ValueError, OSError):
            listening_ok = False
    videos = [a for a in job.get("artifacts", []) if a["kind"] == "video"]
    audit, snapshot = job.get("audit") or {}, job.get("snapshot") or {}
    film_bound = bool(
        len(videos) == 1
        and re.fullmatch(r"[a-f0-9]{64}", videos[0].get("sha256", ""))
        and audit.get("output_sha256") == videos[0]["sha256"]
        and snapshot
        and audit.get("snapshot_sha256") == signature(snapshot)
        and snapshot.get("script") == job.get("script")
        and same_board(snapshot.get("storyboard"), board)
    )
    checks = [
        (
            "facts",
            "事实确认",
            bool(
                facts.get("reviewer")
                and facts.get("id")
                and facts.get("id") == product.get("current_review_id")
            ),
            facts,
        ),
        (
            "script",
            "文稿确认",
            bool(
                script.get("reviewer")
                and script.get("draft_id")
                and current_hash
                and script.get("draft_id") == product.get("current_draft_id")
                and script.get("script_hash") == job.get("script_hash") == current_hash
            ),
            script,
        ),
        (
            "style",
            "风格选择",
            bool(
                creative.get("style_id")
                and not (project.get("iteration") or {}).get("style_confirm_needed")
            ),
            creative,
        ),
        (
            "listening",
            "配音听核",
            listening_ok,
            timing,
        ),
        (
            "film",
            "成片审核",
            bool(
                job.get("status") == "ready"
                and film_bound
                and final.get("decision") == "ready"
                and final.get("reviewer")
                and final.get("checklist_confirmed")
                and current_hash
                and final.get("script_hash") == job.get("script_hash") == current_hash
            ),
            final,
        ),
    ]
    if board.get("delivery"):
        delivery = (job.get("snapshot") or {}).get("delivery_reviews") or {}
        for stage, key, label in (("direction", "direction_style", "创意方向确认"), ("storyboard", "final_style", "最终分镜风格确认")):
            record = delivery.get(stage) or {}
            ok = bool(record.get("reviewer") and record.get("confirmed") and record.get("style_id") == creative.get("style_id"))
            checks.append((key, label, ok, record))
    shot_reviews = project.get("shot_reviews") or {}
    if shot_reviews.get("enabled"):
        checks.append(("shots", "逐镜审核", bool(shot_reviews.get("all_passed")), {"automated_fixture": shot_reviews.get("fixture", False)}))
    gates = [
        {
            "id": key,
            "label": label,
            "state": "fixture" if fixture(record) else "recorded" if ok else "pending",
        }
        for key, label, ok, record in checks
    ]
    is_fixture = fixture(project.get("settings") or {}) or any(
        g["state"] == "fixture" for g in gates
    )
    blockers = [
        g["label"] + ("为模拟记录" if g["state"] == "fixture" else "待完成")
        for g in gates
        if g["state"] != "recorded"
    ]
    if project.get("inputs_changed"):
        blockers.append("输入已变化，请核对并准备对应制作版本")
    if is_fixture:
        blockers.append("工程模拟记录不算客户审批")
    available = job.get("status") in ("needs_review", "ready", "rejected") and any(
        a["kind"] == "video" for a in job.get("artifacts", [])
    )
    approved = bool(available and not blockers)
    return {
        "export_available": bool(available),
        "approved_for_handoff": approved,
        "classification": "approved" if approved else "review",
        "gates": gates,
        "blockers": blockers,
        "fixture": bool(is_fixture),
        "scope": "当前文件版本的人工记录；不代表发布授权、自动合规或投放",
    }


class Handoff:
    def __init__(self, root, store):
        from .customer import Customers

        self.root, self.store = Path(root), store
        self.customers = Customers(root, store)

    def _write(self, path, payloads, files):
        records = []
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
            for name, raw in payloads.items():
                archive.writestr(name, raw)
                records.append(
                    {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                )
            for name, item in files.items():
                source = safe_path(self.root, item["path"])
                hasher, size = hashlib.sha256(), 0
                with source.open("rb") as src, archive.open(name, "w", force_zip64=True) as out:
                    while chunk := src.read(1024**2):
                        size += len(chunk)
                        if size > item["size"] or size > MAX_BYTES:
                            raise Conflict("成片文件大小已变化，请重新核对后导出")
                        hasher.update(chunk)
                        out.write(chunk)
                if size != item["size"] or hasher.hexdigest() != item["sha256"]:
                    raise Conflict("成片文件SHA不一致，请从备份恢复或重新制作")
                records.append({"path": name, "sha256": hasher.hexdigest(), "size": size})
        return records

    def create(self, pid, version):
        if not LOCK.acquire(blocking=False):
            raise Conflict("正在准备另一份交付包，请稍后重试")
        target = receipt_path = None
        try:
            p = self.customers.get(pid)
            if (
                p["revision"] != version["revision"]
                or not p["job"]
                or p["job"]["id"] != version["job_id"]
                or p["job"]["storyboard_revision"] != version["board_revision"]
            ):
                raise Conflict("项目或制作版本已变化，请刷新后导出")
            job = p["job"]
            summary = status(p)
            if not summary["export_available"]:
                raise Conflict("请先生成可审阅的成片；导出不会代替确认或听审")
            if sum(a["kind"] == "video" for a in job["artifacts"]) != 1:
                raise Conflict("主视频登记不唯一，请先核对制作版本后导出")
            provenance = job.get("provenance") or {}
            sources = [
                {k: source.get(k) for k in ("id", "file_name", "sha256")}
                for source in provenance.get("sources", [])
            ]
            media = [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "kind": a["kind"],
                    "sha256": a["sha256"],
                    "original_sha256": (a["metadata"].get("intake") or {}).get("original_sha256"),
                }
                for a in job["assets"]
            ]

            def encode(value):
                return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()

            payloads = {
                "script.txt": job["script"].encode(),
                "storyboard.json": encode(job.get("storyboard")),
                "audit-summary.json": encode(
                    {
                        key: (job.get("audit") or {}).get(key)
                        for key in (
                            "schema_version",
                            "rule_version",
                            "script_hash",
                            "status",
                            "summary",
                            "findings",
                            "coverage",
                            "manual_checks",
                            "human_review_required",
                            "output_sha256",
                        )
                    }
                ),
                "sources.json": encode(
                    {
                        "sources": sources,
                        "media": media,
                        "facts": provenance.get("facts", []),
                        "scenes": provenance.get("scenes", []),
                        "rights": "仅有来源/哈希不等于授权证明；须由客户核对实际使用范围",
                    }
                ),
                "reviews.json": encode(
                    {
                        "fact_review": provenance.get("fact_review"),
                        "script_approval": provenance.get("script_approval"),
                        "listening": ((job.get("snapshot") or {}).get("alignment") or {}).get(
                            "timing_review"
                        ),
                        "film": job.get("reviews", []),
                        "shots": p.get("shot_reviews"),
                        "status": summary,
                    }
                ),
                "README.txt": (
                    "剪序 · 当前版本成果包\n"
                    + (
                        "已完成当前版本人工记录。\n"
                        if summary["approved_for_handoff"]
                        else "待审包：不能当作客户签收或发布许可。\n"
                    )
                    + "\n".join(summary["blockers"])
                    + "\n包含成片、可用字幕/配音、文稿、分镜、来源哈希和审核记录。\n原片、Key、模型、数据库不在本包；逐镜修改请回原项目，业务迁移请另做备份。\n导出不批准、不合规认证、不自动投放。新版与旧版分别保留，已导出的ZIP请另存。\n"
                ).encode(),
            }
            filenames = {
                "video": "video.mp4",
                "video_clean": "video-clean.mp4",
                "subtitles": "subtitles.srt",
            }
            files = {filenames[a["kind"]]: a for a in job["artifacts"] if a["kind"] in filenames}
            voice = next(
                (
                    a
                    for a in job["assets"]
                    if a["id"] == (job.get("storyboard") or {}).get("narration", {}).get("asset_id")
                    and a["kind"] == "audio"
                ),
                None,
            )
            if voice:
                files["narration" + Path(voice["path"]).suffix] = voice
            total = sum(a["size"] for a in files.values()) + sum(len(v) for v in payloads.values())
            if total > MAX_BYTES or sum(len(v) for v in payloads.values()) > 16 * 1024**2:
                raise ValueError("成果包超过512MiB或说明过大，请分别下载文件")
            if shutil.disk_usage(self.root).free < 2 * total + 50 * 1024**2:
                raise ValueError("磁盘空间不足，请释放空间后再导出")
            hid = uuid.uuid4().hex
            folder = safe_path(self.root, f"customers/{pid}/handoffs")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            target, receipt_path = folder / (hid + ".zip"), folder / (hid + ".json")
            records = self._write(target, payloads, files)
            manifest = {
                "format": "customer-handoff-v1",
                "project_id": pid,
                "project_revision": p["revision"],
                "job_id": job["id"],
                "parent_job_id": job.get("parent_id"),
                "board_revision": job["storyboard_revision"],
                "script_hash": job.get("script_hash"),
                **summary,
                "files": records,
                "platform_writes": False,
            }
            with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("HANDOFF.json", encode(manifest))
            receipt = {
                **summary,
                "id": hid,
                "job_id": job["id"],
                "sha256": digest(target),
                "bytes": target.stat().st_size,
                "filename": f"剪序-{'已审' if summary['approved_for_handoff'] else '待审'}-{job['id'][:8]}.zip",
                "download_url": f"/api/customer-projects/{pid}/handoffs/{hid}/download",
            }
            with self.store.transaction() as c:
                current = self.customers.row(c, pid, version["revision"])
                latest = self.store._row(c, job["id"])
                self.customers.products._row(c, pid, p["product"]["revision"])
                if (
                    current["active_job_id"] != job["id"]
                    or latest["updated_at"] != job["updated_at"]
                    or latest["storyboard_revision"] != job["storyboard_revision"]
                ):
                    raise Conflict("制作版本或审核状态已变化，请刷新后重新导出")
                receipt_path.write_bytes(encode(receipt))
                target.chmod(0o600)
                receipt_path.chmod(0o600)
            return receipt
        except (FileNotFoundError, OSError) as exc:
            if target:
                target.unlink(missing_ok=True)
            if receipt_path:
                receipt_path.unlink(missing_ok=True)
            raise Conflict("成果文件缺失或写入失败，请检查磁盘与备份后重试") from exc
        except BaseException:
            if target:
                target.unlink(missing_ok=True)
            if receipt_path:
                receipt_path.unlink(missing_ok=True)
            raise
        finally:
            LOCK.release()

    def download(self, pid, hid):
        self.customers.get(pid)
        if not re.fullmatch(r"[a-f0-9]{32}", hid):
            raise KeyError(hid)
        record = safe_path(self.root, f"customers/{pid}/handoffs/{hid}.json")
        path = safe_path(self.root, f"customers/{pid}/handoffs/{hid}.zip")
        if not record.is_file() or not path.is_file():
            raise KeyError(hid)
        receipt = json.loads(record.read_text())
        if path.stat().st_size != receipt["bytes"] or digest(path) != receipt["sha256"]:
            raise Conflict("成果包校验失败，请重新导出；原任务未修改")
        return path, receipt["filename"]
