"""Authorized local exports; no cookies, scraping or implicit ownership proof."""

import csv
import hashlib
import io
import re


def add_account(records, platform, name, subject):
    if platform not in ("douyin", "xiaohongshu"):
        raise ValueError("请选择抖音或小红书；广告账户仍用原复盘入口")
    if not 1 <= len(name.strip()) <= 120 or not 1 <= len(subject.strip()) <= 256:
        raise ValueError("请填写账户名称和客户声明的账户标识")
    return records.put(
        "connection",
        {
            "platform": platform,
            "name": name.strip(),
            "subject_sha256": hashlib.sha256(subject.strip().encode()).hexdigest(),
            "transport": "file",
            "ownership": "declared_not_api_verified",
            "platform_writes": False,
        },
    )


def freeze_source(records, account_id, raw, filename, declaration):
    account = records.get(account_id, "connection")
    if not re.fullmatch(r"[^/\\\x00-\x1f]{1,100}\.csv", filename, re.I) or not declaration.strip():
        raise ValueError("请提供CSV文件名及有权使用这份导出的说明")
    if not 1 <= len(raw) <= 2 * 1024**2 or len(declaration) > 1000:
        raise ValueError("报表须小于2MiB，来源说明不超过1000字")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (ValueError, UnicodeError, csv.Error):
        raise ValueError("请使用UTF-8 CSV报表") from None
    if (
        not rows
        or len(rows) > 10001
        or len(rows[0]) > 30
        or any(len(r) != len(rows[0]) for r in rows)
    ):
        raise ValueError("CSV最多10000行30列，行列数须一致")
    payload = {
        "account_ref": account_id,
        "platform": account["payload"]["platform"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "filename": filename,
        "declaration": declaration,
        "ownership": "declared_not_api_verified",
    }
    return records.freeze_bytes("source", payload, raw, ".csv")
