"""Local handoff files and declared publication ID mappings. Never platform writes."""

import io
import json
import re
import zipfile

from ..creative_features import extract
from ..media import digest, safe_path


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
    approved = job["status"] == "ready" and any(
        r["decision"] == "ready"
        and r["checklist_confirmed"]
        and not re.search(r"fixture|测试|工程", r["reviewer"] + r["note"], re.I)
        for r in job["reviews"]
    )
    return job, {
        "job_id": jid,
        "video_sha256": video["sha256"],
        "input_snapshot_hash": feature["input_snapshot_hash"],
        "features": feature,
        "review_status": "approved_for_manual_handoff" if approved else "pending",
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
    return records.freeze_bytes("publication_pack", payload, buffer.getvalue(), ".zip")


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
