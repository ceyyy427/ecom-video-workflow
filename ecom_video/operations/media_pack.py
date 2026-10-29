"""Local handoff files and declared publication ID mappings. Never platform writes."""

import contextlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

from ..creative_features import extract
from ..db import Conflict
from ..media import digest, safe_path


def _handoff_review(records, job):
    """Use the original workbench predicate, for this exact active version only."""
    from ..creative import signature
    from ..customer import Customers
    from ..customer_handoff import status

    with records.store.connect() as c:
        owner = c.execute(
            "SELECT product_id FROM customer_jobs WHERE job_id=?", (job["id"],)
        ).fetchone()
    project = None
    if owner:
        # Legacy/incomplete context never grants approval.
        with contextlib.suppress(KeyError, ValueError):
            project = Customers(records.root, records.store).get(owner[0])
    if project and project.get("job") and project["job"]["id"] == job["id"]:
        review = status(project)
    else:
        review = status({"job": job})
        review.update(approved_for_handoff=False, classification="review")
        review["blockers"].append("缺少对应活动版本的完整客户审核上下文，请回工作台核对或恢复")
    context = (
        {
            "project_id": project["id"],
            "revision": project["revision"],
            "product_revision": project["product"]["revision"],
            "active_job_id": (project.get("job") or {}).get("id"),
        }
        if project
        else None
    )
    return review, signature({"job": job, "context": context, "review": review})


