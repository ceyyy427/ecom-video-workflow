"""Persisted local call admission; no raw prompts or credentials enter receipts."""

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar

from .agent_contracts import Problem
from .db import Conflict

SCOPE = ContextVar("agent_scope", default=None)


@contextmanager
def scope(store, run_id, check=None):
    token = SCOPE.set((store, run_id, check))
    try:
        yield
    finally:
        SCOPE.reset(token)


def admitted(row):
    if row["status"] in ("cancelled", "failed", "unknown", "completed"):
        raise Conflict("Agent 运行已停止")
    if row["deadline"] and time.time() >= row["deadline"]:
        raise Problem("DEADLINE_EXCEEDED")


def reserve_call():
    current = SCOPE.get()
    if not current:
        return
    store, rid, check = current
    if check:
        check()
    with store.transaction() as c:
        row = c.execute("SELECT * FROM agent_executions WHERE run_id=?", (rid,)).fetchone()
        admitted(row)
        if row["model_calls"] >= json.loads(row["policy"])["max_model_calls"]:
            raise Problem("BUDGET_EXCEEDED")
        c.execute("UPDATE agent_executions SET model_calls=model_calls+1 WHERE run_id=?", (rid,))


def request_timeout(timeout):
    current = SCOPE.get()
    if not current:
        return timeout
    store, rid, check = current
    if check:
        check()
    with store.connect() as c:
        row = c.execute("SELECT * FROM agent_executions WHERE run_id=?", (rid,)).fetchone()
    admitted(row)
    return min(timeout, max(0.1, row["deadline"] - time.time()))


def owner(store, kind, target):
    with store.connect() as c:
        r = c.execute(
            "SELECT run_id FROM agent_effects WHERE target_kind=? AND target_id=? AND owned=1 ORDER BY created_at DESC LIMIT 1",
            (kind, target),
        ).fetchone()
    return r["run_id"] if r else None


def check_target(store, kind, target):
    rid = owner(store, kind, target)
    if rid:
        with store.connect() as c:
            admitted(c.execute("SELECT * FROM agent_executions WHERE run_id=?", (rid,)).fetchone())
    return rid
