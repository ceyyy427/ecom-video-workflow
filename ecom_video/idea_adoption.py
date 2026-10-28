"""Adopt a frozen plan without transferring or inventing any human approvals."""

import copy
import json
import shutil
import time
import uuid
from contextlib import nullcontext

from .db import Conflict
from .idea_media import check_materials
from .idea_plans import IdeaPlans
from .idea_renderer import visual_poster, visual_spec
from .media import digest, inspect_media, safe_path
from .products import Products, encoded


def selected_plan(store, pid, *, connection=None):
    with nullcontext(connection) if connection is not None else store.connect() as c:
        row = c.execute(
            "SELECT p.id,p.basis,p.plan,a.option_id FROM idea_adoptions a JOIN idea_plans p ON p.id=a.plan_id WHERE a.product_id=?",
            (pid,),
        ).fetchone()
        if not row:
            return None
        plan = json.loads(row["plan"])
        option = next(o for o in plan["options"] if o["id"] == row["option_id"])
        return {
            "plan_id": row["id"],
            "basis": row["basis"],
            "version": plan["version"],
            "engine": plan["engine"],
            "option_id": row["option_id"],
            "option": option,
            "brief": plan["brief"],
            "claims": plan["claims"],
            "materials": [
                {k: a[k] for k in ("id", "sha256", "kind", "source_in")} for a in plan["materials"]
            ],
        }


