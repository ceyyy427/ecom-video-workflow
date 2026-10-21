"""Human-selected creative iteration, atomic draft effects and frozen descriptive evidence."""

import json
import time
import uuid
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

from .creative_features import sha
from .customer import Customers, validate_customer_submission
from .db import Conflict
from .distribution import encode
from .experiment_contracts import Action, Attach, Evaluate, Proposal, Select, Style, enabled, parse
from .products import Products
from .review_contracts import identifier
from .review_snapshots import Reviews


class Replay(Exception):
    pass


def state(c, pid, parent):
    """One DB view, with private metadata hashed rather than returned to the client."""
    p = c.execute("SELECT * FROM customer_projects WHERE product_id=?", (pid,)).fetchone()
    product = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    j = c.execute("SELECT * FROM jobs WHERE id=?", (parent,)).fetchone()
    if not p or not product or not j or p["active_job_id"] != parent or j["status"] != "ready":
        raise Conflict("父成片或当前制作版本已变化，请基于当前版本重新提出假设。")
    validate_customer_submission(c, dict(j))
    prov = json.loads(j["provenance"]) if j["provenance"] else {}
    if (
        prov.get("product_id") != pid
        or (prov.get("fact_review") or {}).get("id") != product["current_review_id"]
        or (prov.get("script_approval") or {}).get("draft_id") != product["current_draft_id"]
    ):
        raise Conflict("当前事实或文稿与父成片不一致，旧变更集已过期。")

    def rows(sql, args):
        return [dict(r) for r in c.execute(sql, args)]

    return {
        "project_revision": p["revision"],
        "product_revision": product["revision"],
        "facts_review_id": product["current_review_id"],
        "script_draft_id": product["current_draft_id"],
        "parent_board_revision": j["storyboard_revision"],
        "project_hash": sha(dict(p)),
        "parent_hash": sha(dict(j)),
        "media_hash": sha(
            rows("SELECT * FROM customer_media WHERE product_id=? ORDER BY id", (pid,))
        ),
        "assets_hash": sha(rows("SELECT * FROM assets WHERE job_id=? ORDER BY id", (parent,))),
        "alignment_hash": sha(
            rows("SELECT * FROM alignments WHERE job_id=? ORDER BY id", (parent,))
        ),
        "sources_hash": sha(
            rows("SELECT * FROM product_sources WHERE product_id=? ORDER BY id", (pid,))
        ),
    }


def validate_experiment_submission(c, job):
    """Always enforce linked draft gates, even if the P16 UI flag is later disabled."""
    e = c.execute("SELECT id FROM experiments WHERE result_job_id=?", (job["id"],)).fetchone()
    if not e:
        return
    board = json.loads(job["storyboard"]) if job["storyboard"] else None
    if not board or not board.get("creative"):
        raise Conflict("迭代新版须人工选择风格并准备分镜。")
    if not c.execute(
        "SELECT 1 FROM experiment_styles WHERE experiment_id=? AND job_id=? AND board_revision=? AND board_hash=? AND style_id=?",
        (e["id"], job["id"], job["storyboard_revision"], sha(board), board["creative"]["style_id"]),
    ).fetchone():
        raise Conflict("请在创意迭代页人工确认新版当前分镜的风格；修改分镜后须重新确认。")


