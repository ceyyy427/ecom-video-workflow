"""Isolated read/export/review/expansion checks with explicit synthetic-data labels."""

import json

from ..customer import Customers
from ..db import Store
from ..maintenance import restore, verify
from .comments import analyze_comments, import_comments
from .iterations import compare_iteration, hypotheses, select_hypothesis
from .media_pack import publication_pack, register_content
from .observations import freeze_observations, import_csv
from .records import Records
from .resources import load_resources

LABEL = "AUTOMATED FIXTURE domestic suite; not customer approval/publication/data"


def validate_cases(cases):
    import re

    if not 2 <= len(cases) <= 4 or len({c.get("category") for c in cases}) < 2:
        raise ValueError("至少两个不同品类的隔离验收工程")
    if any(not re.fullmatch("[a-f0-9]{32}", c.get("project_id", "")) for c in cases):
        raise ValueError("运营验收须指定来源副本内的项目ID")


def run_suite(work, bundle, data, mode, stage):
    validate_cases(data["cases"])
    work.mkdir(mode=0o700)
    (work / ".domestic-suite-acceptance").write_text(LABEL + "\n")
    verified = verify(bundle)
    restore(bundle, work / "runtime")
    root = work / "runtime"
    store = Store(root / "workflow.db")
    records = Records(root, store)
    resources = load_resources()
    report = {
        "stage": stage,
        "mode": mode,
        "customer_signoff": False,
        "cloud_calls": 0,
        "model_calls": 0,
        "platform_writes": 0,
        "backup_verified": verified,
        "resources_checked": len(resources.entries),
        "official_live_verified": False,
        "cases": [],
    }
    if mode == "customer":
        # A customer run never synthesizes confirmations or invents report rows.
        report.update(
            status="needs_human",
            required=[
                "实际核对商品与六方向",
                "实际听核本版配音",
                "逐镜与整片看听",
                "核对素材公开范围",
                "核对真实账号与报表口径",
                "最后由客户验收并发布",
            ],
        )
    else:
        for case in data["cases"]:
            p = Customers(root, store).get(case["project_id"])
            all_receipts = p["product"]["fact_reviews"] + p["product"]["script_approvals"]
            if not all_receipts or any(
                not r["reviewer"].startswith("AUTOMATED FIXTURE") for r in all_receipts
            ):
                raise ValueError("工程模式只能重放已有明确标记的工程审批，不能复用客户签收")
            jid = p["job"]["id"]
            from ..connectors.xhs_import import add_account, freeze_source

            account = add_account(records, "douyin", LABEL + " " + case["id"], case["id"])
            pack = publication_pack(
                records, jid, "douyin", "工程交接样例", "工程假数据，仅验证本机流程"
            )
            assert pack["payload"]["review_status"] == "pending"
            content = "engineering-" + case["id"]
            register_content(records, pack["id"], account["id"], content, LABEL, True)
            raw = (
                "content_id,metric_date,views,likes,comments,shares\n"
                + content
                + ",2026-10-01,100,0,,2\n"
            ).encode()
            source = freeze_source(records, account["id"], raw, "engineering.csv", LABEL)
            cfg = {
                "counting": "daily",
                "timezone": "Asia/Shanghai",
                "observed_at": "2026-10-02T08:00:00+08:00",
                "metric_definitions": {
                    "views": "工程报表播放次数",
                    "likes": "工程报表点赞次数",
                    "comments": "工程报表评论次数",
                    "shares": "工程报表分享次数",
                },
            }
            batch = import_csv(records, source["id"], cfg)
            item = {
                "case": case["id"],
                "category": case["category"],
                "project_id": p["id"],
                "pack_id": pack["id"],
                "source_id": source["id"],
                "batch_id": batch["id"],
                "zero_kept": batch["payload"]["rows"][0]["values"]["likes"] == "0",
                "missing_kept": batch["payload"]["rows"][0]["values"]["comments"] is None,
            }
            if stage in ("review", "mac"):
                snapshot = freeze_observations(records, [batch["id"]])
                comments = import_comments(
                    records,
                    account["id"],
                    ("content_id,text\n" + content + ",这个细节能看近一点吗？\n").encode(),
                    LABEL,
                )
                insight = analyze_comments(records, comments["id"])
                hyp = hypotheses(records, snapshot["id"], jid, insight["id"])
                iteration = select_hypothesis(records, hyp["id"], "detail", LABEL, True)
                new = Customers(root, store).get(iteration["payload"]["project_id"])
                assert (
                    not new["product"]["fact_reviews"]
                    and not new["product"]["script_approvals"]
                    and new["job"] is None
                )
                # No fabricated next film/binding: explain why the same baseline cannot be a next round.
                comparison = compare_iteration(records, iteration["id"], snapshot["id"])
                assert (
                    comparison["payload"]["comparable"] is False
                    and comparison["payload"]["delta"] is None
                )
                item.update(
                    snapshot_id=snapshot["id"],
                    insight_id=insight["id"],
                    hypothesis_id=hyp["id"],
                    iteration_id=iteration["id"],
                    next_project_id=new["id"],
                    comparison_id=comparison["id"],
                    comparison_status="next_version_data_pending",
                    next_project_approvals=0,
                )
            if stage in ("expansion", "mac"):
                from .media_pack import image_pack
                from .research import analyze_market, create_strategy

                market = analyze_market(
                    records,
                    b"sku,product_name,price,currency,sampled_at,source\nengineering-a,Demo,100,CNY,2026-10-01,synthetic-row-1\n",
                    LABEL,
                    "douyin",
                )
                strategy = create_strategy(
                    records,
                    p["id"],
                    p["product"]["revision"],
                    "通勤及周末使用人群",
                    "克制清楚",
                    market["id"],
                )
                visual = next(a for a in p["media"] if a["kind"] != "audio")
                cover = image_pack(records, strategy["id"], visual["id"])
                diagram = image_pack(records, strategy["id"], None)
                item.update(
                    research_id=market["id"],
                    strategy_id=strategy["id"],
                    cover_id=cover["id"],
                    diagram_id=diagram["id"],
                    generated_product_appearance=False,
                )
            report["cases"].append(item)
        report.update(
            status="engineering_passed_manual_pending",
            synthetic_report_rows=True,
            new_customer_approvals=0,
            fixture_selections_only=True,
        )
    from ..maintenance import backup

    backup(root, work / "verified-backup")
    report["output_backup_verified"] = verify(work / "verified-backup")
    (work / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