def adopt(root, store, plan_id, basis, option_id):
    from .customer import Customers
    from .customer_api import Settings

    service = IdeaPlans(root, store)
    row = service.get(plan_id)
    if row["basis"] != basis:
        raise Conflict("方案依据已变化，请重新比较")
    option = next((o for o in row["plan"]["options"] if o["id"] == option_id), None)
    if not option:
        raise ValueError("请选择当前六个方案之一")
    with store.connect() as c:
        prior = c.execute(
            "SELECT product_id FROM idea_adoptions WHERE plan_id=? AND option_id=?",
            (plan_id, option_id),
        ).fetchone()
    if prior:
        return Customers(root, store).get(prior["product_id"])
    if option.get("feasibility") == "needs_materials":
        raise Conflict("该方向仍缺完整画面，请补素材或改稿后重新预览，再进入制作")
    if row["status"] != "ready" or len(row["previews"]) != 6:
        raise Conflict("请先完成六个真实动态预览，再选择进入制作")
    for item in row["plan"]["options"]:
        for kind in ("video", "poster"):
            service.preview(plan_id, item["id"], kind)
    check_materials(root, row["plan"]["materials"])
    pid = uuid.uuid4().hex
    directory = safe_path(root, f"customers/{pid}")
    directory.mkdir(parents=True, exist_ok=False)
    media = []
    plan = row["plan"]
    now = time.time()
    source_id = uuid.uuid4().hex
    try:
        visual_dir = directory / "media"
        visual_dir.mkdir()
        for asset in plan["materials"]:
            aid = uuid.uuid4().hex
            src = safe_path(root, asset["path"])
            target = visual_dir / (aid + src.suffix)
            shutil.copyfile(src, target)
            metadata = copy.deepcopy(asset["metadata"])
            original = (metadata.get("intake") or {}).get("original_path")
            if original:
                old = safe_path(root, original)
                if not old.is_file():
                    raise Conflict("原始素材已移除，请重新选择再制作")
                backup = visual_dir / (aid + "-original" + old.suffix)
                shutil.copyfile(old, backup)
                metadata["intake"]["original_path"] = backup.relative_to(root).as_posix()
            if metadata.get("identity"):
                metadata["identity_reference"] = metadata.pop("identity")
            metadata["idea_material_id"] = asset["id"]
            media.append(
                {
                    "id": aid,
                    "name": asset["name"],
                    "path": target.relative_to(root).as_posix(),
                    "kind": asset["kind"],
                    "sha256": digest(target),
                    "size": target.stat().st_size,
                    "metadata": metadata,
                    "source_in": asset["source_in"],
                    "note": asset.get("source_note", asset.get("note", "")),
                }
            )
        if not media:
            for scene in option["scenes"]:
                aid = uuid.uuid4().hex
                target = visual_dir / (aid + ".png")
                spec = visual_spec(plan, option, scene)
                visual_poster(target, spec)
                media.append(
                    {
                        "id": aid,
                        "name": f"{option['name']}-{scene['id']}.png",
                        "path": target.relative_to(root).as_posix(),
                        "kind": "image",
                        "sha256": digest(target),
                        "size": target.stat().st_size,
                        "metadata": {
                            **inspect_media(target, "image"),
                            "code_visual": spec,
                            "idea_scene_id": scene["id"],
                        },
                        "source_in": 0,
                        "note": "代码图示，非实拍；文字与数值来自本次输入，仍待人工确认",
                    }
                )
        source = directory / "创意方案待核对资料.txt"
        units = [{"id": c["id"], "text": c["text"], "locator": c["source"]} for c in plan["claims"]]
        source.write_text(
            "待核对创作资料；主题为创作设定，其余原文请逐条核对。\n"
            + plan["brief"]["idea"]
            + "\n\n"
            + "\n".join(f"{u['text']}\n来源：{u['locator']}" for u in units),
            encoding="utf-8",
        )
        settings = Settings(
            brief={
                "format": "narrated"
                if option.get("narrative") in {"scenario_share", "detail_explain"}
                else "showcase",
                "audience": plan["brief"]["audience"],
                "tone": plan["brief"]["tone"],
            },
            delivery_version=1,
            identity_lock=plan.get("source_context", {}).get("identity_target"),
            strict_product=bool(plan.get("source_context", {}).get("identity_target")),
            brand=option.get("brand"),
        ).model_dump()
        with store.transaction() as c:
            current = service.row(c, plan_id)
            if current["basis"] != basis or current["status"] != "ready":
                raise Conflict("预览状态已变化，请重新载入")
            prior = c.execute(
                "SELECT product_id FROM idea_adoptions WHERE plan_id=? AND option_id=?",
                (plan_id, option_id),
            ).fetchone()
            if prior:
                existing = prior["product_id"]
            else:
                existing = None
                c.execute(
                    "INSERT INTO products(id,title,status,created_at,updated_at) VALUES(?,?,'collecting',?,?)",
                    (pid, plan["subject"], now, now),
                )
                c.execute(
                    "INSERT INTO customer_projects VALUES(?,0,?,NULL,?,?)",
                    (pid, encoded(settings), now, now),
                )
                c.execute(
                    "INSERT INTO product_sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        source_id,
                        pid,
                        "document",
                        source.name,
                        None,
                        None,
                        source.relative_to(root).as_posix(),
                        digest(source),
                        encoded({"units": units, "idea_plan_basis": basis}),
                        now,
                    ),
                )
                for unit in units:
                    c.execute(
                        "INSERT INTO product_facts VALUES(?,?,?,?,?,?,?)",
                        (
                            uuid.uuid4().hex,
                            pid,
                            source_id,
                            unit["id"],
                            unit["text"],
                            unit["locator"],
                            now,
                        ),
                    )
                for a in media:
                    c.execute(
                        "INSERT INTO customer_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            a["id"],
                            pid,
                            a["name"],
                            a["path"],
                            a["kind"],
                            "product",
                            a["sha256"],
                            a["size"],
                            encoded(a["metadata"]),
                            a["source_in"],
                            a["note"],
                            now,
                        ),
                    )
                c.execute(
                    "INSERT INTO idea_adoptions VALUES(?,?,?,?)", (plan_id, option_id, pid, now)
                )
                Products(store)._event(
                    c,
                    pid,
                    "采用创意预览，新建待确认资料与制作项目；尚无人工审批",
                    "collecting",
                    None,
                    None,
                )
        if existing:
            shutil.rmtree(directory)
            pid = existing
        return Customers(root, store).get(pid)
    except BaseException:
        # Never remove a committed project if post-commit presentation fails.
        with store.connect() as c:
            committed = c.execute(
                "SELECT 1 FROM customer_projects WHERE product_id=?", (pid,)
            ).fetchone()
        if not committed:
            shutil.rmtree(directory, ignore_errors=True)
        raise


