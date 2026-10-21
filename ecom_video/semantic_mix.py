"""Bounded per-sentence presentation; facts are frozen quotations, not model claims."""

import copy
import re
from collections import Counter

VERSION = "semantic-mix-v1"
ACTION = re.compile(
    "倒入|倒水|倒出|开盖|打开|旋开|合上|折叠|转动|戴上|佩戴|拿起|放下|放回|倒一杯|提起|切片|切下|切开|挤出|剥开|放入|放进|滴入|取出|收起|靠拢|戴到|戴在|合拢"
)
DETAIL = re.compile("细节|纹理|果皮|切面|瓶口|杯口|耳罩|头梁|接口|结构|边缘")
SCENE = re.compile("场景|回到|换到|通勤|厨房|办公室|桌边|家里")
SALE = re.compile("优惠|折扣|到手价|限时|仅售|促销|下单|选购|购买|包邮")
DATA = re.compile(
    r"\d|[一二三四五六七八九十百千万零〇两]+(?:帧|毫升|克|秒|元|升)|百分之|销量|曝光|点击率|增长|数据|参数|规格|每秒"
)


def quotation(job, index):
    lines = job["script"].splitlines()
    provenance = job.get("provenance") or {}
    rows = provenance.get("scenes") or []
    if index >= len(rows) or rows[index].get("text") != lines[index]:
        return []
    ids = rows[index].get("fact_ids") or []
    facts = {f["id"]: f for f in provenance.get("facts", []) if "id" in f}
    return [i for i in ids if i in facts and facts[i]["text"] == lines[index]]


def strategy(job, index, asset):
    line = job["script"].splitlines()[index]
    quoted = quotation(job, index)
    image_phrase = bool(re.search("商品图|照片|图片|截图", line)) and not re.search(
        r"\d|每秒|参数|规格|尺寸|容量", line
    )
    # Only a literal single still-frame count is not a product measurement.
    # Image wording must never exempt another claim elsewhere in the sentence.
    measurement_text = re.sub(r"一帧(?=商品图|照片|图片|截图)", "", line)
    sensitive = bool(SALE.search(line) or DATA.search(measurement_text))
    kind = (
        "action"
        if ACTION.search(line)
        else "sales"
        if SALE.search(line)
        else "image"
        if image_phrase
        else "data"
        if DATA.search(line)
        else "scene"
        if SCENE.search(line)
        else "detail"
        if DETAIL.search(line)
        else "text"
        if re.search("说明|文字|文案|提醒|注意|文本", line)
        else "image"
        if asset.get("kind") == "image"
        else "video"
    )
    status = (
        "needs_evidence"
        if sensitive and not quoted
        else "needs_short_quote"
        if sensitive and len(line) > 48
        else "needs_image"
        if kind == "image" and asset.get("kind") != "image"
        else "conditional"
    )
    descriptions = {
        "action": "原速连续实拍，关闭叠加动效；配音不是实际动作证据",
        "data": "只展示当前来源完整原文与静态数值，不补造趋势/增长/统计口径",
        "sales": "完整保留价格、期限、适用条件等原文，人工复核有效性，不制造促销结论",
        "detail": "已核对焦点的细节括号，非检测或测量；真实画面持续播放",
        "scene": "媒体层前景交接，字幕和人声保持稳定；不声称合成了新场景",
        "image": "高清商品图有界运镜，不能替代实拍动作",
        "text": "完整短句信息接力，不截掉限定；完整字幕独立保留",
        "video": "沿用本方向主卡，实拍持续原速播放",
    }
    return {
        "version": VERSION,
        "kind": kind,
        "status": status,
        "quoted_fact_ids": quoted,
        "requires_quotation": sensitive,
        "explanation": descriptions[kind],
        "missing": ["需要当前句完整引用已确认事实，缺少时仅保留原稿字幕，不启用数据/销售强调卡"]
        if status == "needs_evidence"
        else ["原文超过48字，请人工拆成保留完整条件的短句并重新确认；不自动截断"]
        if status == "needs_short_quote"
        else ["本句要求商品图，请选择对应授权图片；不将视频候选视为已满足图片要求"]
        if status == "needs_image"
        else [],
    }


def apply_mix(rows, lines, durations, assets, direction, job):
    from .prompt_catalog import CARDS, card_record, usable_media

    result = copy.deepcopy(rows)
    counts = Counter()
    transitions = 0
    primary = direction["cards"][0]
    for i, row in enumerate(result):
        spec = strategy(job, i, assets[i])
        row.update(shot_recipe="none", transition="cut")
        row["motion_plan"]["prompt_card"] = None
        row["reason"] += "；" + spec["kind"] + "：" + spec["explanation"]
        if spec["requires_quotation"]:
            row["clear_headline"] = True
        if (
            i == len(lines) - 1
            or spec["kind"] == "action"
            or row["motion_plan"].get("intent") == "action"
        ):
            continue
        if spec["status"] != "conditional":
            row["reason"] += "；" + "；".join(spec["missing"])
            continue
        key = (
            primary["id"]
            if i == 0
            else "detail-bracket-soft-v1"
            if spec["kind"] == "detail"
            else "fact-row-soft-v1"
            if spec["kind"] in ("data", "sales")
            else "relay-soft-v1"
            if spec["kind"] == "text"
            else primary["id"]
        )
        card = card_record(key)
        if not usable_media(assets[i]) or durations[i] < 2.8:
            row["reason"] += "；清晰度/时长不足，保留实拍与字幕"
            continue
        limit = min(2, row["motion_plan"]["repeat_limit"])
        if counts[card["recipe"]] >= limit:
            # A single shot should never force neighbouring cards to re-plan.
            row["reason"] += "；达到重复上限，留看商品"
            continue
        counts[card["recipe"]] += 1
        row.update(shot_recipe=card["recipe"])
        row["motion_plan"]["prompt_card"] = key
        row["reason"] += ("；开场使用选定方向主卡" if i == 0 else "") + "；Prompt：" + card["name"]
        if (
            spec["kind"] == "scene"
            and i > 0
            and transitions < 1
            and durations[i - 1] >= 2.8
            and not ACTION.search(lines[i - 1])
            and rows[i - 1]["motion_plan"].get("intent") != "action"
        ):
            row["transition"] = "media-pass"
            transitions += 1
        assert key in CARDS
    return result


def guard_decision(job, index, decision):
    """Repeat evidence checks for every emphasized data/sales recipe at render."""
    result = copy.deepcopy(decision)
    spec = strategy(job, index, {"kind": "video"})
    if spec["kind"] == "action" and result.get("protect_action", True):
        result.update(recipe="none", guard_outcome="action_full_frame")
    if spec["requires_quotation"] or result.get("recipe") == "product-fact-row":
        line = job["script"].splitlines()[index]
        ids = quotation(job, index)
        result["suppress_headline"] = True
        if not ids or len(line) > 48:
            result.update(
                recipe="none",
                guard_outcome="missing_complete_quotation" if not ids else "quotation_too_long",
            )
        elif result.get("recipe") == "product-fact-row":
            result["quote"] = {"text": line, "fact_ids": ids, "label": "引用原文"}
        elif result.get("recipe") != "none":
            result.update(recipe="none", guard_outcome="whole_quote_card_required")
    return result
