"""Human-selected organic-content hypotheses and pending next projects.

Uses existing project/media/fact tables; never copies approvals or replaces P16 paid-ad flow.
"""

import contextlib
import copy
import hashlib
import json
import shutil
import time
from datetime import date

from ..customer import Customers
from ..customer_api import Settings
from ..db import Conflict
from ..media import digest, safe_path
from ..products import Products
from .media_pack import job_binding
from .records import encoded


def hypotheses(records, snapshot_id, parent_job_id, insights_id=None):
    frozen = records.get(snapshot_id, "observation_snapshot")
    job, binding = job_binding(records, parent_job_id)
    rows = [
        r
        for r in frozen["payload"]["rows"]
        if r["binding"]
        and r["binding"]["job_id"] == parent_job_id
        and r["binding"]["video_sha256"] == binding["video_sha256"]
    ]
    if not rows:
        raise ValueError("这份冻结观测没有关联该成片版本，请先登记并重新冻结")
    insight = records.get(insights_id, "comment_insights") if insights_id else None
    if insight and any(r["account_ref"] != insight["payload"]["account_ref"] for r in rows):
        raise ValueError("评论与父片数据不是同一账户")
    return records.put(
        "hypothesis",
        {
            "schema_version": "CreativeHypothesis.v1",
            "snapshot_ref": snapshot_id,
            "snapshot_basis": frozen["basis"],
            "parent": binding,
            "insights_ref": insights_id,
            "evidence_refs": [
                {
                    "batch_ref": r["batch_ref"],
                    "content_ref": r["content_ref"],
                    "metric_date": r["metric_date"],
                }
                for r in rows
            ],
            "candidates": [
                {
                    "id": "opening",
                    "title": "先给动作或观察点，再介绍商品",
                    "change": "只调整开头讲法与选段；保留原完整动作，效果仍待验证",
                },
                {
                    "id": "detail",
                    "title": "补一处能回答问题的近景",
                    "change": "依据评论候选选择问题，先检查实拍是否支持，不凭评论新增性能事实",
                },
                {
                    "id": "rhythm",
                    "title": "缩短非动作留白",
                    "change": "减少重复画面；动作展示和真实人声不加速，字幕重新听核",
                },
            ],
            "selection": "pending",
            "method": "bounded_local_rules",
            "causal_inference": False,
            "note": "创意候选不代表已证明现版为何表现如此；人工选择后新建待确认项目",
        },
    )