def apply_script(store, pid, basis, revision):
    selected = selected_plan(store, pid)
    if not selected or selected["basis"] != basis:
        raise Conflict("当前项目与选定创意版本不一致")
    products = Products(store)
    product = products.get(pid)
    facts = products.confirmed_facts(product)
    sources = {
        s["id"] for s in product["sources"] if s["extracted"].get("idea_plan_basis") == basis
    }
    by_unit = {f["unit_id"]: f for f in facts if f["source_id"] in sources}
    scenes = []
    for item in selected["option"]["scenes"]:
        if any(i not in by_unit for i in item["claim_ids"]):
            raise Conflict("所选方案仍引用未确认的资料，请核对勾选来源或人工编辑文稿")
        scenes.append(
            {"text": item["text"], "fact_ids": [by_unit[i]["id"] for i in item["claim_ids"]]}
        )
    return products.save_draft(
        pid,
        revision,
        scenes,
        "directed",
        model=encoded(
            {
                "creative_plan_version": selected["version"],
                "basis": basis,
                "option_id": selected["option_id"],
            }
        ),
    )


def apply_board(job, board, mode, notes, *, preserve_media=False):
    selected = (job.get("provenance") or {}).get("idea_plan")
    if not selected:
        return
    option = selected["option"]
    if board["creative"]["style_id"] != option["native_style"]:
        notes.append("已人工改选其他风格，本次按当前选择编排，原预览方案仍保留。")
        return
    lines = job["script"].splitlines()
    scenes = option["scenes"]
    if lines != [s["text"] for s in scenes]:
        if any(a["metadata"].get("code_visual") for a in job["assets"]):
            raise ValueError(
                "文稿已修改，旧图示文字不能继续沿用；请重新生成对应方案或替换图示素材，再确认分镜"
            )
        notes.append("文稿已编辑，本次按当前文稿编排，原创意计划留作参考；不强行套用旧语义映射。")
        return
    from .shotcraft import MotionPlan

    assets = job["assets"]
    for shot, scene in zip(board["shots"], scenes, strict=True):
        matched = next(
            (
                a
                for a in assets
                if a["metadata"].get("idea_scene_id") == scene["id"]
                or scene["material_id"]
                and a["metadata"].get("idea_material_id") == scene["material_id"]
            ),
            None,
        )
        if matched and not preserve_media:
            start = scene.get("source_in", matched["metadata"].get("source_in", 0))
            if (
                matched["kind"] == "video"
                and start + shot["duration"] > matched["metadata"]["duration"] + 0.001
            ):
                raise ValueError(
                    "所选方案的实拍不足以覆盖当前声音时长，请补拍、缩句或逐镜改选，不会循环填充"
                )
            shot.update(
                asset_id=matched["id"],
                source_in=start if matched["kind"] == "video" else 0,
                motion="static",
                fit="contain",
            )
        # Existing action windows survive; only presentation/recipe changes.
        motion = shot.get("motion_plan") or MotionPlan().model_dump()
        motion["prompt_card"] = None
        shot.update(
            headline=scene.get("headline", shot.get("headline", "")),
            presentation="design",
            shot_id=scene["id"],
            shot_recipe=scene["recipe"],
            transition=scene["transition"],
            motion_plan=motion,
        )
    notes.append(
        f"沿用创意预览 {selected['plan_id']} / {selected['option_id']}：同一文稿、稳定镜头ID与配方；声音时长优先，仍待逐镜和成片审核。"
    )


def validate_diagram(asset, line, provenance):
    from .idea_renderer import CodeVisual

    value = asset["metadata"]
    if isinstance(value, str):
        value = json.loads(value)
    spec = CodeVisual.model_validate(value["code_visual"])
    if spec.labels != [line]:
        raise ValueError("图示文字与当前文稿不同，请更新对应图示或重新生成方案，不能显示旧事实")
    if spec.data:
        selected = (provenance or {}).get("idea_plan")
        expected = {
            c["text"] for c in (selected or {}).get("claims", []) if c["id"].startswith("data-")
        }
        confirmed = {f["text"] for f in (provenance or {}).get("facts", [])}
        if not expected or not expected.issubset(confirmed):
            raise ValueError("数据图示含尚未确认的数值，请核对完整来源后再制作")