class Experiments:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.reviews = Reviews(root, store)
        self.customers = Customers(root, store)

    def row(self, c, eid):
        identifier(eid)
        row = c.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        if not row:
            raise KeyError(eid)
        return dict(row)

    def public(self, c, row):
        proposal = json.loads(row["payload"])
        if sha(proposal) != row["proposal_hash"]:
            raise Conflict("创意提案内容校验失败。")
        evaluations = []
        for r in c.execute(
            "SELECT * FROM experiment_evaluations WHERE experiment_id=? ORDER BY created_at,id",
            (row["id"],),
        ):
            p = json.loads(r["payload"])
            if sha(p) != r["evaluation_hash"]:
                raise Conflict("对比证据校验失败。")
            evaluations.append(
                {
                    "id": r["id"],
                    "evaluation_hash": r["evaluation_hash"],
                    "created_at": r["created_at"],
                    **p,
                }
            )
        return {
            k: row[k]
            for k in (
                "id",
                "status",
                "revision",
                "proposal_hash",
                "result_job_id",
                "result_script_draft_id",
                "created_at",
                "updated_at",
            )
        } | {
            "proposal": proposal,
            "events": [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in c.execute(
                    "SELECT seq,type,actor,payload,created_at FROM experiment_events WHERE experiment_id=? ORDER BY seq",
                    (row["id"],),
                )
            ],
            "evaluations": evaluations,
            "styles": [
                dict(r)
                for r in c.execute(
                    "SELECT job_id,board_revision,board_hash,style_id,actor,created_at FROM experiment_styles WHERE experiment_id=? ORDER BY created_at,id",
                    (row["id"],),
                )
            ],
        }

    def get(self, eid):
        with self.store.connect() as c:
            c.execute("BEGIN")
            return self.public(c, self.row(c, eid))

    def export(self, eid):
        return encode(self.get(eid)).encode()

    def listing(self, review_id=None):
        if review_id:
            identifier(review_id)
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,review_id,material_id,parent_job_id,result_job_id,status,revision,created_at FROM experiments"
                    + (" WHERE review_id=?" if review_id else "")
                    + " ORDER BY created_at DESC,id DESC LIMIT 50",
                    (review_id,) if review_id else (),
                )
            ]

    def event(self, c, eid, kind, cmd, payload=None):
        if (
            c.execute(
                "SELECT count(*) FROM experiment_events WHERE experiment_id=?", (eid,)
            ).fetchone()[0]
            >= 500
        ):
            raise ValueError("单个迭代最多 500 条事件，请新建提案。")
        c.execute(
            "INSERT INTO experiment_events(experiment_id,type,actor,payload,created_at) VALUES(?,?,?,?,?)",
            (eid, kind, cmd.actor, encode(payload or cmd.model_dump()), time.time()),
        )

    def replay(self, c, eid, op, cmd):
        old = c.execute(
            "SELECT * FROM experiment_commands WHERE request_id=?", (cmd.request_id,)
        ).fetchone()
        if old:
            if (
                old["operation"] != op
                or (eid and old["experiment_id"] != eid)
                or old["command_hash"] != sha(cmd.model_dump())
            ):
                raise Conflict("request_id 已用于其他操作或内容，请使用新标识。")
            return json.loads(old["result"])
        return None

    def record(self, c, eid, op, cmd):
        result = self.public(c, self.row(c, eid))
        c.execute(
            "INSERT INTO experiment_commands VALUES(?,?,?,?,?,?)",
            (cmd.request_id, eid, op, sha(cmd.model_dump()), encode(result), time.time()),
        )
        return result

    def guard(self, c, eid, cmd):
        e = self.row(c, eid)
        if e["revision"] != cmd.expected_revision:
            raise Conflict("创意迭代已更新，请重新载入当前版本。")
        return e

    def check_basis(self, c, e):
        p = json.loads(e["payload"])
        if state(c, p["product_id"], p["parent_job_id"]) != p["base_state"]:
            raise Conflict("父版本、事实、文稿、素材或配音已变化；旧变更集已过期。")
        return p

    def change(self, c, eid, status, **fields):
        c.execute(
            "UPDATE experiments SET status=?,revision=revision+1,updated_at=?"
            + "".join("," + k + "=?" for k in fields)
            + " WHERE id=?",
            (status, time.time(), *fields.values(), eid),
        )

    def context(self, review_id, material_id):
        frozen = self.reviews.get(review_id)
        material = next(
            (m for m in frozen["snapshot"]["materials"] if m["material_id"] == material_id), None
        )
        binding = material and material.get("binding")
        if not binding:
            raise ValueError("此冻结素材尚未关联可用父成片。")
        with self.store.connect() as c:
            c.execute("BEGIN")
            version = c.execute(
                "SELECT product_id FROM customer_jobs WHERE job_id=?", (binding["job_id"],)
            ).fetchone()
            if not version:
                raise ValueError("旧成片没有客户商品项目归属，请先在客户制作流程建立可追溯版本。")
            basis = state(c, version["product_id"], binding["job_id"])
            job = dict(c.execute("SELECT * FROM jobs WHERE id=?", (binding["job_id"],)).fetchone())
            snapshot = json.loads(job["snapshot"])
            feature = material.get("creative_feature")
            if (
                material["binding_status"] != "bound"
                or not feature
                or feature["input_snapshot_hash"] != sha(snapshot)
            ):
                raise Conflict("冻结复盘与当前父成片提交版本不一致。")
            video = c.execute(
                "SELECT sha256 FROM artifacts WHERE job_id=? AND kind='video'", (job["id"],)
            ).fetchone()
            if not video or video[0] != binding["video_sha256"]:
                raise Conflict("父成片登记哈希与冻结复盘不一致。")
            board = json.loads(job["storyboard"])
            return {
                "review_id": review_id,
                "review_hash": frozen["snapshot_hash"],
                "account_id": frozen["snapshot"]["account"]["id"],
                "material_id": material_id,
                "parent_job_id": job["id"],
                "product_id": version["product_id"],
                "base_state": basis,
                "shots": board["shots"],
                "style_id": board["creative"]["style_id"],
                "submitted_script": job["script"],
                "facts": snapshot["provenance"]["facts"],
                "scenes": snapshot["provenance"]["scenes"],
            }

    def create(self, value):
        cmd = parse(Proposal, value)
        if not enabled():
            raise ValueError("创意迭代未启用。")
        with self.store.connect() as c:
            prior = self.replay(c, None, "create", cmd)
            if prior:
                return prior
        ctx = self.context(cmd.review_id, cmd.material_id)
        if ctx["parent_job_id"] != cmd.parent_job_id:
            raise Conflict("父成片不属于选定冻结素材。")
        if cmd.change_set.kind == "visual" and cmd.change_set.shot_id not in {
            s["shot_id"] for s in ctx["shots"]
        }:
            raise ValueError("变更镜头不属于父成片。")
        if cmd.change_set.kind == "script":
            from .generation import validate_scenes

            validate_scenes([s.model_dump() for s in cmd.change_set.scenes], ctx["facts"])
        proposal = {
            **cmd.model_dump(exclude_none=True),
            **{k: ctx[k] for k in ("product_id", "review_hash", "account_id", "base_state")},
            "causal_inference": False,
            "hypothesis_status": "unverified_human_proposal",
        }
        eid, now = uuid.uuid4().hex, time.time()
        with self.store.transaction() as c:
            prior = self.replay(c, None, "create", cmd)
            if prior:
                return prior
            if state(c, ctx["product_id"], cmd.parent_job_id) != ctx["base_state"]:
                raise Conflict("项目输入已变化，请重新提出假设。")
            c.execute(
                "INSERT INTO experiments VALUES(?,?,?,?,?,?,?,'proposed',0,NULL,NULL,?,?)",
                (
                    eid,
                    cmd.review_id,
                    ctx["product_id"],
                    cmd.parent_job_id,
                    cmd.material_id,
                    sha(proposal),
                    encode(proposal),
                    now,
                    now,
                ),
            )
            self.event(c, eid, "proposed", cmd)
            return self.record(c, eid, "create", cmd)

    def select(self, eid, value):
        cmd = parse(Select, value)
        return self.simple(eid, "select", cmd, self._select)

    def simple(self, eid, op, cmd, handler):
        if not enabled():
            raise ValueError("创意迭代未启用。")
        with self.store.transaction() as c:
            old = self.replay(c, eid, op, cmd)
            if old:
                return old
            e = self.guard(c, eid, cmd)
            handler(c, e, cmd)
            return self.record(c, eid, op, cmd)

    def _select(self, c, e, cmd):
        if e["status"] != "proposed":
            raise Conflict("只有待选择提案可以选择或拒绝。")
        if cmd.decision == "selected":
            self.check_basis(c, e)
        self.change(c, e["id"], cmd.decision)
        self.event(c, e["id"], cmd.decision, cmd)

    def apply(self, eid, value):
        cmd = parse(Action, value)
        if not enabled():
            raise ValueError("创意迭代未启用。")
        with self.store.connect() as c:
            old = self.replay(c, eid, "apply", cmd)
            if old:
                return old
            e = self.guard(c, eid, cmd)
            if e["status"] != "selected":
                raise Conflict("请先由人工选择此提案；每个提案只应用一次。")
            p = self.check_basis(c, e)
        service = self

        class Receipt:
            def guard(self, c):
                if service.replay(c, eid, "apply", cmd):
                    raise Replay
                current = service.guard(c, eid, cmd)
                if current["status"] != "selected":
                    raise Conflict("提案状态已变化。")
                service.check_basis(c, current)

            def __call__(self, c, result):
                script = p["change_set"]["kind"] == "script"
                if not script:
                    # Visual revisions may inherit timestamps, but P16 requires a new listening check.
                    c.execute(
                        "UPDATE alignments SET status='needs_review',reviewer=NULL,updated_at=? WHERE job_id=? AND status='confirmed'",
                        (time.time(), result),
                    )
                service.change(
                    c,
                    eid,
                    "draft_created",
                    **{("result_script_draft_id" if script else "result_job_id"): result},
                )
                service.event(
                    c,
                    eid,
                    "script_draft_created" if script else "visual_draft_created",
                    cmd,
                    {
                        "result_id": result,
                        "parent_job_id": p["parent_job_id"],
                        "review_id": p["review_id"],
                        "human_gates_required": [
                            "script" if script else "style",
                            "listening_if_narrated",
                            "film_review",
                        ],
                    },
                )
                service.record(c, eid, "apply", cmd)

        try:
            if p["change_set"]["kind"] == "visual":
                self.customers.revise(
                    p["product_id"],
                    {
                        "request_id": "p16-" + eid,
                        "revision": p["base_state"]["project_revision"],
                        "job_id": p["parent_job_id"],
                        "board_revision": p["base_state"]["parent_board_revision"],
                        "shot_id": p["change_set"]["shot_id"],
                        "changes": p["change_set"]["changes"],
                    },
                    receipt=Receipt(),
                )
            else:
                Products(self.store).save_draft(
                    p["product_id"],
                    p["base_state"]["product_revision"],
                    p["change_set"]["scenes"],
                    "experiment_human_proposal",
                    receipt=Receipt(),
                )
        except (Replay, Conflict):
            with self.store.connect() as c:
                prior = self.replay(c, eid, "apply", cmd)
            if prior:
                return prior
            raise
        with self.store.connect() as c:
            return self.replay(c, eid, "apply", cmd)

    def attach(self, eid, value):
        return self.simple(eid, "attach", parse(Attach, value), self._attach)

    def _attach(self, c, e, cmd):
        p = json.loads(e["payload"])
        if e["status"] != "draft_created" or not e["result_script_draft_id"] or e["result_job_id"]:
            raise Conflict("只有待交接的新稿件可以关联一个新版草稿。")
        j = dict(self.store._row(c, cmd.job_id))
        if j["status"] != "draft" or j["id"] == p["parent_job_id"]:
            raise Conflict("请选择该新稿件确认后准备的当前草稿。")
        version = c.execute(
            "SELECT product_id FROM customer_jobs WHERE job_id=?", (j["id"],)
        ).fetchone()
        if not version or version[0] != p["product_id"]:
            raise Conflict("新版不属于同一个商品项目。")
        prov = json.loads(j["provenance"]) if j["provenance"] else {}
        prod = c.execute("SELECT * FROM products WHERE id=?", (p["product_id"],)).fetchone()
        if (
            (prov.get("script_approval") or {}).get("draft_id") != e["result_script_draft_id"]
            or prod["current_draft_id"] != e["result_script_draft_id"]
            or prod["current_review_id"] != p["base_state"]["facts_review_id"]
        ):
            raise Conflict("必须重新确认本提案的新稿件，事实变化则须重建提案。")
        # A prepared draft may not have a board yet; verify the customer version fingerprints.
        project = c.execute(
            "SELECT active_job_id FROM customer_projects WHERE product_id=?", (p["product_id"],)
        ).fetchone()
        if project[0] != j["id"] or prod["status"] != "script_confirmed":
            raise Conflict("新版不是当前已确认稿件的制作版本。")
        version = c.execute("SELECT * FROM customer_jobs WHERE job_id=?", (j["id"],)).fetchone()
        project_row = c.execute(
            "SELECT * FROM customer_projects WHERE product_id=?", (p["product_id"],)
        ).fetchone()
        current = {
            "settings": json.loads(project_row["settings"]),
            "product": dict(prod),
            "media": [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM customer_media WHERE product_id=? ORDER BY rowid",
                    (p["product_id"],),
                )
            ],
        }
        from .media_analysis import attach

        attach(c, current["media"])
        if version["input_fingerprint"] != Customers.fingerprint(current):
            raise Conflict("新版准备后素材或输入已变化，请重新准备再关联。")
        c.execute("UPDATE jobs SET parent_id=? WHERE id=?", (p["parent_job_id"], j["id"]))
        c.execute(
            "UPDATE alignments SET status='needs_review',reviewer=NULL WHERE job_id=? AND status='confirmed'",
            (j["id"],),
        )
        self.change(c, e["id"], "draft_created", result_job_id=j["id"])
        self.event(c, e["id"], "script_version_attached", cmd)

    def style_confirm(self, eid, value):
        return self.simple(eid, "style", parse(Style, value), self._style)

    def _style(self, c, e, cmd):
        if e["result_job_id"] != cmd.job_id or e["status"] != "draft_created":
            raise Conflict("请选择此提案关联的新版草稿。")
        j = self.store._row(c, cmd.job_id)
        board = json.loads(j["storyboard"]) if j["storyboard"] else None
        if (
            j["status"] != "draft"
            or j["storyboard_revision"] != cmd.board_revision
            or not board
            or not board.get("creative")
            or board["creative"]["style_id"] != cmd.style_id
        ):
            raise Conflict("当前分镜或风格已变化，请重新载入并核对。")
        validate_customer_submission(c, j)
        c.execute(
            "INSERT INTO experiment_styles VALUES(?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                e["id"],
                j["id"],
                cmd.board_revision,
                sha(board),
                cmd.style_id,
                cmd.actor,
                time.time(),
            ),
        )
        self.change(c, e["id"], e["status"])
        self.event(c, e["id"], "style_confirmed", cmd)

    def ready(self, c, e):
        if not e["result_job_id"]:
            raise Conflict("尚未关联新版制作任务。")
        j = self.store._row(c, e["result_job_id"])
        if (
            j["status"] != "ready"
            or not c.execute(
                "SELECT 1 FROM reviews WHERE job_id=? AND decision='ready'", (j["id"],)
            ).fetchone()
        ):
            raise Conflict("新版须先通过现有成片人工审核。")
        return j

    def await_data(self, eid, value):
        return self.simple(eid, "await", parse(Action, value), self._await)

    def _await(self, c, e, cmd):
        if e["status"] != "draft_created":
            raise Conflict("当前状态不能转入等待数据。")
        self.ready(c, e)
        self.change(c, e["id"], "awaiting_data")
        self.event(c, e["id"], "awaiting_customer_data_not_placement_receipt", cmd)

    def evaluate(self, eid, value):
        return self.simple(eid, "evaluate", parse(Evaluate, value), self._evaluate)

    def _evaluate(self, c, e, cmd):
        if e["status"] not in ("draft_created", "awaiting_data", "evaluated"):
            raise Conflict("请先创建、关联并审核新版。")
        self.ready(c, e)
        if (
            c.execute(
                "SELECT count(*) FROM experiment_evaluations WHERE experiment_id=?", (e["id"],)
            ).fetchone()[0]
            >= 100
        ):
            raise ValueError("单个迭代最多保存 100 份评估，请新建提案。")
        p = json.loads(e["payload"])
        baseline = self.reviews.public(self.reviews.row(c, p["review_id"]))
        later = self.reviews.public(self.reviews.row(c, cmd.next_review_id))
        if baseline["snapshot_hash"] != p["review_hash"]:
            raise Conflict("基准快照哈希不一致。")
        if later["snapshot"]["account"]["id"] != p["account_id"]:
            raise Conflict("下一轮快照属于其他账户，不允许混比。")
        before = next(
            m for m in baseline["snapshot"]["materials"] if m["material_id"] == p["material_id"]
        )
        after = next(
            (m for m in later["snapshot"]["materials"] if m["material_id"] == cmd.new_material_id),
            None,
        )
        j = c.execute(
            "SELECT product_id FROM customer_jobs WHERE job_id=?", (e["result_job_id"],)
        ).fetchone()
        if not j or j[0] != p["product_id"]:
            raise Conflict("新版不属于原商品，不允许跨商品比较。")
        result = compare(p, baseline, later, before, after, e["result_job_id"], cmd.new_material_id)
        result.update(
            actor=cmd.actor, experiment_id=e["id"], algorithm_version="frozen-descriptive-v1"
        )
        c.execute(
            "INSERT INTO experiment_evaluations VALUES(?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                e["id"],
                cmd.next_review_id,
                sha(result),
                encode(result),
                time.time(),
            ),
        )
        self.change(
            c,
            e["id"],
            "evaluated" if result["status"] == "descriptive_available" else "awaiting_data",
        )
        self.event(
            c,
            e["id"],
            "evaluation_recorded",
            cmd,
            {"evaluation_hash": sha(result), "status": result["status"], "causal_inference": False},
        )