def select_hypothesis(records, hypothesis_id, candidate_id, reviewer, confirmed):
    if confirmed is not True or not 1 <= len(reviewer.strip()) <= 120:
        raise ValueError("请人工选择下一版假设并填写确认人")
    hypothesis = records.get(hypothesis_id, "hypothesis")
    h = hypothesis["payload"]
    choice = next((c for c in h["candidates"] if c["id"] == candidate_id), None)
    if not choice:
        raise ValueError("请选择这份冻结提案中的候选")
    for old in records.matches(
        "iteration", {"hypothesis_ref": hypothesis_id, "candidate_id": candidate_id}
    ):
        if (
            old["payload"]["hypothesis_ref"] == hypothesis_id
            and old["payload"]["candidate_id"] == candidate_id
        ):
            return old
    frozen = records.get(h["snapshot_ref"], "observation_snapshot")
    if frozen["basis"] != h["snapshot_basis"]:
        raise ValueError("冻结观测依据变化")
    job, binding = job_binding(records, h["parent"]["job_id"])
    if (
        binding["video_sha256"] != h["parent"]["video_sha256"]
        or binding["input_snapshot_hash"] != h["parent"]["input_snapshot_hash"]
    ):
        raise ValueError("父成片版本变化，请重新提出假设")
    pid = hashlib.sha256((hypothesis_id + ":" + candidate_id).encode()).hexdigest()[:32]
    directory = records.root / "customers" / pid
    original_pid = (job.get("provenance") or {}).get("product_id")
    parent_project = None
    if original_pid:
        with contextlib.suppress(KeyError):
            parent_project = Customers(records.root, records.store).get(original_pid)
    if parent_project:
        provenance = job.get("provenance") or {}
        if (
            not parent_project["job"]
            or parent_project["job"]["id"] != job["id"]
            or parent_project["inputs_changed"]
            or parent_project["product"]["status"] != "script_confirmed"
            or parent_project["product"]["current_review_id"]
            != (provenance.get("fact_review") or {}).get("id")
            or parent_project["product"]["current_draft_id"]
            != (provenance.get("script_approval") or {}).get("draft_id")
        ):
            raise ValueError(
                "父片当前资料、文稿或活动版本已变化，请先核对或恢复对应版本，再提出下一版假设"
            )
    facts = Products.confirmed_facts(parent_project["product"]) if parent_project else []
    # Facts are copied as UNCONFIRMED candidate quotations, not promoted from comments/script.
    units = [
        {
            "id": "fact-" + str(i),
            "text": f["text"],
            "locator": "父项目已核对原文候选：" + f["id"] + "；本版仍须重新确认",
        }
        for i, f in enumerate(facts)
    ]
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "下一版待核对资料.txt"
    source.write_text(
        "下一版创作假设："
        + choice["change"]
        + "\n\n参考文稿（不是商品事实）：\n"
        + job["script"]
        + "\n\n待重新确认事实原文：\n"
        + "\n".join(u["text"] for u in units)
    )
    media = []
    for asset in job["assets"]:
        if asset["kind"] == "audio":
            continue  # Do not attach an old voice as if it matches a new script.
        aid = hashlib.sha256((pid + asset["id"]).encode()).hexdigest()[:32]
        old = safe_path(records.root, asset["path"])
        if not old.is_file() or digest(old) != asset["sha256"]:
            raise ValueError("父片素材已变化，不复用错误文件")
        path = directory / "media" / (aid + old.suffix)
        path.parent.mkdir(exist_ok=True)
        shutil.copyfile(old, path)
        meta = copy.deepcopy(asset["metadata"])
        if meta.get("identity"):
            meta["identity_reference"] = meta.pop("identity")
        # Intake originals belong to the old job. Keep only the actual copied normalized file.
        meta.pop("intake", None)
        media.append(
            {
                **asset,
                "id": aid,
                "path": path.relative_to(records.root).as_posix(),
                "metadata": meta,
                "size": path.stat().st_size,
            }
        )
    settings = Settings.model_validate(
        parent_project["settings"]
        if parent_project
        else {"delivery_version": 1, "brief": {"format": "narrated"}}
    ).model_dump()
    settings["review_context"] = "下一版假设 " + hypothesis_id + "；全部人工确认待完成"
    title = (parent_project["product"]["title"] if parent_project else job["title"])[
        :100
    ] + " · 下一版"
    payload = {
        "schema_version": "CreativeIteration.v1",
        "hypothesis_ref": hypothesis_id,
        "snapshot_ref": h["snapshot_ref"],
        "parent": h["parent"],
        "candidate_id": candidate_id,
        "selected_change": choice,
        "reviewer": reviewer,
        "confirmed": True,
        "project_id": pid,
        "reference_script": job["script"],
        "human_gates": "all_pending",
        "causal_inference": False,
    }

    def create(c):
        if parent_project:
            Customers(records.root, records.store).row(c, original_pid, parent_project["revision"])
            Products(records.store)._row(c, original_pid, parent_project["product"]["revision"])
        if c.execute("SELECT 1 FROM customer_projects WHERE product_id=?", (pid,)).fetchone():
            raise Conflict("这个假设已创建下一版，请刷新查看；未重复创建")
        current = records.store._row(c, job["id"])
        parsed = json.loads(current["snapshot"]) if current["snapshot"] else None
        if current["status"] != job["status"] or parsed != job["snapshot"]:
            raise ValueError("父片状态变化，请刷新后重新选择")
        now = time.time()
        c.execute(
            "INSERT INTO products(id,title,status,created_at,updated_at) VALUES(?,?,'collecting',?,?)",
            (pid, title, now, now),
        )
        c.execute(
            "INSERT INTO customer_projects VALUES(?,0,?,NULL,?,?)",
            (pid, encoded(settings), now, now),
        )
        sid = hashlib.sha256((pid + "source").encode()).hexdigest()[:32]
        c.execute(
            "INSERT INTO product_sources VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                pid,
                "document",
                source.name,
                None,
                None,
                source.relative_to(records.root).as_posix(),
                digest(source),
                encoded({"units": units, "iteration_ref": hypothesis_id}),
                now,
            ),
        )
        for unit in units:
            fid = hashlib.sha256((pid + unit["id"]).encode()).hexdigest()[:32]
            c.execute(
                "INSERT INTO product_facts VALUES(?,?,?,?,?,?,?)",
                (fid, pid, sid, unit["id"], unit["text"], unit["locator"], now),
            )
        for a in media:
            c.execute(
                "INSERT INTO customer_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a["id"],
                    pid,
                    a["name"],
                    a["path"],
                    a["kind"],
                    "product",
                    a["sha256"],
                    a["size"],
                    encoded(a["metadata"]),
                    a["metadata"].get("source_in", 0),
                    "父片复用；同款与动作仍须核对",
                    now,
                ),
            )

    return records.put("iteration", payload, on_create=create)


