"""Fixed, bounded local production coordinator. Human gates are never tools."""

import json
import threading
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from .agent_contracts import ERRORS, Problem
from .agent_guard import scope
from .agent_runtime_contracts import Control, StyleChoice, execution_enabled
from .agent_service import encoded, validate_id
from .creative import signature
from .customer import Customers
from .db import Conflict
from .maintenance_lock import worker_guard
from .resource_leases import Lease

TERMINAL = {"completed", "failed", "cancelled", "unknown"}


def input_identity(p):
    return signature(
        {
            "settings": p["settings"],
            "review": p["product"]["current_review_id"],
            "draft": p["product"]["current_draft_id"],
            "media": [
                {k: a[k] for k in ("id", "sha256", "kind", "role", "source_in", "note")}
                for a in p["media"]
            ],
        }
    )


def build_plan(p, policy):
    plan = {
        "project_id": p["id"],
        "project_revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "input_hash": input_identity(p),
        "job_id": p["job"]["id"] if p["job"] else None,
        "board_revision": p["job"]["storyboard_revision"] if p["job"] else None,
        "policy": policy,
        "steps": [
            "recognize",
            "prepare",
            "human_style",
            "local_align",
            "human_listen",
            "select_and_plan",
            "render",
            "human_film_review",
        ],
    }
    return {**plan, "plan_hash": signature(plan)}


def create_execution(c, rid, plan, now):
    c.execute(
        "INSERT INTO agent_executions(run_id,status,plan_hash,policy,project_id,project_revision,product_revision,input_hash,job_id,board_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rid,
            "proposed",
            plan["plan_hash"],
            encoded(plan["policy"]),
            plan["project_id"],
            plan["project_revision"],
            plan["product_revision"],
            plan["input_hash"],
            plan["job_id"],
            plan["board_revision"],
            now,
            now,
        ),
    )


class Busy(Exception):
    pass


