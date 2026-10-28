"""Privacy-minimized comment candidates. No external instructions are executed."""

import csv
import hashlib
import io
import re

from .records import encoded

RULES = (
    ("product_questions", "商品问题", r"多大|尺寸|什么|吗|怎么|\?|？|口袋|尺码"),
    ("usage_pain", "使用困难", r"不好用|麻烦|不合适|太小|太大|不舒服"),
    ("trust_objection", "信任与证据疑问", r"真假|骗人|证据|测试|靠谱吗|广告"),
    ("praise", "正面反馈", r"喜欢|好看|不错|满意"),
)


def redact(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已移除]", text)
    text = re.sub(
        r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)|\b0\d{2,3}[- ]?\d{7,8}\b", "[电话已移除]", text
    )
    text = re.sub(
        r"(?:微信|wechat|weixin|vx)\s*[:：号]?\s*[a-zA-Z0-9_-]{5,}",
        "[联系标识已移除]",
        text,
        flags=re.I,
    )
    return "".join(c for c in text if ord(c) >= 32)[:2000]


def import_comments(records, account_id, raw, declaration):
    account = records.get(account_id, "connection")
    if not 1 <= len(raw) <= 2 * 1024**2 or not 1 <= len(declaration.strip()) <= 1000:
        raise ValueError("请提供小于2MiB的UTF-8评论CSV及处理授权说明")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not {"content_id", "text"} <= set(reader.fieldnames or []):
            raise ValueError()
        rows = []
        for i, row in enumerate(reader):
            text = row["text"]
            content = row["content_id"]
            if (
                not isinstance(text, str)
                or len(text) > 10000
                or not content
                or len(content) > 256
                or i >= 10000
            ):
                raise ValueError()
            # Do not retain author/nickname/avatars, raw IDs or unredacted source bytes.
            rows.append({"row_ref": f"row-{i + 2}", "content_ref": content, "text": redact(text)})
        if not rows:
            raise ValueError()
    except (ValueError, UnicodeError, KeyError, csv.Error):
        raise ValueError("评论CSV须含content_id和text，最多10000行；个人标识默认不保留") from None
    payload = {
        "schema_version": "Comments.v1",
        "account_ref": account_id,
        "platform": account["payload"]["platform"],
        "original_source_sha256": hashlib.sha256(raw).hexdigest(),
        "declaration": declaration,
        "rows": rows,
        "raw_personal_data_retained": False,
        "privacy_policy": "drop author fields; mask common phone/email/contact strings; human privacy check still required",
    }
    sanitized = encoded(payload).encode()
    return records.freeze_bytes("comments", payload, sanitized, ".json")


def analyze_comments(records, oid):
    source = records.get(oid, "comments")
    groups = {
        k: {"id": k, "name": label, "count": 0, "evidence_refs": [], "examples": []}
        for k, label, _ in RULES
    }
    groups["unknown"] = {
        "id": "unknown",
        "name": "其他／待判断",
        "count": 0,
        "evidence_refs": [],
        "examples": [],
    }
    for row in source["payload"]["rows"]:
        key = next((k for k, _, pattern in RULES if re.search(pattern, row["text"])), "unknown")
        group = groups[key]
        group["count"] += 1
        group["evidence_refs"].append(
            {"comments_ref": oid, "row_ref": row["row_ref"], "content_ref": row["content_ref"]}
        )
        if len(group["examples"]) < 3:
            group["examples"].append(row["text"])
    return records.put(
        "comment_insights",
        {
            "schema_version": "CommentInsights.v1",
            "comments_ref": oid,
            "account_ref": source["payload"]["account_ref"],
            "method": "local_rules_candidate_only",
            "groups": list(groups.values()),
            "promote_to_product_fact": False,
            "note": "规则候选不等于语义模型结论；先人工校分类，样本不代表全体用户，不自动回复或发送云端",
        },
        files=source["files"],
    )