def compare(proposal, baseline, later, before, after, child, material_id):
    """Deterministic arithmetic only. Availability checks are not causal identification."""
    a, b = baseline["snapshot"], later["snapshot"]
    reasons = []
    keys = [
        "basis_id",
        "algorithm_version",
        "currency",
        "timezone",
        "number_encoding",
        "rounding",
        "definitions",
    ]
    if any(a["metric_contract"].get(k) != b["metric_contract"].get(k) for k in keys):
        reasons.append("metric_contract_mismatch")
    wa, wb = (
        a["metric_contract"].get("attribution_window"),
        b["metric_contract"].get("attribution_window"),
    )
    if not wa or not wb:
        reasons.append("attribution_window_unknown")
    elif wa != wb:
        reasons.append("attribution_window_mismatch")
    if not a["aggregation_allowed"] or not b["aggregation_allowed"]:
        reasons.append("incompatible_source_context")
    if b["start_date"] <= a["end_date"] or baseline["review_id"] == later["review_id"]:
        reasons.append("next_window_not_after_baseline")
    lengths = [
        (date.fromisoformat(s["end_date"]) - date.fromisoformat(s["start_date"])).days + 1
        for s in (a, b)
    ]
    if lengths[0] != lengths[1]:
        reasons.append("unequal_window_lengths")
    if material_id == proposal["material_id"]:
        reasons.append("same_material_id")
    if (
        not after
        or not after.get("binding")
        or after["binding"]["job_id"] != child
        or after["binding_status"] != "bound"
    ):
        reasons.append("variant_binding_missing_or_mismatched")
        after = None  # Unverified or other-version values are not this variant's performance.
    for label, m in [("baseline", before), ("next", after)]:
        if not m:
            reasons.append(label + "_material_missing")
            continue
        if m["missing_dates"]:
            reasons.append(label + "_material_days_missing")
        if m["reported_days"] < proposal["comparison_policy"]["min_reported_days"]:
            reasons.append(label + "_reported_days_below_policy")
        impressions = m["interval_totals"]["impressions"]
        if (
            impressions is None
            or Decimal(impressions) < proposal["comparison_policy"]["min_impressions"]
        ):
            reasons.append(label + "_impressions_unknown_or_below_policy")
    metric = proposal["target_metric"]
    values = [
        None if m is None else (m["interval_totals"] | m["interval_ratios"]).get(metric)
        for m in (before, after)
    ]
    if any(v is None for v in values):
        reasons.append("target_metric_missing_or_zero_denominator")
    delta, relative = None, None
    if not reasons:
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            av, bv = map(Decimal, values)
            delta = format((bv - av).quantize(Decimal("0.000001")), "f")
            if av != 0:
                relative = format(((bv - av) / abs(av)).quantize(Decimal("0.000001")), "f")
    return {
        "status": "insufficient_evidence" if reasons else "descriptive_available",
        "reasons": reasons,
        "baseline": {
            "review_id": baseline["review_id"],
            "snapshot_hash": baseline["snapshot_hash"],
            "material_id": proposal["material_id"],
            "job_id": proposal["parent_job_id"],
            "value": values[0],
            "metric_contract": a["metric_contract"],
        },
        "next": {
            "review_id": later["review_id"],
            "snapshot_hash": later["snapshot_hash"],
            "material_id": material_id,
            "job_id": child,
            "value": values[1],
            "metric_contract": b["metric_contract"],
        },
        "target_metric": metric,
        "absolute_difference": delta,
        "relative_difference": relative,
        "relative_difference_status": "unknown_zero_baseline"
        if not reasons and Decimal(values[0]) == 0
        else "available"
        if relative is not None
        else "not_computed",
        "comparison_policy": proposal["comparison_policy"],
        "causal_inference": False,
        "winner": None,
        "limitations": [
            "描述性观察，不是随机实验；曝光/人群/计划/日期差异未控制。",
            "可计算差值不代表创意导致变化，不判断胜出或调整预算。",
            "指标和归因窗口来自导入声明，未向平台独立核准。",
        ],
    }
