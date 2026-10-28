#!/usr/bin/env python3
"""参数一致性校验 —— 「参数唯一来源」原则的自动化。

  python spec_consistency.py --spec spec_table.csv --text 文案.txt --allow 2026,110
  python spec_consistency.py --spec spec_table.csv --title "标题" --text 详情.md

规则：**文案里出现的每一个数字，都必须能溯源到 spec_table**。
  溯源 = 与某个参数值中的数字相等（20000mAh 的 20000、45W 的 45、3 Saídas 的 3）。
  溯源不了的数字 = 参数漂移（笔误/编造/口径不一致），逐个列出并给出上下文。

反向检查：spec_table 里的数字在文案中一次都没出现 = 参数没讲，提醒补内容。
"""
import argparse
import csv
import json
import re
import sys

NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)(?![\w]*\d)(?=[^\d]|$)")


def load_spec(path):
    """spec_table：CSV（参数,数值 两列）或 JSON（dict）。返回 [(参数, 原始值, 数字集合)]。"""
    specs = []
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                specs.append((k, str(v), _nums_in(str(v))))
        return specs
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    for row in rows:
        if len(row) < 2 or not row[1].strip():
            continue
        if row[0].strip().lower() in ("参数", "param", "key", "项目"):
            continue
        val = row[1].strip()
        specs.append((row[0].strip(), val, _nums_in(val)))
    return specs


def _nums_in(s):
    """从字符串抽数字：支持 20.000（巴西千分位）、20,000、20000、1.5。"""
    out = set()
    for m in re.finditer(r"\d{1,3}(?:[.,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?", s):
        t = m.group()
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", t):
            t = t.replace(".", "").replace(",", "")
        else:
            t = t.replace(",", ".")
        try:
            f = float(t)
            out.add(int(f) if f == int(f) else round(f, 4))
        except ValueError:
            pass
    return out


def check(text, specs, allow):
    allow_nums = _nums_in(",".join(allow)) if allow else set()
    spec_nums = {}
    for name, raw, nums in specs:
        for n in nums:
            spec_nums.setdefault(n, []).append(name)

    text_norm = text.replace("\u00a0", " ")
    # 文案中的数字（带上下文）
    found, untraceable = [], []
    for m in re.finditer(r"\d{1,3}(?:[.,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?", text_norm):
        raw = m.group()
        t = raw
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", t):
            t = t.replace(".", "").replace(",", "")
        else:
            t = t.replace(",", ".")
        try:
            n = float(t)
            n = int(n) if n == int(n) else round(n, 4)
        except ValueError:
            continue
        ctx = text_norm[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
        found.append((n, raw, ctx))
        if n in spec_nums or n in allow_nums:
            continue
        untraceable.append(dict(number=raw, context=f"…{ctx}…",
                                hint="溯源不到 spec_table —— 笔误 / 编造 / 口径不一致？"))

    # 反向：参数从未出现（只查含数字的参数；无数值参数如"Display Digital"无从匹配）
    missing = []
    for name, raw, nums in specs:
        if not nums:
            continue
        hit = any(re.search(rf"(?<![\d.,]){re.escape(str(n))}(?![\d])", text_norm) for n in nums)
        if not hit:
            missing.append(f"{name}（{raw}）")

    ok = not untraceable
    return dict(ok=ok, spec_count=len(specs),
                numbers_in_text=len(found),
                untraceable=untraceable,
                missing_specs=missing)


def main():
    ap = argparse.ArgumentParser(description="参数一致性校验（参数唯一来源原则）")
    ap.add_argument("--spec", required=True, help="spec_table：CSV（参数,数值）或 JSON")
    ap.add_argument("--text", help="文案文件（标题+详情一起校验最佳）")
    ap.add_argument("--title", help="标题文本（可与 --text 同时给，合并校验）")
    ap.add_argument("--allow", help="豁免数字，逗号分隔（年份、无关常量等）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.text and not args.title:
        sys.exit("[ERROR] 给 --text 文件或 --title 文本")
    text = ""
    if args.title:
        text += args.title + "\n"
    if args.text:
        try:
            with open(args.text, encoding="utf-8") as f:
                text += f.read()
        except OSError as e:
            sys.exit(f"[ERROR] 读不了文件：{e}")

    specs = load_spec(args.spec)
    if not specs:
        sys.exit("[ERROR] spec_table 里没有可用参数")
    allow = [a.strip() for a in args.allow.split(",")] if args.allow else []

    rep = check(text, specs, allow)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"\n参数 {rep['spec_count']} 项 ｜ 文案中数字 {rep['numbers_in_text']} 处 ｜ "
              f"总判定: {'✅ 全部可溯源' if rep['ok'] else '❌ 存在参数漂移'}")
        for u in rep["untraceable"]:
            print(f"  ❌ {u['number']}: {u['context']}")
        if rep["missing_specs"]:
            print(f"  ⚠️ 以下参数在文案中从未出现（提醒补内容）：{'、'.join(rep['missing_specs'])}")
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
