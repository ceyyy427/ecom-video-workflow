"""Read-only edit planning and append-only, version-bound customer review records."""

import copy
import json
import time

from .creative import signature
from .db import Conflict

RUNNING = {"queued", "validating", "rendering", "auditing"}
REASONS = {
    "checked": "已逐镜检查",
    "product_visibility": "商品不清楚",
    "action_mismatch": "动作不对应",
    "caption_timing": "字幕时机",
    "voice": "配音问题",
    "facts": "事实或限定语",
    "other": "其他",
}


def member(service, pid, jid):
    with service.store.connect() as c:
        if not c.execute(
            "SELECT 1 FROM customer_jobs WHERE product_id=? AND job_id=?", (pid, jid)
        ).fetchone():
            raise KeyError(jid)
    return service.store.get(jid)


def canonical(job):
    hashes = {a["id"]: a["sha256"] for a in job["assets"]}

    def normalized(value):
        if isinstance(value, dict):
            return {
                k: normalized(v)
                for k, v in value.items()
                if k not in ("fingerprint", "alignment_id")
                and not (k in ("caption_note", "typography") and not v)
            }
        if isinstance(value, list):
            return [normalized(v) for v in value]
        return hashes.get(value, value) if isinstance(value, str) else value

    return normalized(job.get("storyboard") or {})


def compare(service, pid, before, after):
    a, b = member(service, pid, before), member(service, pid, after)
    x, y = canonical(a), canonical(b)
    left = {s["shot_id"]: s for s in x.get("shots", [])}
    right = {s["shot_id"]: s for s in y.get("shots", [])}
    ids = list(dict.fromkeys([*left, *right]))
    rows = [
        {
            "shot_id": sid,
            "changed_fields": [
                k
                for k in sorted(set(left.get(sid, {})) | set(right.get(sid, {})))
                if left.get(sid, {}).get(k) != right.get(sid, {}).get(k)
            ],
        }
        for sid in ids
    ]
    global_fields = [
        k
        for k in sorted(set(x) | set(y))
        if k not in ("shots", "creative", "delivery") and x.get(k) != y.get(k)
    ]
    if (x.get("creative") or {}) != (y.get("creative") or {}):
        global_fields.append("creative")
    return {
        "before": before,
        "after": after,
        "shots": rows,
        "changed_shots": [r["shot_id"] for r in rows if r["changed_fields"]],
        "global_fields": global_fields,
        "script_changed": a["script"] != b["script"],
        "audio_changed": any(x.get(k) != y.get(k) for k in ("narration", "music_id", "music_db")),
        "videos": {
            j["id"]: "/api/jobs/" + j["id"] + "/artifacts/video"
            if any(f["kind"] == "video" for f in j["artifacts"])
            else None
            for j in (a, b)
        },
        "scope": "比较已保存的制作参数及素材SHA；不是成片像素/声音一致性的自动保证。",
    }


