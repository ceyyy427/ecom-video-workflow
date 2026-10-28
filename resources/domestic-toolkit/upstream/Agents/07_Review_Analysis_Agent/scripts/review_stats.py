#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_stats.py — 07 Review Analysis Agent 的确定性算术层。

分工边界：**分类交给模型，计数交给脚本。**
  模型的活：把每条评论归到八类差评/好评卖点（语义判断）
  脚本的活：聚合、占比、可修复率、合计校验、卖点排序（确定性算术）

输入 1：评论 CSV（必填 rating 列；差评行建议有 category 列；可选 has_image 列）
输入 2（可选）：卖点 CSV（列：卖点,频次,强度[强/中/弱]）→ 频次 × 权重排序
输出：好评/中评/差评分布、差评八类归因计数与占比、可修复率（含合计校验）、
      卖点综合分排行、未归因/未分类清单。

零第三方依赖，Python 3.9+。

用法：
  python review_stats.py --file 评论.csv --fixable "误解型,参数不符合预期,配件缺失,使用困难"
  python review_stats.py --file 评论.csv --points 卖点.csv --format json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

WEIGHT = {"强": 3, "中": 2, "弱": 1}

RATING_COLS = ["rating", "评分", "星级", "avaliacao", "estrelas", "stars"]
CATEGORY_COLS = ["category", "归因", "分类", "差评归因", "categoria"]
IMAGE_COLS = ["has_image", "带图", "有图", "com_imagem", "com_foto", "image"]
POINT_COLS = ["卖点", "selling_point", "point"]
FREQ_COLS = ["频次", "次数", "frequency", "count"]
STRENGTH_COLS = ["强度", "情感强度", "strength", "weight"]


def _out(msg: str) -> None:
    print(msg, flush=True)


def _pick(row_cols: list[str], candidates: list[str], label: str,
          required: bool) -> str | None:
    for c in candidates:
        if c in row_cols:
            return c
    if required:
        sys.exit(f"[INPUT_MISSING] 找不到{label}列。可用列：{', '.join(row_cols)}"
                 f"（识别名：{', '.join(candidates)}）")
    return None


def _num(v, default=0.0):
    if v is None:
        return default
    s = str(v).strip().replace("%", "").replace(" ", "")
    if s in ("", "-", "—", "暂无", "N/A", "nan"):
        return default
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        s = parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) != 3 \
            else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return default


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "1.0", "true", "yes", "y", "是", "有", "sim")


# ---------------------------------------------------------------- 主计算

def analyze_reviews(path: str, fixable: set[str]) -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"[INPUT_MISSING] 找不到评论文件：{path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"[INPUT_MISSING] {path} 没有数据行。")
    cols = list(rows[0].keys())

    rc = _pick(cols, RATING_COLS, "评分", required=True)
    cc = _pick(cols, CATEGORY_COLS, "归因", required=False)
    ic = _pick(cols, IMAGE_COLS, "带图", required=False)

    total = len(rows)
    good = mid = bad = imgs = 0
    unrate = 0
    attr: dict[str, int] = {}
    unattributed: list[str] = []

    for i, r in enumerate(rows, 2):
        val = _num(r.get(rc), default=None)
        if val is None or val < 1 or val > 5:
            unrate += 1
            continue
        if val >= 4:
            good += 1
        elif val == 3:
            mid += 1
        else:
            bad += 1
            cat = (r.get(cc) or "").strip() if cc else ""
            if cat:
                attr[cat] = attr.get(cat, 0) + 1
            else:
                unattributed.append(f"第 {i} 行")
        if ic and _truthy(r.get(ic)):
            imgs += 1

    rated = good + mid + bad
    attr_total = sum(attr.values())
    mismatch = attr_total - bad  # 应为 0
    fixable_count = sum(v for k, v in attr.items() if k in fixable)
    unknown_cats = sorted(set(attr) - fixable - set())  # 全部类目

    return {
        "total": total, "unrated": unrate,
        "good": good, "mid": mid, "bad": bad,
        "good_rate": round(good / rated, 4) if rated else 0,
        "mid_rate": round(mid / rated, 4) if rated else 0,
        "bad_rate": round(bad / rated, 4) if rated else 0,
        "image_count": imgs,
        "image_rate": round(imgs / total, 4) if total else 0,
        "attribution": dict(sorted(attr.items(), key=lambda kv: -kv[1])),
        "attribution_total": attr_total,
        "attribution_mismatch": mismatch,
        "unattributed": unattributed,
        "fixable_set": sorted(fixable),
        "fixable_count": fixable_count,
        "fixable_rate": round(fixable_count / bad, 4) if bad else 0,
        "all_categories": unknown_cats,
    }