def job_binding(records, jid):
    if not re.fullmatch("[a-f0-9]{32}", jid):
        raise ValueError("成片ID无效")
    job = records.store.get(jid)
    if job["status"] not in ("ready", "needs_review", "rejected"):
        raise ValueError("请先完成渲染；待审片仅可导出带待审说明的交接包")
    video = next((a for a in job["artifacts"] if a["kind"] == "video"), None)
    if not video:
        raise ValueError("成片缺失")
    for a in job["artifacts"]:
        file = safe_path(records.root, a["path"])
        if not file.is_file() or digest(file) != a["sha256"]:
            raise ValueError("成片或证据已变化，请从备份恢复或重做，不重新绑定")
    with records.store.connect() as c:
        raw = dict(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
    feature = extract(raw, video["sha256"])
    from ..delivery_revision import canonical

    feature["production_manifest"] = {
        "version": 1,
        "board": canonical(job),
        "script": job["script"],
        "scope": "submitted production parameters; not pixel/audio equivalence or causal evidence",
    }
    review, review_basis = _handoff_review(records, job)
    return job, {
        "job_id": jid,
        "video_sha256": video["sha256"],
        "input_snapshot_hash": feature["input_snapshot_hash"],
        "features": feature,
        "review_status": "approved_for_manual_handoff"
        if review["approved_for_handoff"]
        else "pending",
        "handoff_review": review,
        "handoff_basis": review_basis,
        "can_publish": False,
        "platform_writes": 0,
    }


def publication_pack(records, jid, platform, title, text):
    if (
        platform not in ("douyin", "xiaohongshu")
        or not 1 <= len(title.strip()) <= 100
        or len(text) > 3000
    ):
        raise ValueError("请选择平台、填写标题及不超过3000字的待核对文案")
    job, binding = job_binding(records, jid)
    payload = {
        **binding,
        "platform": platform,
        "title": title.strip(),
        "text": text,
        "copy_review": "pending",
        "publishing": "customer_manually_operates_platform",
    }
    entries = {"video": "video.mp4", "subtitles": "subtitles.srt", "cover": "cover.png"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        total = 0
        for a in job["artifacts"]:
            if a["kind"] not in entries:
                continue
            path = safe_path(records.root, a["path"])
            total += path.stat().st_size
            if total > 250 * 1024**2:
                raise ValueError("交接文件超过250MiB，请在原工作台单独导出")
            info = zipfile.ZipInfo(entries[a["kind"]], date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        archive.writestr(
            zipfile.ZipInfo("handoff.json"), json.dumps(payload, ensure_ascii=False, indent=2)
        )
        archive.writestr(
            zipfile.ZipInfo("操作说明.txt"),
            "本包不执行发布或投放。待审片先回工作台完成逐镜与整片审核；发布文案在平台再核对。\n"
            "由客户登录抖音/小红书上传视频，检查封面、字幕、音乐和素材权限。\n"
            "发布后将作品ID登记到运营工作台；平台导出自然内容报表后导入，广告数据用原投放复盘入口。\n",
        )

    def guard(_connection):
        # Records.put holds the existing SQLite write transaction here. Other writes
        # cannot change facts/reviews/active version between this check and registration.
        _, current = _handoff_review(records, records.store.get(jid))
        if current != binding["handoff_basis"]:
            raise Conflict("打包期间审核或版本依据已变化，请刷新后重试；未登记交接包")

    return records.freeze_bytes(
        "publication_pack", payload, buffer.getvalue(), ".zip", on_create=guard
    )


def register_content(records, pack_id, account_id, content_id, reviewer, confirmed):
    if confirmed is not True or not reviewer.strip() or len(reviewer) > 120:
        raise ValueError("请人工确认本账户作品ID与成片版本的对应关系")
    if (
        not isinstance(content_id, str)
        or not 1 <= len(content_id) <= 256
        or any(ord(c) < 33 for c in content_id)
    ):
        raise ValueError("作品ID须为不含空白的原始字符串")
    pack = records.get(pack_id, "publication_pack")["payload"]
    account = records.get(account_id, "connection")["payload"]
    if pack["platform"] != account["platform"]:
        raise ValueError("账户和交接包平台不符")
    job_binding(records, pack["job_id"])
    payload = {
        k: pack[k]
        for k in ("job_id", "video_sha256", "input_snapshot_hash", "features", "platform")
    }
    payload.update(
        pack_ref=pack_id,
        account_ref=account_id,
        content_ref=content_id,
        reviewer=reviewer,
        confirmed=True,
        ownership="declared_mapping",
        platform_writes=0,
    )
    for prior in records.matches(
        "publication_registration",
        {"platform": pack["platform"], "account_ref": account_id, "content_ref": content_id},
    ):
        p = prior["payload"]
        if (p["platform"], p["account_ref"], p["content_ref"]) == (
            pack["platform"],
            account_id,
            content_id,
        ):
            if p["video_sha256"] != pack["video_sha256"] or p["job_id"] != pack["job_id"]:
                raise ValueError("该作品ID已关联其他成片版本，请核对，不能覆盖旧绑定")
            return prior

    def check(c):
        prior = c.execute(
            "SELECT payload FROM operation_objects WHERE kind='publication_registration' AND json_extract(payload,'$.account_ref')=? AND json_extract(payload,'$.content_ref')=?",
            (account_id, content_id),
        ).fetchone()
        if prior and any(
            json.loads(prior[0])[k] != payload[k] for k in ("job_id", "video_sha256", "platform")
        ):
            raise ValueError("该作品ID已登记到其他成片；未覆盖绑定")

    return records.put("publication_registration", payload, on_create=check)


def image_pack(records, strategy_id, asset_id):
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    from ..customer import Customers
    from ..media import font_path, run_checked
    from .research import strategy_state

    state = strategy_state(records, strategy_id)
    if not state["current"]:
        raise ValueError(state["reason"])
    strategy = state["record"]["payload"]
    project = Customers(records.root, records.store).get(strategy["product_id"])
    chosen = next(
        (a for a in project["media"] if a["id"] == asset_id and a["kind"] != "audio"), None
    )
    if asset_id and not chosen:
        raise ValueError("封面素材必须属于当前商品，不能混用其他商品图片")
    target = project["settings"].get("identity_lock")
    if chosen and target and chosen["metadata"].get("identity"):
        identity = chosen["metadata"]["identity"]
        if any(identity.get(k) != target.get(k) for k in ("sku", "color")):
            raise ValueError("封面素材与当前单色/款式约束不一致")
    canvas = Image.new("RGB", (1080, 1440), "#f5f2eb")
    draw = ImageDraw.Draw(canvas)
    at = None
    if chosen:
        source = safe_path(records.root, chosen["path"])
        if not source.is_file() or digest(source) != chosen["sha256"]:
            raise ValueError("封面源素材已变化，请恢复或重新上传")
        with tempfile.TemporaryDirectory(prefix="ecom-cover-") as temp:
            if chosen["kind"] == "video":
                ranges = chosen["metadata"].get("verified_visible_ranges") or []
                at = ranges[0]["start"] if ranges else chosen["source_in"]
                frame = Path(temp) / "frame.png"
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-ss",
                        str(at),
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        str(frame),
                    ]
                )
                source = frame
            with Image.open(source) as original:
                photo = ImageOps.contain(
                    ImageOps.exif_transpose(original).convert("RGB"), (1000, 940)
                )
                canvas.paste(photo, ((1080 - photo.width) // 2, (960 - photo.height) // 2))
    else:
        draw.rounded_rectangle((100, 140, 980, 840), radius=40, outline="#8f897d", width=3)
        draw.line((170, 300, 890, 700), fill="#a6a094", width=3)
        draw.line((170, 700, 890, 300), fill="#a6a094", width=3)
    font = str(font_path())

    def text(value, top, size, max_lines):
        # Keep complete model/numerical conditions; shrink, never silently truncate.
        while size >= 24:
            f = ImageFont.truetype(font, size)
            lines, line = [], ""
            for char in value:
                if f.getlength(line + char) > 920 and line:
                    lines.append(line)
                    line = char
                else:
                    line += char
            if line:
                lines.append(line)
            if len(lines) <= max_lines:
                draw.multiline_text((80, top), "\n".join(lines), font=f, fill="#252c29", spacing=12)
                return
            size -= 2
        raise ValueError("完整文案超过封面布局，请人工选择更短且不删条件的事实原文")

    text(strategy["positioning"]["subject"], 1000, 62, 2)
    core = strategy["positioning"]["core_selling_point"]
    text(core["text"] if core else "商品资料待补齐", 1170, 42, 3)
    text("素材与文案待核对" if chosen else "代码图示 · 非商品照片", 1380, 28, 1)
    raw = io.BytesIO()
    canvas.save(raw, format="PNG")
    payload = {
        "schema_version": "ImagePackDraft.v1",
        "strategy_ref": strategy_id,
        "strategy_basis": state["record"]["basis"],
        "product_id": strategy["product_id"],
        "source_asset_id": asset_id,
        "source_sha256": chosen["sha256"] if chosen else None,
        "source_frame_at": at,
        "display_kind": "provided_asset_with_literal_text"
        if chosen
        else "schematic_not_product_photo",
        "review_status": "pending",
        "copy_fact_refs": [core["id"]] if core else [],
        "engine_basis": digest(Path(__file__)),
        "font_sha256": digest(Path(font)),
        "notes": [
            "保持提供画面比例，不伪造外观或内部结构",
            "若素材识别未知，封面主体仍须人工核对；使用权由客户确认",
        ],
    }
    return records.freeze_bytes("image_pack", payload, raw.getvalue(), ".png")


def content_matrix(records, plan_id):
    from ..idea_plans import IdeaPlans

    plan = IdeaPlans(records.root, records.store).get(plan_id)
    if plan["plan"]["version"] != "domestic-creative-v1":
        raise ValueError("请选择国内六方向方案")
    p = plan["plan"]
    return records.put(
        "content_matrix",
        {
            "schema_version": "ContentMatrixDraft.v1",
            "plan_ref": plan_id,
            "plan_basis": plan["basis"],
            "rows": [
                {
                    "option_id": o["id"],
                    "title": o["name"],
                    "platform": p["suite_brief"]["platform"],
                    "narrative": o["narrative"],
                    "script": o["script"],
                    "feasibility": o["feasibility"],
                    "gaps": o.get("gaps", []),
                    "status": "draft_not_scheduled",
                }
                for o in p["options"]
            ],
            "scheduling": False,
            "publishing": False,
        },
    )