def impact(service, pid, data):
    p = service.current(
        pid, data["revision"], data["job_id"], data["board_revision"], allow_media_change=True
    )
    job = p["job"]
    board = copy.deepcopy(job.get("storyboard"))
    if not board or job["status"] in RUNNING:
        raise Conflict("请等待生成结束并准备可编辑分镜")
    shot = next((s for s in board["shots"] if s["shot_id"] == data["shot_id"]), None)
    if shot is None:
        raise KeyError(data["shot_id"])
    changes = copy.deepcopy(data["changes"])
    if not changes:
        raise ValueError("请选择修改项")
    draft = job["status"] == "draft"
    assets = copy.deepcopy(job["assets"])
    from .shot_changes import apply_changes

    if draft:
        if "media_id" in changes:
            raise ValueError("草稿请选当前任务的素材")
        shot.update(changes)
        if changes.get("asset_id"):
            a = next(
                (a for a in assets if a["id"] == changes["asset_id"] and a["kind"] != "audio"), None
            )
            if not a:
                raise ValueError("画面不属于当前任务")
            shot["role"] = a["metadata"].get("customer_role") or "product"
            shot["evidence_note"] = a["metadata"].get("evidence_note") or ""
    else:
        from .customer_api import ShotChanges

        changes = ShotChanges.model_validate(changes).model_dump(
            exclude_unset=True, exclude_none=True
        )
        if "typography" in data["changes"] and data["changes"]["typography"] is None:
            changes["typography"] = None
        media_id = changes.pop("media_id", None)
        selected = None
        selected_id = None
        if media_id:
            selected = next(
                (a for a in p["media"] if a["id"] == media_id and a["kind"] != "audio"), None
            )
            if not selected:
                raise ValueError("替换画面不属于当前项目")
            existing = next(
                (a for a in assets if a["metadata"].get("library_id") == media_id), None
            )
            if not existing:
                if (
                    sum(a["kind"] != "audio" for a in assets) >= 30
                    or sum(a["size"] for a in assets) + selected["size"] > 500 * 1024**2
                ):
                    raise ValueError("修订素材超过项目限制，请新建制作版本")
                existing = copy.deepcopy(selected)
                assets.append(existing)
            selected_id = existing["id"]
        apply_changes(shot, changes, selected, selected_id)
        from .creative import rebase_fingerprint

        board["creative"]["fingerprint"] = rebase_fingerprint(
            job, {**job, "assets": assets}, board["creative"]
        )
    from .production import validate_production
    from .shotcraft import effective_transitions
    from .storyboard import validate_board

    valid = validate_board({**job, "assets": assets}, board)
    validate_production(valid, assets)

    def boundaries(b):
        return effective_transitions(
            [{**s, "frames": round(s["duration"] * 30)} for s in b["shots"]]
        )

    adjacent = boundaries(valid) != boundaries(job["storyboard"])
    affected = [data["shot_id"]]
    if adjacent:
        i = next(i for i, s in enumerate(board["shots"]) if s["shot_id"] == data["shot_id"])
        affected = [s["shot_id"] for s in board["shots"][max(0, i - 1) : i + 2]]
    return {
        "basis": signature({"version": data, "input": service.fingerprint(p)}),
        "affected_shots": affected,
        "audio_changed": False,
        "subtitles_changed": False,
        "can_apply_single_shot": not adjacent,
        "can_apply": draft or not adjacent,
        "requires": ["最终分镜风格确认", "逐镜检查", "成片审核"],
        "warnings": ["动作保护会影响相邻转场，请在新草稿整体调整"] if adjacent else [],
        "message": (
            "草稿边界会影响相邻镜头，请核对转场和动作完整性。"
            if adjacent
            else "仅调整画面；保持镜长、整稿配音和字幕。"
        )
        + "仍需确认最终分镜与重新审片。缓存是否复用以渲染清单为准。",
    }


def review_state(c, job):
    if not job:
        return {"enabled": False, "shots": [], "all_passed": False, "fixture": False, "basis": None}
    board = job.get("storyboard") or {}
    if isinstance(board, str):
        board = json.loads(board)
    video = c.execute(
        "SELECT sha256 FROM artifacts WHERE job_id=? AND kind='video'", (job["id"],)
    ).fetchall()
    basis = signature(
        {
            "job": job["id"],
            "revision": job["storyboard_revision"],
            "board": board,
            "video": [r["sha256"] for r in video],
        }
    )
    records = []
    # Records never inherit to another job or to a different film hash.
    for r in c.execute("SELECT message FROM events WHERE job_id=? ORDER BY id DESC", (job["id"],)):
        try:
            item = json.loads(r["message"])
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and item.get("kind") == "shot_review":
            records.append(item)
    current = {}
    for r in records:
        if r.get("basis") == basis:
            current.setdefault(r["shot_id"], r)
    shots = [
        {"shot_id": s["shot_id"], "review": current.get(s["shot_id"])}
        for s in board.get("shots", [])
    ]
    from .customer_handoff import fixture

    return {
        "enabled": bool(records),
        "basis": basis,
        "shots": shots,
        "all_passed": bool(shots)
        and all(r["review"] and r["review"]["decision"] == "pass" for r in shots),
        "fixture": any(fixture(r["review"]) for r in shots if r["review"]),
        "history": records,
    }


