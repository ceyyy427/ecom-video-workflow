"""Read-only live matching diagnostic; wrappers record, never alter model results."""

import json
from pathlib import Path

import httpx

from ecom_video import clip_matching
from ecom_video.customer_planner import plan_board

out = Path("docs/evidence/p10/flask-match-probe.json")
p = httpx.get(
    "http://127.0.0.1:8765/api/customer-projects/c2fd93388a19440baac13e1634af7de9", trust_env=False
).json()
original = clip_matching.rank
record = {}


def captured(lines, pool, model):
    record.update(lines=lines, pool=pool, model=model)
    ranks = original(lines, pool, model)
    record["rankings"] = ranks
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(ranks, ensure_ascii=False), flush=True)
    return ranks


clip_matching.rank = captured
try:
    board = plan_board(p["job"], p["settings"], "social", p["alignment"])
    record["plan"] = board
except Exception as e:
    record["error"] = str(e)
    print(str(e), flush=True)
finally:
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2))
