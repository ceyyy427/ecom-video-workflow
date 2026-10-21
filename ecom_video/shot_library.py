"""Read-only pinned shot research, distinct from the bounded executable renderer."""

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

INDEX = Path(__file__).parent / "data/shotcraft-library.json"
INDEX_SHA256 = "11ba934a2b701843ef113a65d4a1a0c16974b9473ed0a60b62aceb7131c76755"
ADAPTED = {
    "scan-bracket-sweep": ["detail-bracket-soft-v1", "detail-bracket-bold-v1"],
    "row-embed": ["fact-row-soft-v1", "fact-row-bold-v1"],
    "transition-hidden-cut": [],
    "spotlight-hero-card": ["hero-soft-v1", "hero-bold-v1"],
    "word-relay-filmstrip": ["relay-soft-v1", "relay-bold-v1"],
    "brand-frame-snap": ["brand-soft-v1", "brand-bold-v1"],
    "text-as-mask": ["type-mask-clean-v1", "type-mask-bold-v1"],
    "panel-grid-moves": ["comic-panels-soft-v1", "comic-panels-bold-v1"],
    "crash-zoom-punch": ["tech-punch-v1", "sport-punch-v1", "daily-punch-v1"],
    "blur-slide": [],
    "marker-underline-title": [],
    "scanline-annotate-focus": [],
    "product-card-progressive-assemble": [],
    "bottom-push-stack-wipe": [],
    "line-carry-transition": [],
}
CATEGORIES = (
    "opening|typography|ui-entrance|camera|data|interaction|transition|rhythm|effects|outro"
)


@lru_cache(maxsize=1)
def _load():
    raw = INDEX.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INDEX_SHA256:
        raise RuntimeError("镜头参考库完整性校验失败，请恢复匹配版本，不执行该文件")
    return json.loads(raw)


def _record(card, *, full=False):
    result = copy.deepcopy(
        card
        if full
        else {k: v for k, v in card.items() if k not in ("body", "implementation_sources")}
    )
    result.update(
        status="adapted" if card["id"] in ADAPTED else "reference_only",
        executable_prompt_ids=ADAPTED.get(card["id"], []),
        license=_load()["license"],
        commit=_load()["commit"],
        library_sha256=INDEX_SHA256,
    )
    result["adaptation_note"] = (
        "项目有限适配；仍需核对素材与人工听审"
        if result["status"] == "adapted"
        else "仅参考，未接成渲染配方；选择或检索不会执行"
    )
    result["evidence_boundary"] = (
        "镜头方法不构成商品事实；前后对比、数字、拆解结构需另有真实素材与依据"
    )
    return result


def detail(card_id):
    for card in _load()["cards"]:
        if card["id"] == card_id:
            return _record(card, full=True)
    raise KeyError(card_id)


def _terms(query):
    query = query.lower().strip()
    english = re.findall(r"[a-z][a-z0-9-]{1,}", query)
    chinese = [
        s[i : i + 2] for s in re.findall(r"[\u4e00-\u9fff]+", query) for i in range(len(s) - 1)
    ]
    chinese += [s for s in re.findall(r"[\u4e00-\u9fff]+", query) if len(s) == 1]
    return sorted(set(english + chinese))[:160]


def inventory(query="", category="", status="", limit=124):
    data = _load()
    terms = _terms(query)
    ranked = []
    for card in data["cards"]:
        row = _record(card)
        if category and card["category"] != category or status and row["status"] != status:
            continue
        primary = (card["id"] + " " + card["summary"] + " " + card["use"]).lower()
        secondary = (card["intention"] + " " + card["body"]).lower()
        hits = [t for t in terms if t in primary or t in secondary]
        score = sum(6 if t in primary else 1 for t in hits)
        if query.strip() and not score:
            continue
        row.update(score=score, matched_terms=hits)
        ranked.append(row)
    ranked.sort(key=lambda c: (-c["score"], c["id"]))
    return {
        "stats": {"cards": 124, "styles": 150, "samples": 150},
        "categories": data["categories"],
        "commit": data["commit"],
        "license": data["license"],
        "library_sha256": INDEX_SHA256,
        "total": len(ranked),
        "items": ranked[:limit],
        "coverage": "全量正文/代码索引；150样例为来源链接，未逐条人工观看或自动移植",
    }


def suggest(job, brief, style):
    query = " ".join(
        (job["title"], brief["category"], brief["audience"], brief["tone"], job["script"][:240])
    )
    preferred = {
        "premium": ("opening", "typography"),
        "lifestyle": ("camera", "rhythm"),
        "demo": ("effects", "ui-entrance"),
    }.get(style, ("camera", "opening"))
    rows = inventory(query, limit=124)["items"]
    # Product-specific words may be absent in a UI-focused upstream library; name
    # that fallback instead of pretending the source recognized the customer's SKU.
    fallback = not rows
    if fallback:
        rows = inventory(limit=124)["items"]
    rows.sort(key=lambda c: (-(c["score"] + (12 if c["category"] in preferred else 0)), c["id"]))
    result = rows[:3]
    for row in result:
        row["matching_basis"] = (
            "无词命中，按镜头类别提供待确认参考"
            if fallback
            else "本机词组检索 + 风格家族类别偏好；非画面识别或效果预测"
        )
    return result


def router():
    api = APIRouter(prefix="/api/prompt-library")

    @api.get("")
    def listing(
        q: str = Query(default="", max_length=240),
        category: str = Query(default="", pattern="^(" + CATEGORIES + "|)$"),
        status: Literal["", "adapted", "reference_only"] = "",
        limit: int = Query(default=40, ge=1, le=124),
    ):
        try:
            return inventory(q, category, status, limit)
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(503, "镜头参考库未就绪或校验失败，请核对安装包") from None

    @api.get("/{card_id}")
    def card(card_id: str):
        try:
            return detail(card_id)
        except KeyError:
            raise HTTPException(404, "参考卡不存在") from None
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(503, "镜头参考库未就绪或校验失败") from None

    return api