def review(service, pid, data):
    p = service.current(pid, data["revision"], data["job_id"], data["board_revision"])
    job = p["job"]
    if job["status"] != "needs_review":
        raise Conflict("只能记录待审成片；已签收版本请新建修改版")
    if not data["reviewer"].strip() or not data["note"].strip():
        raise ValueError("请填写实际审核人和意见")
    with service.store.transaction() as c:
        service.row(c, pid, data["revision"])
        service.products._row(c, pid, p["product"]["revision"])
        row = dict(service.store._row(c, job["id"]))
        state = review_state(c, row)
        if (
            row["status"] != "needs_review"
            or row["storyboard_revision"] != data["board_revision"]
            or state["basis"] != data["basis"]
        ):
            raise Conflict("成片或审核依据已变化，请重新看听")
        if data["shot_id"] not in {s["shot_id"] for s in state["shots"]}:
            raise ValueError("镜头不属于当前版本")
        if not c.execute(
            "SELECT 1 FROM artifacts WHERE job_id=? AND kind='video'", (job["id"],)
        ).fetchone():
            raise Conflict("尚无可审核成片")
        event = {"kind": "shot_review", **data, "created_at": time.time()}
        service.store._event(
            c,
            job["id"],
            row["status"],
            row["status"],
            json.dumps(event, ensure_ascii=False),
            event["created_at"],
        )
        return review_state(c, row)


def restore(service, pid, data):
    p = service.current(pid, data["revision"], data["job_id"], data["board_revision"])
    target = member(service, pid, data["target_job_id"])
    if not data["reviewer"].strip():
        raise ValueError("请填写操作人")
    with service.store.transaction() as c:
        service.row(c, pid, data["revision"])
        service.products._row(c, pid, p["product"]["revision"])
        current = service.store._row(c, data["job_id"])
        row = service.store._row(c, target["id"])
        version = c.execute(
            "SELECT * FROM customer_jobs WHERE job_id=? AND product_id=?", (target["id"], pid)
        ).fetchone()
        if (
            current["status"] in RUNNING
            or row["status"] in RUNNING
            or current["storyboard_revision"] != data["board_revision"]
        ):
            raise Conflict("制作版本正在运行或已变化")
        if version["input_fingerprint"] != service.fingerprint(p) or version[
            "basis_fingerprint"
        ] != service.basis(p):
            raise Conflict("当前资料、文稿或声音与历史版不同；旧版可查看，请另建制作版本")
        event = {
            "kind": "active_version_restored",
            **data,
            "created_at": time.time(),
            "note": "仅恢复活动制作版本；原稿、各版审批与文件保持",
        }
        service.store._event(
            c,
            target["id"],
            row["status"],
            row["status"],
            json.dumps(event, ensure_ascii=False),
            event["created_at"],
        )
        service.touch(c, pid, target["id"])
    return service.get(pid)


def learning_links(service, pid):
    p = service.get(pid)
    with service.store.connect() as c:
        snapshots = [
            dict(r)
            for r in c.execute(
                """SELECT l.review_id,l.material_id,l.job_id,r.start_date,r.end_date,r.snapshot_hash,r.actor FROM review_feature_links l JOIN review_snapshots r ON r.id=l.review_id JOIN customer_jobs v ON v.job_id=l.job_id WHERE v.product_id=? ORDER BY r.created_at DESC LIMIT 100""",
                (pid,),
            )
        ]
        experiments = [
            dict(r)
            for r in c.execute(
                """SELECT e.id,e.review_id,e.parent_job_id,e.result_job_id,e.status FROM experiments e JOIN customer_jobs v ON v.job_id=e.parent_job_id WHERE v.product_id=? ORDER BY e.created_at DESC LIMIT 100""",
                (pid,),
            )
        ]
    for item in snapshots:
        item["url"] = (
            "/experiments?review=" + item["review_id"] + "&material=" + item["material_id"]
        )
        item["current_version"] = item["job_id"] == (p["job"] or {}).get("id")
    return {
        "snapshots": snapshots,
        "experiments": experiments,
        "causal_inference": False,
        "note": "仅描述性复盘。客户自行投放后导入报表；没有数据则保留未知。假设必须人工选择。",
    }