class Runtime:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.customers = Customers(root, store)

    def row(self, c, rid):
        r = c.execute("SELECT * FROM agent_executions WHERE run_id=?", (rid,)).fetchone()
        if not r:
            raise Problem("NOT_FOUND")
        return dict(r)

    def event(self, c, rid, kind, payload):
        c.execute(
            "INSERT INTO agent_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
            (rid, kind, encoded(payload), time.time()),
        )

    def get(self, rid):
        validate_id(rid)
        with self.store.connect() as c:
            e = self.row(c, rid)
            steps = [
                dict(x)
                for x in c.execute(
                    "SELECT step_key,status,attempts,started_at,finished_at,error FROM agent_steps WHERE run_id=? ORDER BY started_at,step_key",
                    (rid,),
                )
            ]
            choice = c.execute(
                "SELECT style_id,direction_basis,reviewer,created_at FROM agent_choices WHERE run_id=?",
                (rid,),
            ).fetchone()
        return {
            k: e[k]
            for k in (
                "run_id",
                "revision",
                "status",
                "plan_hash",
                "project_id",
                "job_id",
                "board_revision",
                "waiting_for",
                "steps_used",
                "deadline",
                "created_at",
                "updated_at",
            )
        } | {
            "policy": json.loads(e["policy"]),
            "error": json.loads(e["error"]) if e["error"] else None,
            "usage": {"model_calls": e["model_calls"], "cloud_calls": 0, "platform_writes": 0},
            "steps": steps,
            "style_choice": dict(choice) if choice else None,
            "inflight_step": bool(
                e["lease_token"] and e["lease_until"] and e["lease_until"] > time.time()
            ),
        }

    def validate(self, e, p=None):
        p = p or self.customers.get(e["project_id"])
        if (
            p["revision"] != e["project_revision"]
            or p["product"]["revision"] != e["product_revision"]
            or input_identity(p) != e["input_hash"]
        ):
            raise Problem("STALE_INPUT")
        if e["job_id"] and (
            not p["job"]
            or p["job"]["id"] != e["job_id"]
            or p["job"]["storyboard_revision"] != e["board_revision"]
        ):
            raise Problem("STALE_INPUT")
        return p

    def validate_rows(self, c, e):
        p = c.execute(
            "SELECT revision,active_job_id FROM customer_projects WHERE product_id=?",
            (e["project_id"],),
        ).fetchone()
        product = c.execute(
            "SELECT revision FROM products WHERE id=?", (e["project_id"],)
        ).fetchone()
        if (
            not p
            or not product
            or p["revision"] != e["project_revision"]
            or product["revision"] != e["product_revision"]
        ):
            raise Problem("STALE_INPUT")
        if e["job_id"]:
            j = c.execute(
                "SELECT storyboard_revision FROM jobs WHERE id=?", (e["job_id"],)
            ).fetchone()
            if (
                p["active_job_id"] != e["job_id"]
                or not j
                or j["storyboard_revision"] != e["board_revision"]
            ):
                raise Problem("STALE_INPUT")

    def parsed(self, model, value):
        try:
            return model.model_validate(value)
        except ValidationError:
            raise Problem("INVALID_INPUT") from None

    def bound(self, e, command):
        if (
            command.plan_hash != e["plan_hash"]
            or command.policy_id != json.loads(e["policy"])["policy_id"]
        ):
            raise Problem("STALE_INPUT")

    def control(self, rid, action, value):
        validate_id(rid)
        if action not in ("execute", "resume", "pause", "cancel"):
            raise Problem("INVALID_INPUT")
        if not execution_enabled() and action not in ("cancel", "pause"):
            raise Problem("AGENT_DISABLED")
        cmd = self.parsed(Control, value)
        with self.store.transaction() as c:
            e = self.row(c, rid)
            self.bound(e, cmd)
            # Retrying a successful control with its prior revision is a no-op.
            target = {
                "execute": "queued",
                "resume": "queued",
                "pause": "paused",
                "cancel": "cancelled",
            }[action]
            if (action == "execute" and e["status"] != "proposed" and cmd.revision == 0) or (
                e["status"] == target and cmd.revision in (e["revision"], e["revision"] - 1)
            ):
                return self.get(rid)
            if cmd.revision != e["revision"]:
                raise Problem("STALE_INPUT")
            if e["status"] in TERMINAL:
                raise Problem("DOMAIN_REJECTED")
            if action == "pause" and e["status"] == "proposed":
                raise Problem("DOMAIN_REJECTED")
            if action in ("execute", "resume"):
                self.validate(e)
                if action == "execute" and e["status"] != "proposed":
                    raise Problem("DOMAIN_REJECTED")
                if action == "resume" and e["status"] not in ("paused", "waiting_human"):
                    raise Problem("DOMAIN_REJECTED")
                if (
                    action == "resume"
                    and e["lease_token"]
                    and e["lease_until"]
                    and e["lease_until"] > time.time()
                ):
                    raise Problem("DOMAIN_REJECTED")
                if e["deadline"] and time.time() >= e["deadline"]:
                    raise Problem("DEADLINE_EXCEEDED")
            if action == "cancel":
                self.cancel_children(c, rid)
                c.execute(
                    "UPDATE agent_steps SET status='cancelled',finished_at=? WHERE run_id=? AND status='running'",
                    (time.time(), rid),
                )
            deadline = e["deadline"]
            if action == "execute":
                deadline = time.time() + json.loads(e["policy"])["max_elapsed_s"]
            c.execute(
                "UPDATE agent_executions SET status=?,revision=revision+1,waiting_for=?,deadline=?,lease_token=?,lease_until=?,updated_at=? WHERE run_id=?",
                (
                    target,
                    e["waiting_for"] if action == "pause" else None,
                    deadline,
                    e["lease_token"] if action == "pause" else None,
                    e["lease_until"] if action == "pause" else None,
                    time.time(),
                    rid,
                ),
            )
            self.event(c, rid, "execution_" + action, {"status": target})
        return self.get(rid)

    def choose(self, rid, value):
        validate_id(rid)
        cmd = self.parsed(StyleChoice, value)
        if not execution_enabled():
            raise Problem("AGENT_DISABLED")
        if not cmd.reviewer.strip():
            raise Problem("INVALID_INPUT")
        with self.store.transaction() as c:
            e = self.row(c, rid)
            self.bound(e, cmd)
            if e["status"] in TERMINAL or cmd.revision != e["revision"]:
                raise Problem("STALE_INPUT")
            p = self.validate(e)
            if (
                not p["recommendations"]
                or p["direction_basis"] != cmd.direction_basis
                or cmd.style_id not in {s["id"] for s in p["recommendations"]["options"]}
            ):
                raise Problem("STALE_INPUT")
            if (
                p["job"]
                and p["job"]["storyboard"]
                and p["job"]["storyboard"]["creative"]["style_id"] != cmd.style_id
            ):
                raise Problem("STALE_INPUT")
            c.execute(
                "INSERT INTO agent_choices VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET style_id=excluded.style_id,direction_basis=excluded.direction_basis,reviewer=excluded.reviewer,created_at=excluded.created_at",
                (rid, cmd.style_id, cmd.direction_basis, cmd.reviewer, time.time()),
            )
            c.execute(
                "UPDATE agent_executions SET revision=revision+1,updated_at=? WHERE run_id=?",
                (time.time(), rid),
            )
            self.event(
                c,
                rid,
                "human_style_selected",
                {"style_id": cmd.style_id, "direction_basis": cmd.direction_basis},
            )
            from .delivery_reviews import record_agent_direction

            record_agent_direction(c, self.store, p, cmd.style_id, cmd.reviewer)
        return self.get(rid)

    def cancel_children(self, c, rid):
        for kind, tid in c.execute(
            "SELECT DISTINCT target_kind,target_id FROM agent_effects WHERE run_id=? AND owned=1",
            (rid,),
        ).fetchall():
            if kind == "analysis":
                c.execute(
                    "UPDATE media_analyses SET status='cancelled',lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND status IN ('queued','running')",
                    (time.time(), tid),
                )
            elif kind == "alignment":
                c.execute(
                    "UPDATE alignments SET status='failed',error='Agent 运行已停止',updated_at=? WHERE id=? AND status='running'",
                    (time.time(), tid),
                )
            elif kind == "job":
                j = c.execute("SELECT status FROM jobs WHERE id=?", (tid,)).fetchone()
                if j and j["status"] in ("draft", "queued", "validating", "rendering", "auditing"):
                    c.execute(
                        "UPDATE jobs SET lease_token=NULL,lease_until=NULL,worker_id=NULL WHERE id=?",
                        (tid,),
                    )
                    self.store._event(
                        c,
                        tid,
                        j["status"],
                        "cancelled",
                        "Agent 运行停止；保留已完成产物",
                        time.time(),
                    )

    def finish(self, e, status, waiting=None, code=None):
        with self.store.transaction() as c:
            current = self.row(c, e["run_id"])
            if current["lease_token"] != e["lease_token"] or current["status"] in TERMINAL:
                return
            if current["status"] == "paused":
                c.execute(
                    "UPDATE agent_executions SET lease_token=NULL,lease_until=NULL WHERE run_id=? AND lease_token=?",
                    (e["run_id"], e["lease_token"]),
                )
                return
            error = None
            if code:
                _, stage, msg = ERRORS[code]
                error = encoded(
                    {
                        "code": code,
                        "stage": stage,
                        "safe_message": msg,
                        "retryable": False,
                        "outcome_uncertain": status == "unknown",
                        "evidence_refs": [],
                    }
                )
                self.cancel_children(c, e["run_id"])
                c.execute(
                    "UPDATE agent_steps SET status=?,finished_at=?,error=? WHERE run_id=? AND status='running'",
                    (status, time.time(), code, e["run_id"]),
                )
            changed = (
                current["status"] != status
                or current["waiting_for"] != waiting
                or current["error"] != error
            )
            c.execute(
                "UPDATE agent_executions SET status=?,waiting_for=?,error=?,revision=revision+?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE run_id=?",
                (status, waiting, error, int(changed), time.time(), e["run_id"]),
            )
            if changed:
                self.event(
                    c,
                    e["run_id"],
                    "execution_state",
                    {"status": status, "waiting_for": waiting, "error_code": code},
                )

    def effect(self, rid, key):
        with self.store.connect() as c:
            r = c.execute(
                "SELECT * FROM agent_effects WHERE run_id=? AND step_key=?", (rid, key)
            ).fetchone()
        return dict(r) if r else None

    def begin(self, e, key):
        with self.store.transaction() as c:
            self.fenced(c, e)
            if self.effect(e["run_id"], key):
                return False
            policy = json.loads(e["policy"])
            current = self.row(c, e["run_id"])
            prior = c.execute(
                "SELECT * FROM agent_steps WHERE run_id=? AND step_key=?", (e["run_id"], key)
            ).fetchone()
            if (
                prior
                and prior["status"] == "running"
                and current["model_calls"] > prior["model_calls_at_start"]
            ):
                raise Problem("OUTCOME_UNKNOWN")
            if current["steps_used"] >= policy["max_steps"]:
                raise Problem("BUDGET_EXCEEDED")
            c.execute(
                "UPDATE agent_executions SET steps_used=steps_used+1 WHERE run_id=?", (e["run_id"],)
            )
            c.execute(
                "INSERT INTO agent_steps(run_id,step_key,status,attempts,started_at,model_calls_at_start) VALUES(?,?,'running',1,?,?) ON CONFLICT(run_id,step_key) DO UPDATE SET attempts=attempts+1,started_at=excluded.started_at,model_calls_at_start=excluded.model_calls_at_start,status='running'",
                (e["run_id"], key, time.time(), current["model_calls"]),
            )
            self.event(c, e["run_id"], "step_started", {"step_key": key})
        return True

    def fenced(self, c, e, *, allow_paused=False):
        current = self.row(c, e["run_id"])
        if (
            current["status"] not in (("running", "paused") if allow_paused else ("running",))
            or current["lease_token"] != e["lease_token"]
            or current["lease_until"] <= time.time()
        ):
            raise Conflict("执行租约失效")
        if current["deadline"] <= time.time():
            raise Problem("DEADLINE_EXCEEDED")

    def receipt(self, e, key, kind, owned=True, *, resource=None):
        def commit(c, target, *, owned_override=None, resource_token=None):
            self.fenced(c, e, allow_paused=True)
            effect_owned = owned if owned_override is None else owned_override
            if kind == "alignment" and effect_owned:
                row = self.row(c, e["run_id"])
                if row["model_calls"] >= json.loads(row["policy"])["max_model_calls"]:
                    raise Problem("BUDGET_EXCEEDED")
                c.execute(
                    "UPDATE agent_executions SET model_calls=model_calls+1 WHERE run_id=?",
                    (e["run_id"],),
                )
            if key == "prepare":
                p = c.execute(
                    "SELECT revision FROM customer_projects WHERE product_id=?", (e["project_id"],)
                ).fetchone()
                j = c.execute(
                    "SELECT storyboard_revision FROM jobs WHERE id=?", (target,)
                ).fetchone()
                c.execute(
                    "UPDATE agent_executions SET project_revision=?,job_id=?,board_revision=? WHERE run_id=?",
                    (p["revision"], target, j["storyboard_revision"], e["run_id"]),
                )
            elif key == "plan":
                j = c.execute(
                    "SELECT storyboard_revision FROM jobs WHERE id=?", (target,)
                ).fetchone()
                c.execute(
                    "UPDATE agent_executions SET board_revision=? WHERE run_id=?",
                    (j["storyboard_revision"], e["run_id"]),
                )
            c.execute(
                "INSERT INTO agent_effects VALUES(?,?,?,?,?,?,?)",
                (
                    e["run_id"],
                    key,
                    kind,
                    target,
                    int(effect_owned),
                    encoded({"target_id": target, "resource_token": resource_token}),
                    time.time(),
                ),
            )
            c.execute(
                "UPDATE agent_steps SET status='completed',finished_at=? WHERE run_id=? AND step_key=?",
                (time.time(), e["run_id"], key),
            )
            self.event(
                c,
                e["run_id"],
                "step_committed",
                {"step_key": key, "kind": kind, "target_id": target, "owned": effect_owned},
            )

        def guard(c):
            self.fenced(c, e, allow_paused=True)
            self.validate_rows(c, e)
            if resource:
                resource.guard(c)

        commit.guard = guard
        return commit

    def record_existing(self, e, key, kind, tid):
        if self.begin(e, key):
            with self.store.transaction() as c:
                receipt = self.receipt(e, key, kind, False)
                receipt.guard(c)
                receipt(c, tid)

    def claim(self):
        if not execution_enabled():
            return None
        now = time.time()
        with self.store.transaction() as c:
            # Deadlines apply even while waiting for a person or explicitly paused.
            for x in c.execute(
                "SELECT * FROM agent_executions WHERE deadline<=? AND status NOT IN ('completed','failed','cancelled','unknown')",
                (now,),
            ).fetchall():
                self.cancel_children(c, x["run_id"])
                c.execute(
                    "UPDATE agent_steps SET status='failed',finished_at=?,error='DEADLINE_EXCEEDED' WHERE run_id=? AND status='running'",
                    (now, x["run_id"]),
                )
                err = ERRORS["DEADLINE_EXCEEDED"]
                c.execute(
                    "UPDATE agent_executions SET status='failed',revision=revision+1,error=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE run_id=?",
                    (
                        encoded(
                            {
                                "code": "DEADLINE_EXCEEDED",
                                "stage": err[1],
                                "safe_message": err[2],
                                "retryable": False,
                                "outcome_uncertain": False,
                                "evidence_refs": [],
                            }
                        ),
                        now,
                        x["run_id"],
                    ),
                )
                self.event(
                    c,
                    x["run_id"],
                    "execution_state",
                    {"status": "failed", "error_code": "DEADLINE_EXCEEDED"},
                )
            r = c.execute(
                "SELECT * FROM agent_executions WHERE (status IN ('queued','running') OR (status='waiting_human' AND waiting_for='film_review')) AND (lease_until IS NULL OR lease_until<=?) ORDER BY updated_at LIMIT 1",
                (now,),
            ).fetchone()
            if not r:
                return None
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE agent_executions SET status=CASE WHEN status='waiting_human' THEN status ELSE 'running' END,lease_token=?,lease_until=?,updated_at=? WHERE run_id=?",
                (token, now + 30, now, r["run_id"]),
            )
            return {**dict(r), "status": "running", "lease_token": token, "lease_until": now + 30}

    @worker_guard(lambda self: self.root)
    def tick(self):
        e = self.claim()
        if not e:
            return False
        done = threading.Event()

        def beat():
            while not done.wait(5):
                with self.store.transaction() as c:
                    c.execute(
                        "UPDATE agent_executions SET lease_until=? WHERE run_id=? AND lease_token=? AND status IN ('running','paused')",
                        (time.time() + 30, e["run_id"], e["lease_token"]),
                    )

        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
        try:
            self.advance(e)
        except Busy:
            self.finish(e, "running")
        except Problem as exc:
            self.finish(e, "unknown" if exc.code == "OUTCOME_UNKNOWN" else "failed", code=exc.code)
        except Conflict:
            self.finish(e, "failed", code="STALE_INPUT")
        except Exception:
            self.finish(e, "failed", code="LOCAL_TASK_FAILED")
        finally:
            done.set()
            thread.join(6)
        return True

    def advance(self, e):
        rid = e["run_id"]
        p = self.validate(e)
        if p["product"]["status"] != "script_confirmed":
            return self.finish(e, "waiting_human", "facts_script")
        if not any(a["kind"] != "audio" for a in p["media"]):
            return self.finish(e, "waiting_human", "media")
        if p["settings"]["brief"]["format"] != "showcase" and not any(
            a["role"] == "voice" for a in p["media"]
        ):
            return self.finish(e, "waiting_human", "voice_upload")
        if p["settings"].get("auto_select"):
            from .media_analysis import Analysis

            for a in p["media"]:
                if a["kind"] == "audio":
                    continue
                key = "analysis:" + a["id"]
                effect = self.effect(rid, key)
                if not effect:
                    if self.begin(e, key):
                        prior = a.get("analysis")
                        owned = not (
                            prior
                            and not a["analysis_stale"]
                            and prior["status"] in ("ready", "queued", "running")
                        )
                        Analysis(self.root, self.store).start(
                            p["id"], a["id"], receipt=self.receipt(e, key, "analysis", owned)
                        )
                    return self.finish(e, "running")
                with self.store.connect() as c:
                    child = c.execute(
                        "SELECT * FROM media_analyses WHERE id=?", (effect["target_id"],)
                    ).fetchone()
                if not child:
                    raise Problem("OUTCOME_UNKNOWN")
                if (
                    not a.get("analysis")
                    or a["analysis"]["id"] != child["id"]
                    or a["analysis_stale"]
                ):
                    raise Problem("STALE_INPUT")
                if child["status"] in ("queued", "running"):
                    return self.finish(e, "running")
                if child["status"] != "ready":
                    raise Problem(
                        child["error"]
                        if child["error"] in ("BUDGET_EXCEEDED", "DEADLINE_EXCEEDED")
                        else "LOCAL_TASK_FAILED"
                    )
        if not self.effect(rid, "prepare"):
            owned = not (p["job"] and not p["inputs_changed"])
            if self.begin(e, "prepare"):
                self.customers.prepare(
                    p["id"], p["revision"], receipt=self.receipt(e, "prepare", "job", owned)
                )
            return self.finish(e, "running")
        # Effect receipt and project/job revisions were committed atomically.
        with self.store.connect() as c:
            e = {**self.row(c, rid), "lease_token": e["lease_token"]}
            choice = c.execute("SELECT * FROM agent_choices WHERE run_id=?", (rid,)).fetchone()
        p = self.validate(e)
        job = p["job"]
        if not job:
            raise Problem("OUTCOME_UNKNOWN")
        if not choice:
            return self.finish(e, "waiting_human", "style")
        if choice["direction_basis"] != p["direction_basis"]:
            raise Problem("STALE_INPUT")
        if job["status"] != "draft":
            if job["status"] == "ready":
                return self.finish(e, "completed")
            if job["status"] == "needs_review":
                return self.finish(e, "waiting_human", "film_review")
            if job["status"] in ("failed", "blocked", "rejected", "cancelled"):
                raise Problem("LOCAL_TASK_FAILED")
            return self.finish(e, "running")
        if p["settings"]["brief"]["format"] != "showcase":
            from .alignment import AlignmentService

            align = p["alignment"]
            if not align:
                if not self.effect(rid, "align"):
                    voice = next(
                        a for a in job["assets"] if a["metadata"].get("customer_role") == "voice"
                    )
                    try:
                        AlignmentService(self.root, self.store, recover=False).start(
                            job["id"],
                            voice["id"],
                            receipt=self.receipt(e, "align", "alignment"),
                            before_start=lambda: self.begin(e, "align"),
                        )
                    except Conflict:
                        raise Busy from None
                    return self.finish(e, "running")
                raise Problem("OUTCOME_UNKNOWN")
            if align["status"] == "running":
                effect = self.effect(rid, "align")
                if effect and effect["owned"]:
                    resource_token = json.loads(effect["receipt"]).get("resource_token")
                    with self.store.connect() as c:
                        active = c.execute(
                            "SELECT 1 FROM resource_leases WHERE token=? AND expires_at>?",
                            (resource_token, time.time()),
                        ).fetchone()
                    if not active:
                        raise Problem("OUTCOME_UNKNOWN")
                return self.finish(e, "running")
            if align["status"] != "confirmed":
                return self.finish(
                    e,
                    "waiting_human",
                    "listening" if align["status"] == "needs_review" else "alignment_failed",
                )
        if not job["storyboard"]:
            lease = Lease(self.store)
            if not lease.acquire():
                raise Busy
            lease.keepalive()
            try:
                if self.begin(e, "plan"):
                    with scope(self.store, rid, lease.check):
                        self.customers.plan(
                            p["id"],
                            p["revision"],
                            job["id"],
                            job["storyboard_revision"],
                            choice["style_id"],
                            p["recommendations"]["fingerprint"],
                            p["alignment"]["id"] if p["alignment"] else None,
                            receipt=self.receipt(e, "plan", "job", False, resource=lease),
                        )
                lease.check()
            finally:
                lease.release()
            return self.finish(e, "running")
        if job["storyboard"]["creative"]["style_id"] != choice["style_id"]:
            raise Problem("STALE_INPUT")
        if p["delivery_reviews"]["enabled"] and not p["delivery_reviews"]["storyboard"]:
            return self.finish(e, "waiting_human", "storyboard")
        if not self.effect(rid, "submit") and self.begin(e, "submit"):
            self.customers.submit(
                p["id"],
                p["revision"],
                job["id"],
                job["storyboard_revision"],
                receipt=self.receipt(
                    e, "submit", "job", bool(self.effect(rid, "prepare")["owned"])
                ),
            )
        self.finish(e, "running")