def analyze_points(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        sys.exit(f"[INPUT_MISSING] 找不到卖点文件：{path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    cols = list(rows[0].keys())
    pc = _pick(cols, POINT_COLS, "卖点", required=True)
    fc = _pick(cols, FREQ_COLS, "频次", required=True)
    sc = _pick(cols, STRENGTH_COLS, "强度", required=False)

    out = []
    for r in rows:
        name = (r.get(pc) or "").strip()
        if not name:
            continue
        freq = int(_num(r.get(fc)))
        s_raw = (r.get(sc) or "中").strip() if sc else "中"
        w = WEIGHT.get(s_raw)
        if w is None:
            sys.exit(f"[INPUT_MISSING] 强度值无法识别：{s_raw!r}（可用：强/中/弱）")
        out.append({"point": name, "freq": freq, "strength": s_raw,
                    "weight": w, "score": freq * w})
    out.sort(key=lambda x: -x["score"])
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return {"rows": out}


# ---------------------------------------------------------------- 输出

def to_markdown(res: dict, pts: dict | None, fixable: set[str]) -> str:
    L = ["# 评论统计报告（确定性聚合）\n"]
    L.append("## 1. 总体分布\n")
    L.append(f"- 评论总数：**{res['total']}**"
             + (f"（{res['unrated']} 条评分缺失已剔除）" if res["unrated"] else ""))
    L.append(f"- 好评（4–5★）：**{res['good']}**（{res['good_rate']:.1%}）")
    L.append(f"- 中评（3★）：**{res['mid']}**（{res['mid_rate']:.1%}）")
    L.append(f"- 差评（1–2★）：**{res['bad']}**（{res['bad_rate']:.1%}）")
    if res["image_count"]:
        L.append(f"- 带图评论：{res['image_count']}（{res['image_rate']:.1%}）")
    L.append("")

    L.append("## 2. 差评归因\n")
    if res["attribution_mismatch"] != 0:
        L.append(f"> 🔴 **合计校验失败**：归因合计 {res['attribution_total']} ≠ 差评数 "
                 f"{res['bad']}（差 {res['attribution_mismatch']:+d}）。"
                 f"**先修数据再下结论**，未归因 {len(res['unattributed'])} 行："
                 f"{', '.join(res['unattributed'][:6])}"
                 f"{'…' if len(res['unattributed']) > 6 else ''}\n")
    L.append("| 类别 | 条数 | 占差评比 | 可修复 |")
    L.append("|---|---|---|---|")
    for k, v in res["attribution"].items():
        mark = "✅" if k in fixable else "❌"
        L.append(f"| {k} | {v} | {v / res['bad']:.1%} | {mark} |")
    L.append(f"| **合计** | **{res['attribution_total']}** | "
             f"{res['attribution_total'] / res['bad']:.1%} | "
             f"**{res['fixable_count']} 条可修 = {res['fixable_rate']:.1%}** |")
    L.append("")
    L.append(f"> 可修复口径（--fixable 指定）：{'、'.join(res['fixable_set'])}。"
             f"可修复 = 改文案/补图/补说明即可解决，成本接近零；"
             f"不可修复 = 物流/质量类，周期以周/月计。\n")

    if pts:
        L.append("## 3. 好评卖点排行（频次 × 情感权重）\n")
        L.append("| # | 卖点 | 提及频次 | 强度 | 权重 | 综合分 |")
        L.append("|---|---|---|---|---|---|")
        for r in pts["rows"]:
            L.append(f"| {r['rank']} | {r['point']} | {r['freq']} | "
                     f"{r['strength']} | {r['weight']} | **{r['score']}** |")
        L.append("")
        L.append("> 综合分 = 频次 × 权重（强=3 / 中=2 / 弱=1）。"
                 "排行指导详情页与主图的卖点优先级，**不指导真伪**——"
                 "真实性仍须回到 spec_table。\n")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="评论统计聚合（确定性算术）")
    ap.add_argument("--file", required=True, help="评论 CSV（rating 必填，category/has_image 可选）")
    ap.add_argument("--fixable", default="误解型,参数不符合预期,配件缺失,使用困难",
                    help="可修复类目，逗号分隔")
    ap.add_argument("--points", help="卖点 CSV（卖点,频次,强度），可选")
    ap.add_argument("--format", choices=["md", "json", "both"], default="md")
    ap.add_argument("-o", "--output", help="输出文件前缀")
    args = ap.parse_args()

    fixable = {x.strip() for x in args.fixable.split(",") if x.strip()}
    res = analyze_reviews(args.file, fixable)
    pts = analyze_points(args.points) if args.points else None

    md = to_markdown(res, pts, fixable)
    if args.format in ("md", "both"):
        _out(md)
    if args.format in ("json", "both"):
        payload = {"reviews": res, "selling_points": pts}
        _out("\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output:
        pref = Path(args.output)
        if args.format in ("md", "both"):
            pref.with_suffix(".md").write_text(md, encoding="utf-8")
        if args.format in ("json", "both"):
            pref.with_suffix(".json").write_text(
                json.dumps({"reviews": res, "selling_points": pts},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        _out(f"\n已写出：{pref.with_suffix('.md')}")


if __name__ == "__main__":
    main()
