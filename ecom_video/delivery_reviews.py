"""Explicit human choices in the existing append-only event history, bound to versions."""

import json
import time

from .creative import signature
from .customer_directions import editorial_basis
from .db import Conflict


def bindings(c, p):
    from .customer import Customers

    job = p.get("job") or {}
    board = job.get("storyboard") or {}
    alignment_id = (board.get("creative") or {}).get("alignment_id")
    alignment = (
        c.execute("SELECT result,status FROM alignments WHERE id=?", (alignment_id,)).fetchone()
        if alignment_id
        else None
    )
    return {
        "direction_basis": editorial_basis(p),
        "storyboard_basis": signature(
            {
                "job_id": job.get("id"),
                "board_revision": job.get("storyboard_revision"),
                "board": board,
                "alignment": dict(alignment) if alignment else None,
                "input": Customers.fingerprint(p),
            }
        )
        if board
        else None,
    }


def review_state(c, p):
    job = p.get("job") or {}
    enabled = bool(
        p["settings"].get("delivery_version") or (job.get("storyboard") or {}).get("delivery")
    )
    result = {
        "enabled": enabled,
        "direction": None,
        "storyboard": None,
        "direction_basis": None,
        "storyboard_basis": None,
    }
    if not enabled:
        return result
    result.update(bindings(c, p))
    positions = {}
    records = c.execute(
        "SELECT id,message FROM events WHERE job_id IN (SELECT job_id FROM customer_jobs WHERE product_id=? UNION SELECT a.job_id FROM script_approvals a JOIN script_drafts d ON d.id=a.draft_id WHERE d.product_id=?) ORDER BY id DESC LIMIT 300",
        (p["id"], p["id"]),
    )
    for row in records:
        try:
            event = json.loads(row["message"])
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("kind") != "delivery_style_review":
            continue
        stage = event.get("stage")
        if (
            stage in ("direction", "storyboard")
            and result[stage] is None
            and event.get("basis") == result[stage + "_basis"]
        ):
            result[stage] = event
            positions[stage] = row["id"]
    if result["storyboard"] and (
        not result["direction"]
        or positions["direction"] > positions["storyboard"]
        or result["direction"]["style_id"] != result["storyboard"]["style_id"]
        or result["storyboard"]["style_id"]
        != (job.get("storyboard") or {}).get("creative", {}).get("style_id")
    ):
        result["storyboard"] = None
    return result


def confirm_style(service, pid, data):
    p = service.get(pid)
    if p["revision"] != data["revision"] or not data["reviewer"].strip():
        raise Conflict("项目已变化或缺少人工确认人，请重新核对")
    if p["product"]["status"] != "script_confirmed":
        raise Conflict("请先确认当前事实和文稿")
    stage, style = data["stage"], data["style_id"]
    state = p["delivery_reviews"]
    if not state["enabled"] or data["basis"] != state[stage + "_basis"]:
        raise Conflict("方向或分镜依据已变化，请刷新并重新核对")
    job = p.get("job")
    if stage == "direction":
        if style not in {o["id"] for o in p["recommendations"]["options"]}:
            raise ValueError("请选择本次推荐方向")
        approval = next(
            a
            for a in p["product"]["script_approvals"]
            if a["draft_id"] == p["product"]["current_draft_id"]
        )
        jid = job["id"] if job else approval["job_id"]
    else:
        if not job or job["status"] != "draft" or p["inputs_changed"]:
            raise Conflict("请核对当前可编辑分镜版本")
        if style != job["storyboard"]["creative"]["style_id"]:
            raise Conflict("最终风格与当前分镜不一致")
        if not job["storyboard"].get("delivery"):
            raise Conflict("新版交付分镜不能移除版本约束")
        if (job["storyboard"].get("delivery") or {}).get("identity_lock") != p["settings"].get(
            "identity_lock"
        ):
            raise Conflict("分镜款式/配色限制与项目不符")
        if not state["direction"] or state["direction"]["style_id"] != style:
            raise Conflict("请先确认相同的创意方向")
        if p["settings"]["brief"]["format"] != "showcase" and (
            not p["alignment"] or p["alignment"]["status"] != "confirmed"
        ):
            raise Conflict("请先完成本版配音听核")
        jid = job["id"]
    event = {
        "kind": "delivery_style_review",
        **data,
        "project_id": pid,
        "job_id": jid,
        "created_at": time.time(),
    }
    with service.store.transaction() as c:
        service.row(c, pid, data["revision"])
        service.products._row(c, pid, p["product"]["revision"])
        row = service.store._row(c, jid)
        if job and row["storyboard_revision"] != job["storyboard_revision"]:
            raise Conflict("分镜已更新，请重新核对")
        if bindings(c, p)[stage + "_basis"] != data["basis"]:
            raise Conflict("声音或分镜已更新，请重新核对")
        if stage == "storyboard" and review_state(c, p)["direction"] != state["direction"]:
            raise Conflict("创意方向确认已变化，请重新核对最终分镜")
        service.store._event(
            c, jid, row["status"], row["status"], json.dumps(event, ensure_ascii=False), time.time()
        )
    return service.get(pid)


def record_agent_direction(c, store, p, style, reviewer):
    if not p["settings"].get("delivery_version"):
        return
    approval = next(
        a
        for a in p["product"]["script_approvals"]
        if a["draft_id"] == p["product"]["current_draft_id"]
    )
    jid = p["job"]["id"] if p.get("job") else approval["job_id"]
    row = store._row(c, jid)
    event = {
        "kind": "delivery_style_review",
        "stage": "direction",
        "project_id": p["id"],
        "job_id": jid,
        "basis": editorial_basis(p),
        "style_id": style,
        "reviewer": reviewer,
        "confirmed": True,
        "source": "explicit human Agent style command",
    }
    store._event(
        c, jid, row["status"], row["status"], json.dumps(event, ensure_ascii=False), time.time()
    )
