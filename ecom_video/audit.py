"""Versioned text preflight. Absence of matches is never compliance clearance."""

import hashlib
import json
import unicodedata
from pathlib import Path


def audit_script(script):
    rules = json.loads((Path(__file__).parent / "rules.json").read_text(encoding="utf-8"))
    findings = []
    offset = 0
    for line_no, line in enumerate(script.splitlines(), 1):
        normalized = unicodedata.normalize("NFKC", line)
        for rule in rules["rules"]:
            for term in rule["terms"]:
                start = normalized.find(unicodedata.normalize("NFKC", term))
                if start >= 0:
                    findings.append(
                        {
                            "rule_id": rule["id"],
                            "severity": rule["severity"],
                            "term": term,
                            "line": line_no,
                            "normalized_column": start + 1,
                            "original_line": line,
                            "reason": rule["reason"],
                            "suggestion": rule["suggestion"],
                        }
                    )
        offset += len(line) + 1
    return {
        "schema_version": 1,
        "rule_version": rules["version"],
        "script_hash": hashlib.sha256(script.encode()).hexdigest(),
        "status": "blocked" if any(f["severity"] == "block" for f in findings) else "needs_review",
        "summary": "规则预检不能证明合规；成片必须人工复核。",
        "findings": findings,
        "coverage": {
            "script_rules": True,
            "visual": False,
            "ocr": False,
            "audio_asr": False,
            "rights": False,
            "product_evidence": False,
        },
        "manual_checks": [
            "卖点、价格、效果和促销信息真实且有依据",
            "画面及配音没有误导性内容",
            "商品、音乐、人物和素材有使用授权",
            "字幕、口播、画面与时间轴一致",
            "核对目标平台的最新规则与类目资质",
        ],
        "changes_applied": False,
    }
