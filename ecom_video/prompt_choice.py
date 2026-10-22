"""Read-only local prompt adaptation; chosen recipes enter the existing edit draft."""

from .db import Conflict
from .prompt_catalog import CARDS, card_record, usable_media
from .shot_library import detail


def adaptation(service, pid, card_id, shot_id=None):
    card = detail(card_id)
    p = service.get(pid)
    job = p.get("job") or {}
    board = job.get("storyboard") or {}
    shots = board.get("shots") or []
    selected = (
        next((s for s in shots if s["shot_id"] == shot_id), None)
        if shot_id
        else next(iter(shots), None)
    )
    if shot_id and selected is None:
        raise Conflict("当前分镜已变化，请返回工作台重新选择这一镜")
    index = shots.index(selected) if selected else None
    text = job["script"].splitlines()[index] if selected else ""
    choices = []
    for key in CARDS:
        row = card_record(key)
        source = row.get("source_card_id") or row["source"]["url"].rsplit("/", 1)[-1].removesuffix(
            ".md"
        )
        if source == card_id:
            choices.append(
                {k: row[k] for k in ("id", "name", "recipe", "prompt", "requirements", "digest")}
            )
    assets = {a["id"]: a for a in job.get("assets", [])}
    ids = (
        [cut["asset_id"] for cut in selected.get("source_cuts", [])]
        if selected and selected.get("source_cuts")
        else [selected["asset_id"]]
        if selected
        else []
    )
    blockers = []
    if not selected:
        blockers.append("先确认事实、文稿和方向，并在商品制作中准备分镜")
    if p.get("inputs_changed") and not p.get("visual_revision_allowed"):
        blockers.append("商品或文稿已变化，请先重新准备分镜")
    if not choices:
        blockers.append("此卡仅供参考，尚无本机可执行变体")
    if selected and (not ids or not all(usable_media(assets.get(a, {})) for a in ids)):
        blockers.append("本镜需有使用权的同款高清素材，短边至少720像素")
    if job.get("status") in ("queued", "validating", "rendering", "auditing"):
        blockers.append("当前正在制作，结束后再编辑")
    brief = p["settings"]["brief"]
    method = choices[0]["prompt"] if choices else card["intention"]
    adapted = (
        f"商品：{p['product']['title']}。人群：{brief['audience'] or '尚未填写'}。"
        f"气质：{brief['tone'] or '尚未填写'}。\n"
        f"本镜原稿：{text or '分镜尚未准备，暂不生成商品讲解'}\n"
        f"画面方法：{method}\n"
        f"仅适配这句已确认内容，沿用同款/配色、焦点和完整动作区间。"
        f"不从参考卡添加商品事实；数字和对比须有现有依据。"
    )
    return {
        "project_id": pid,
        "title": p["product"]["title"],
        "revision": p["revision"],
        "job_id": job.get("id"),
        "board_revision": job.get("storyboard_revision"),
        "shot_id": selected["shot_id"] if selected else None,
        "text": text,
        "shots": [
            {"id": s["shot_id"], "text": job["script"].splitlines()[i]} for i, s in enumerate(shots)
        ],
        "card_id": card_id,
        "choices": choices,
        "adapted_prompt": adapted,
        "ready": not blockers,
        "blockers": blockers,
        "source_url": card["source_url"],
        "scope": "本机规则适配；尚未保存或执行。回工作台核对修改影响后保存，人工确认仍保留。",
    }
