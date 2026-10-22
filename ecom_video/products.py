"""Versioned product evidence and two explicit human confirmation gates."""

import hashlib
import json
import time
import uuid

from .db import Conflict, validate_script
from .generation import validate_scenes


def uid():
    return uuid.uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def reviewer_fields(reviewer, note):
    reviewer, note = reviewer.strip(), note.strip()
    if not 1 <= len(reviewer) <= 80 or not 1 <= len(note) <= 1000:
        raise ValueError("请填写确认人（最多 80 字）与核对说明（最多 1000 字）")
    return reviewer, note


class Products:
    def __init__(self, store):
        self.store = store

    def _row(self, c, pid, revision=None):
        row = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise KeyError(pid)
        if revision is not None and row["revision"] != revision:
            raise Conflict("资料已更新，请重新载入后核对当前版本")
        return dict(row)

    def _event(self, c, pid, message, status, review, draft):
        now = time.time()
        c.execute(
            "UPDATE products SET status=?,current_review_id=?,current_draft_id=?,revision=revision+1,updated_at=? WHERE id=?",
            (status, review, draft, now, pid),
        )
        c.execute(
            "INSERT INTO product_events(product_id,revision,message,created_at) SELECT id,revision,?,? FROM products WHERE id=?",
            (message, now, pid),
        )

    def create(self, title):
        title = title.strip()
        if not 1 <= len(title) <= 120 or any(ord(c) < 32 for c in title):
            raise ValueError("产品标题须为 1–120 字")
        pid, now = uid(), time.time()
        with self.store.transaction() as c:
            c.execute(
                "INSERT INTO products(id,title,status,created_at,updated_at) VALUES(?,?,'collecting',?,?)",
                (pid, title, now, now),
            )
            self._event(c, pid, "创建产品资料夹", "collecting", None, None)
        return self.get(pid)

    def list(self):
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute("SELECT * FROM products ORDER BY updated_at DESC LIMIT 100")
            ]

    def get(self, pid):
        with self.store.connect() as c:
            product = self._row(c, pid)
            for table, key, json_fields in (
                ("product_sources", "sources", ["extracted"]),
                ("product_facts", "facts", []),
                ("fact_reviews", "fact_reviews", ["fact_ids"]),
                ("script_drafts", "script_drafts", ["payload"]),
                ("product_events", "events", []),
            ):
                product[key] = [
                    dict(r)
                    for r in c.execute(
                        f"SELECT * FROM {table} WHERE product_id=? ORDER BY rowid", (pid,)
                    )
                ]
                for row in product[key]:
                    for field in json_fields:
                        row[field] = json.loads(row[field])
            product["script_approvals"] = [
                dict(r)
                for r in c.execute(
                    "SELECT a.* FROM script_approvals a JOIN script_drafts d ON d.id=a.draft_id WHERE d.product_id=? ORDER BY a.created_at",
                    (pid,),
                )
            ]
        return product

    def add_source(self, pid, revision, source):
        with self.store.transaction() as c:
            self._row(c, pid, revision)
            if (
                c.execute(
                    "SELECT COUNT(*) FROM product_sources WHERE product_id=?", (pid,)
                ).fetchone()[0]
                >= 10
            ):
                raise Conflict("每个产品最多 10 份资料，请新建资料夹")
            c.execute(
                "INSERT INTO product_sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    source["id"],
                    pid,
                    source["kind"],
                    source["file_name"],
                    source.get("original_url"),
                    source.get("final_url"),
                    source["path"],
                    source["sha256"],
                    encoded(source["extracted"]),
                    time.time(),
                ),
            )
            for unit in source["extracted"]["units"]:
                # Only complete short units become candidates. Long text stays available for exact manual quotation.
                if 1 <= len(unit["text"]) <= 100:
                    c.execute(
                        "INSERT INTO product_facts VALUES(?,?,?,?,?,?,?)",
                        (
                            uid(),
                            pid,
                            source["id"],
                            unit["id"],
                            unit["text"],
                            unit["locator"],
                            time.time(),
                        ),
                    )
            self._event(c, pid, "新增资料，需重新确认事实", "collecting", None, None)
        return self.get(pid)

    def add_quote(self, pid, revision, source_id, unit_id, text):
        text = text.strip()
        with self.store.transaction() as c:
            self._row(c, pid, revision)
            source = c.execute(
                "SELECT extracted FROM product_sources WHERE id=? AND product_id=?",
                (source_id, pid),
            ).fetchone()
            if not source:
                raise ValueError("资料不属于当前产品")
            unit = next(
                (u for u in json.loads(source["extracted"])["units"] if u["id"] == unit_id), None
            )
            if not unit or not 1 <= len(text) <= 100 or text not in unit["text"]:
                raise ValueError("引文须为原文中的连续 1–100 字，请保留必要语境")
            c.execute(
                "INSERT OR IGNORE INTO product_facts VALUES(?,?,?,?,?,?,?)",
                (uid(), pid, source_id, unit_id, text, unit["locator"], time.time()),
            )
            self._event(c, pid, "添加事实候选，需重新确认事实", "collecting", None, None)
        return self.get(pid)

    def confirm_facts(self, pid, revision, fact_ids, reviewer, note):
        reviewer, note = reviewer_fields(reviewer, note)
        if not 1 <= len(fact_ids) <= 20 or len(set(fact_ids)) != len(fact_ids):
            raise ValueError("请选择 1–20 条不重复事实")
        with self.store.transaction() as c:
            self._row(c, pid, revision)
            facts = {
                r["id"]: dict(r)
                for r in c.execute("SELECT * FROM product_facts WHERE product_id=?", (pid,))
            }
            if any(i not in facts for i in fact_ids):
                raise ValueError("候选事实不属于当前产品")
            rid = uid()
            c.execute(
                "INSERT INTO fact_reviews VALUES(?,?,?,?,?,?,?)",
                (
                    rid,
                    pid,
                    encoded(fact_ids),
                    sha(encoded([facts[i] for i in fact_ids])),
                    reviewer,
                    note,
                    time.time(),
                ),
            )
            self._event(c, pid, "人工确认产品事实", "facts_confirmed", rid, None)
        return self.get(pid)

    @staticmethod
    def confirmed_facts(product):
        review = next(
            (r for r in product["fact_reviews"] if r["id"] == product["current_review_id"]), None
        )
        if not review:
            raise Conflict("请先人工核对并确认产品事实")
        facts = {f["id"]: f for f in product["facts"]}
        return [facts[i] for i in review["fact_ids"]]

    def save_draft(self, pid, revision, scenes, mode, model=None, *, receipt=None):
        product = self.get(pid)
        scenes = validate_scenes(scenes, self.confirmed_facts(product))
        script = "\n".join(s["text"] for s in scenes)
        validate_script(product["title"], script, 3)
        with self.store.transaction() as c:
            if receipt:
                receipt.guard(c)
            p = self._row(c, pid, revision)
            if p["current_review_id"] != product["current_review_id"]:
                raise Conflict("事实确认版本已变化，请重新生成")
            did = uid()
            c.execute(
                "INSERT INTO script_drafts VALUES(?,?,?,?,?,?,?,?)",
                (
                    did,
                    pid,
                    p["current_review_id"],
                    mode,
                    model,
                    encoded(scenes),
                    sha(script),
                    time.time(),
                ),
            )
            self._event(
                c, pid, "创建脚本版本（待人工确认）", "script_draft", p["current_review_id"], did
            )
            if receipt:
                receipt(c, did)
        return self.get(pid)

    def approve(self, pid, revision, draft_id, reviewer, note, seconds=3):
        reviewer, note = reviewer_fields(reviewer, note)
        product = self.get(pid)
        draft = next((d for d in product["script_drafts"] if d["id"] == draft_id), None)
        if not draft:
            raise ValueError("脚本版本不属于当前产品")
        with self.store.transaction() as c:
            prior = c.execute(
                "SELECT job_id FROM script_approvals WHERE draft_id=?", (draft_id,)
            ).fetchone()
            if prior:
                jid = prior["job_id"]
            else:
                p = self._row(c, pid, revision)
                if (
                    p["current_draft_id"] != draft_id
                    or p["current_review_id"] != draft["facts_review_id"]
                ):
                    raise Conflict("只能确认当前事实版本下的最新脚本")
                facts = self.confirmed_facts(product)
                scenes = validate_scenes(draft["payload"], facts)
                title, script = validate_script(
                    p["title"], "\n".join(s["text"] for s in scenes), seconds
                )
                if sha(script) != draft["script_hash"]:
                    raise Conflict("脚本内容与版本哈希不一致")
                review = next(
                    r for r in product["fact_reviews"] if r["id"] == p["current_review_id"]
                )
                source_ids = {f["source_id"] for f in facts}
                sources = [
                    {k: v for k, v in s.items() if k != "extracted"}
                    for s in product["sources"]
                    if s["id"] in source_ids
                ]
                # Keep full quoted units alongside short facts so excerpts retain their context.
                for source in sources:
                    original = next(s for s in product["sources"] if s["id"] == source["id"])
                    units = {f["unit_id"] for f in facts if f["source_id"] == source["id"]}
                    source["units"] = [
                        u for u in original["extracted"]["units"] if u["id"] in units
                    ]
                jid, aid, now = uid(), uid(), time.time()
                approval = {
                    "id": aid,
                    "draft_id": draft_id,
                    "job_id": jid,
                    "reviewer": reviewer,
                    "note": note,
                    "script_hash": sha(script),
                    "created_at": now,
                }
                provenance = {
                    "schema_version": 1,
                    "product_id": pid,
                    "product_revision": revision,
                    "title": title,
                    "sources": sources,
                    "facts": facts,
                    "fact_review": review,
                    "script_approval": approval,
                    "scenes": scenes,
                    "generation": {"mode": draft["mode"], "model": draft["model"]},
                    "semantic_verification": "human_only",
                }
                from .creative_proposals import current_plan

                plan = current_plan(product)
                if plan:
                    provenance["creative_plan"] = plan
                c.execute(
                    "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at,provenance) VALUES(?,?,?,?,'draft',?,?,?)",
                    (jid, title, script, seconds, now, now, encoded(provenance)),
                )
                c.execute(
                    "INSERT INTO script_approvals VALUES(?,?,?,?,?,?,?)",
                    (aid, draft_id, jid, reviewer, note, sha(script), now),
                )
                self.store._event(c, jid, None, "draft", "已确认产品脚本转入剪辑草稿", now)
                self._event(
                    c,
                    pid,
                    "人工确认脚本并创建剪辑草稿",
                    "script_confirmed",
                    p["current_review_id"],
                    draft_id,
                )
        return self.store.get(jid)
