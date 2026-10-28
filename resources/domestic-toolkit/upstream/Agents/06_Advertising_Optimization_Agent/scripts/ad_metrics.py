#!/usr/bin/env python3
"""广告决策层算术脚本（Shopee / Mercado Livre 广告）—— 只算，不猜，不执行。

  python ad_metrics.py calc --price 113.40 --product-cost 55 --commission 14 \
      --return 2 --tax 0 --target-acos 25 --cvr 0.44
  python ad_metrics.py diagnose --file ../examples/sample-ad-report.csv \
      --price 113.40 --product-cost 55 --commission 14 --return 2 --tax 0 --target-acos 25

设计原则（与 01 模块一致）：能算的别让模型猜。
  本脚本只输出确定性数字与分级动作建议（P0 止血 / P1 改善 / P2 放量），
  **不改后台、不执行** —— 执行由人决定（合规与风控要求）。

盈亏线公式（含巴西税费项）：
  广告前贡献 = 售价 − 产品成本 − 头程 − 尾程 − 售价×佣金% − 售价×退货损耗% − 售价×税率%
  盈亏线 ACoS = 广告前贡献 ÷ 售价      盈亏线 ROAS = 1 ÷ 盈亏线 ACoS
  可承受 CPC  = 售价 × 转化率 × 目标 ACoS
税率口径：巴西税制复杂（ICMS/PIS/COFINS/Simples Nacional），此处用「综合有效税率」
  一个参数表示（按售价百分比），由使用者按自己的税制填。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

# 与 02 模块共用同一份平台费率预设（单一事实来源）
PLATFORM_FEES = (Path(__file__).resolve().parents[2]
                 / "02_Product_Strategy_Agent" / "scripts" / "platform_fees.json")


def _tier_lookup(price, tiers, default=0.0):
    for t in tiers or []:
        mx = t.get("max")
        if mx is None or price <= float(mx):
            return float(t.get("pct", t.get("fee", default)))
    return default


def _resolve_fees(args):
    """费率解析：显式 CLI 参数 > 平台预设（--platform）> 0。"""
    preset = None
    if getattr(args, "platform", None):
        try:
            plats = json.loads(PLATFORM_FEES.read_text(encoding="utf-8"))
        except OSError:
            sys.exit(f"[ERROR] 读不到平台费率表：{PLATFORM_FEES}")
        key = args.platform.strip()
        if key not in plats:
            matches = [k for k in plats
                       if not k.startswith("_") and (k == key or k.startswith(key + "_"))]
            if len(matches) == 1:
                key = matches[0]
            else:
                keys = "、".join(k for k in plats if not k.startswith("_"))
                sys.exit(f"[INPUT_MISSING] 未知平台 {args.platform!r}。可用：{keys}")
        preset = plats[key]

    price = args.price
    if args.commission is not None:
        comm = args.commission
    elif preset:
        if "commission_pct" in preset:
            comm = float(preset["commission_pct"])
        elif preset.get("commission_tiers"):
            comm = _tier_lookup(price, preset["commission_tiers"])
        else:
            comm = 0.0
    else:
        comm = 0.0

    def scalar(flag, pkey):
        if flag is not None:
            return float(flag)
        if preset and pkey in preset:
            return float(preset[pkey])
        return 0.0

    if getattr(args, "fixed_fee", None) is not None:
        ff = float(args.fixed_fee)
    elif preset and preset.get("fixed_fee_tiers"):
        ff = _tier_lookup(price, preset["fixed_fee_tiers"])
    else:
        ff = 0.0

    return comm, scalar(args.return_rate, "return_pct"), scalar(args.tax, "tax_pct"), \
        scalar(getattr(args, "extra_pct", None), "extra_pct"), ff, \
        (preset or {}).get("label", getattr(args, "platform", None) or "custom")
import sys

# 列名自动映射（中 / 英 / 葡）
COLUMN_MAP = {
    "name":    ["广告名称", "广告组", "计划名称", "campaign", "name", "ad_group", "campanha"],
    "impressions": ["曝光量", "曝光", "展示量", "impressions", "imps", "impressoes"],
    "clicks":  ["点击量", "点击数", "点击", "clicks", "cliques"],
    "spend":   ["花费", "消耗", "花费金额", "spend", "cost", "gasto"],
    "orders":  ["订单数", "订单", "成交订单", "orders", "conversions", "pedidos"],
    "gmv":     ["销售额", "成交金额", "广告销售额", "gmv", "sales", "receita"],
}


def _num(v, default=0.0, kind="dec"):
    """容忍 'R$ 1.234,56' / '1,234' / '1.500' / '12.3%' / '-' / 空串。

    kind="int"（曝光/点击/订单）：点、逗号一律视为千分位，只留数字。
    kind="dec"（花费/销售额）：
      同时有 , 和 .  → 靠右的是小数分隔符；
      只有一个分隔符 → 小数位 ≤2 位按小数，否则按千分位（巴西 '1.500'=1500）。
    """
    if v is None:
        return default
    s = str(v).strip().replace("R$", "").replace("%", "").replace(" ", "")
    if s in ("", "-", "—", "暂无", "N/A", "nan"):
        return default
    neg = s.startswith("-")
    s = s.lstrip("-")
    if kind == "int":
        digits = "".join(ch for ch in s if ch.isdigit())
        if not digits:
            return default
        return (-1 if neg else 1) * int(digits)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") \
            else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head}.{tail}" if len(tail) <= 2 else head + tail
    elif "." in s:
        head, _, tail = s.rpartition(".")
        s = s if len(tail) <= 2 else head + tail
    try:
        return (-1 if neg else 1) * float(s)
    except ValueError:
        return default


def _pick(header, kind):
    low = [h.strip().lower() for h in header]
    for cand in COLUMN_MAP[kind]:
        if cand.lower() in low:
            return header[low.index(cand.lower())]
    return None


def cost_model(args):
    price = args.price
    comm, ret, tax, extra, ff, plat_label = _resolve_fees(args)
    contrib = (price - args.product_cost - args.first_leg - args.shipping
               - price * (comm + ret + tax + extra) / 100 - ff)
    be_acos = contrib / price if price else 0
    return dict(price=price, platform=plat_label,
                commission_pct_applied=comm, fixed_fee_applied=round(ff, 2),
                extra_pct_applied=extra,
                pre_ad_contribution=round(contrib, 2),
                break_even_acos=round(be_acos, 4),
                break_even_roas=round(1 / be_acos, 2) if be_acos > 0 else None)


def cmd_calc(args):
    m = cost_model(args)
    out = dict(mode="calc", **m)
    if args.target_acos:
        ta = args.target_acos / 100
        out["target_acos"] = args.target_acos
        out["target_roas"] = round(1 / ta, 2)
        if args.cvr:
            out["affordable_cpc"] = round(m["price"] * (args.cvr / 100) * ta, 2)
            out["affordable_cpc_note"] = "售价 × 转化率 × 目标ACoS —— 出价高于它即亏损加速"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _grade(row, m, args, be_roas, target_roas):
    """确定性分级：P0 止血 / P1 改善 / P2 放量 / INFO 数据不足。返回 (级别, 动作列表)。"""
    acts = []
    name = row["name"]
    imp, clk, spend, orders = row["impressions"], row["clicks"], row["spend"], row["orders"]
    gmv = row["gmv"] if row["gmv"] else orders * m["price"]
    ctr = clk / imp if imp else 0
    cvr = orders / clk if clk else 0
    cpc = spend / clk if clk else 0
    roas = gmv / spend if spend else None
    affordable_cpc = m["price"] * cvr * (args.target_acos / 100) if cvr else None

    # 0) 数据充分性 —— 数据不足一律不动（攒数据，过早上手段=噪声驱动）
    if imp < args.min_impressions:
        return "INFO", [f"曝光 {imp:,.0f} < {args.min_impressions:,}，数据不足，本轮不动，继续攒数据"], dict(
            ctr=ctr, cvr=cvr, cpc=cpc, roas=roas, affordable_cpc=affordable_cpc, gmv=gmv)
    if not spend:
        return "INFO", ["无花费，本轮不动"], dict(ctr=ctr, cvr=cvr, cpc=cpc, roas=roas,
                                                affordable_cpc=affordable_cpc, gmv=gmv)

    # 1) CTR 检查（基准 3–5%，<2% 明确偏低）—— 症状指向素材，回流 04
    if ctr < 0.02:
        acts.append(f"CTR {ctr:.2%} 低于 2% —— 回流 04 换主图/首图（不要在广告端解决素材问题）")
    elif ctr < 0.03:
        acts.append(f"CTR {ctr:.2%} 处于 2–3% 观察区，暂不动素材")

    # 2) 订单为零（点击足够 = 素材没问题，落地页/价格/评论有问题）
    if orders == 0 and clk >= 30:
        acts.append(f"点击 {clk:,.0f} 零订单 —— 回流 03 检查详情页与价格带，广告端只降出价止血")
        acts.append(f"出价降至可承受 CPC {affordable_cpc:.2f} 以下（当前 CPC {cpc:.2f}）")
        return "P0", acts, dict(ctr=ctr, cvr=cvr, cpc=cpc, roas=roas,
                                affordable_cpc=affordable_cpc, gmv=gmv)

    # 3) ROAS 分级（锚盈亏线，不锚感觉）
    if roas is None:
        return "INFO", ["无花费数据"], dict(ctr=ctr, cvr=cvr, cpc=cpc, roas=None,
                                            affordable_cpc=affordable_cpc, gmv=gmv)
    if roas < 0.5 * be_roas:
        acts.append(f"ROAS {roas:.2f} < 盈亏线一半（{be_roas:.2f}）—— P0 止血")
        acts.append(f"预算降至最低档、出价降至 {affordable_cpc:.2f} 以下（当前 CPC {cpc:.2f}）")
        acts.append("❗ 不要暂停广告 —— 暂停破坏连续性并降低广告权重（应降预算降出价，见 actions.md）")
    elif roas < be_roas:
        acts.append(f"ROAS {roas:.2f} 低于盈亏线 {be_roas:.2f} —— P1 改善")
        acts.append(f"出价降至 {affordable_cpc:.2f} 以下（当前 CPC {cpc:.2f}），预算暂不动")
        if cvr < 0.01:
            acts.append(f"转化率 {cvr:.2%} < 1% —— 瓶颈在转化不在流量，回流 03/07，广告端不加大投放")
    elif roas < target_roas:
        acts.append(f"ROAS {roas:.2f} 在盈亏线与目标 {target_roas:.2f} 之间 —— P1 维持")
        acts.append("预算与出价都不动；改善转化率是唯一杠杆")
    else:
        acts.append(f"ROAS {roas:.2f} ≥ 目标 {target_roas:.2f} —— P2 放量")
        acts.append("预算 +20~30%（一次只加这一档），观察 3 天再决定下一档")

    # 4) 迭代纪律：输出「本轮明确不动」清单
    keep = "预算与出价结构、素材、listing 文案" if roas >= be_roas else "listing 文案与素材"
    acts.append(f"本轮明确不动：{keep}（一次只改一个病因）")
    return ("P0" if roas < 0.5 * be_roas else
            "P2" if roas >= target_roas else "P1"), acts, dict(
        ctr=ctr, cvr=cvr, cpc=cpc, roas=roas, affordable_cpc=affordable_cpc, gmv=gmv)


def cmd_diagnose(args):
    m = cost_model(args)
    be_roas = m["break_even_roas"]
    target_roas = 1 / (args.target_acos / 100) if args.target_acos else be_roas * 1.5

    try:
        with open(args.file, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        sys.exit(f"[ERROR] 读不了文件：{e}")
    if not rows:
        sys.exit("[ERROR] CSV 里没有数据行")

    header = list(rows[0].keys())
    col = {k: _pick(header, k) for k in COLUMN_MAP}
    missing = [k for k, v in col.items() if v is None and k != "gmv"]
    if missing:
        sys.exit(f"[ERROR] 认不出这些列（可用映射见 references/metrics.md）：{missing}")

    results, totals = [], dict(spend=0.0, gmv=0.0, orders=0.0, clicks=0.0, impressions=0.0)
    for r in rows:
        row = dict(name=(r.get(col["name"]) or "?").strip(),
                   impressions=_num(r.get(col["impressions"]), kind="int"),
                   clicks=_num(r.get(col["clicks"]), kind="int"),
                   spend=_num(r.get(col["spend"]), kind="dec"),
                   orders=_num(r.get(col["orders"]), kind="int"),
                   gmv=_num(r.get(col["gmv"]), kind="dec") if col["gmv"] else 0.0)
        grade, acts, met = _grade(row, m, args, be_roas, target_roas)
        results.append(dict(campaign=row["name"], grade=grade,
                            impressions=row["impressions"], clicks=row["clicks"],
                            spend=round(row["spend"], 2), orders=row["orders"],
                            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in met.items()},
                            actions=acts))
        for k in totals:
            totals[k] += row[k] if k != "gmv" else (row["gmv"] or row["orders"] * m["price"])

    total_roas = totals["gmv"] / totals["spend"] if totals["spend"] else None
    out = dict(mode="diagnose", cost_model=m, target_acos=args.target_acos,
               target_roas=target_roas, total=dict(
                   campaigns=len(results), **{k: round(v, 2) for k, v in totals.items()},
                   roas=round(total_roas, 2) if total_roas else None,
                   net_contribution=round(m["pre_ad_contribution"] / m["price"] * totals["gmv"] - totals["spend"], 2)),
               campaigns=sorted(results, key=lambda x: (x["grade"], -(x["roas"] or 0))))
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if not args.json:
        icon = {"P0": "🔴", "P1": "🟡", "P2": "🟢", "INFO": "⚪"}
        print(f"\n盈亏线 ROAS {be_roas} ｜ 目标 ROAS {target_roas} ｜ "
              f"整体 ROAS {out['total']['roas']} ｜ 整体净贡献 R$ {out['total']['net_contribution']}\n")
        for c in out["campaigns"]:
            print(f"{icon[c['grade']]} [{c['grade']}] {c['campaign']}  "
                  f"ROAS {c['roas'] if c['roas'] else '-'}  花费 R$ {c['spend']}  订单 {c['orders']:g}")
            for a in c["actions"]:
                print(f"     · {a}")
            print()
    return 0


def main():
    ap = argparse.ArgumentParser(description="广告决策层算术脚本（只算不执行）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calc", help="由成本结构算盈亏线 / 可承受 CPC")
    c.add_argument("--price", type=float, required=True, help="售价 R$")
    c.add_argument("--product-cost", type=float, required=True)
    c.add_argument("--shipping", type=float, default=0, help="尾程运费")
    c.add_argument("--first-leg", type=float, default=0, help="头程运费")
    c.add_argument("--platform", help="平台费率预设 key（与 02 sku_pricing 共用 platform_fees.json）")
    c.add_argument("--commission", type=float, default=None, help="平台佣金 %%（覆盖预设）")
    c.add_argument("--return", dest="return_rate", type=float, default=None, help="退货损耗 %%（覆盖预设）")
    c.add_argument("--tax", type=float, default=None, help="综合有效税率 %%（巴西税制自行折算）")
    c.add_argument("--extra-pct", type=float, default=None, help="平台附加 %%（如免运计划；覆盖预设）")
    c.add_argument("--fixed-fee", type=float, default=None, help="按件固定费 R$（覆盖预设阶梯）")
    c.add_argument("--target-acos", type=float, help="目标 ACoS %%")
    c.add_argument("--cvr", type=float, help="转化率 %%（算可承受 CPC 用）")

    d = sub.add_parser("diagnose", help="读广告导出 CSV → 指标 + P0/P1/P2 分级动作")
    d.add_argument("--file", required=True)
    d.add_argument("--price", type=float, required=True)
    d.add_argument("--product-cost", type=float, required=True)
    d.add_argument("--shipping", type=float, default=0)
    d.add_argument("--first-leg", type=float, default=0)
    d.add_argument("--platform", help="平台费率预设 key（与 02 sku_pricing 共用 platform_fees.json）")
    d.add_argument("--commission", type=float, default=None)
    d.add_argument("--return", dest="return_rate", type=float, default=None)
    d.add_argument("--tax", type=float, default=None)
    d.add_argument("--extra-pct", type=float, default=None)
    d.add_argument("--fixed-fee", type=float, default=None)
    d.add_argument("--target-acos", type=float, default=25)
    d.add_argument("--min-impressions", type=int, default=1000, help="数据充分性门槛")
    d.add_argument("--json", action="store_true")

    args = ap.parse_args()
    sys.exit(cmd_calc(args) if args.cmd == "calc" else cmd_diagnose(args))


if __name__ == "__main__":
    main()