def compare_iteration(records, iteration_id, later_snapshot_id):
    iteration = records.get(iteration_id, "iteration")["payload"]
    before = records.get(iteration["snapshot_ref"], "observation_snapshot")["payload"]
    after = records.get(later_snapshot_id, "observation_snapshot")["payload"]
    reasons = []
    _, parent_binding = job_binding(records, iteration["parent"]["job_id"])
    if parent_binding["video_sha256"] != iteration["parent"]["video_sha256"]:
        raise ValueError("父成片摘要与假设不符")
    keys = (
        "counting",
        "timezone",
        "metric_definitions",
        "dataset_kind",
        "currency",
        "attribution_window",
    )
    if any(before[k] != after[k] for k in keys):
        reasons.append("metric_contract_mismatch")
    if (
        before["counting"] != "daily"
        or not before["aggregation_allowed"]
        or not after["aggregation_allowed"]
    ):
        reasons.append("daily_coverage_required")
    a = [
        r
        for r in before["rows"]
        if r["binding"] and r["binding"]["job_id"] == iteration["parent"]["job_id"]
    ]
    b = []
    for row in after["rows"]:
        if not row["binding"]:
            continue
        job = records.store.get(row["binding"]["job_id"])
        if (job.get("provenance") or {}).get("product_id") == iteration["project_id"]:
            _, actual = job_binding(records, job["id"])
            if any(actual[k] != row["binding"][k] for k in ("video_sha256", "input_snapshot_hash")):
                raise ValueError("下一版冻结绑定与实际成片不符")
            b.append(row)
    if not b:
        reasons.append("next_version_binding_missing")
    elif {r["account_ref"] for r in a} != {r["account_ref"] for r in b}:
        reasons.append("account_mismatch")
    if a and b:
        start_a, end_a = min(r["metric_date"] for r in a), max(r["metric_date"] for r in a)
        start_b, end_b = min(r["metric_date"] for r in b), max(r["metric_date"] for r in b)
        if start_b <= end_a or (date.fromisoformat(end_a) - date.fromisoformat(start_a)) != (
            date.fromisoformat(end_b) - date.fromisoformat(start_b)
        ):
            reasons.append("periods_overlap_or_differ_in_length")
    actual_changes = None
    if b:
        if len({r["binding"]["job_id"] for r in b}) != 1:
            reasons.append("multiple_next_versions")
        first_manifest = iteration["parent"]["features"].get("production_manifest")
        next_manifest = b[0]["binding"]["features"].get("production_manifest")
        if not first_manifest or not next_manifest:
            reasons.append("creative_change_manifest_missing")
        else:
            x, y = first_manifest["board"], next_manifest["board"]
            actual_changes = {
                "script_changed": first_manifest["script"] != next_manifest["script"],
                "shots_changed": x.get("shots") != y.get("shots"),
                "sound_parameters_changed": any(
                    x.get(k) != y.get(k) for k in ("narration", "music_id", "music_db")
                ),
                "scope": "saved parameters and asset SHA; no pixel equivalence claim",
            }
            if not any(
                actual_changes[k]
                for k in ("script_changed", "shots_changed", "sound_parameters_changed")
            ):
                reasons.append("no_recorded_creative_change")
    missing = [
        m
        for m in ("views", "likes", "comments", "shares")
        if any(r["values"][m] is None for r in a + b)
    ]
    delta = (
        None
        if reasons
        else {
            m: str(sum(int(r["values"][m]) for r in b) - sum(int(r["values"][m]) for r in a))
            if m not in missing
            else None
            for m in ("views", "likes", "comments", "shares")
        }
    )
    return records.put(
        "comparison",
        {
            "schema_version": "CreativeComparison.v1",
            "iteration_ref": iteration_id,
            "baseline_snapshot_ref": iteration["snapshot_ref"],
            "later_snapshot_ref": later_snapshot_id,
            "comparable": not reasons,
            "reasons": reasons,
            "missing_metrics": missing,
            "delta": delta,
            "actual_changes": actual_changes,
            "causal_inference": False,
            "conclusion": "只描述已登记版本在各自期间的观测差异；时点、人群等未控制，不归因到创意改动",
        },
    )
