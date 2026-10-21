"""Short SQLite transactions own state; renderers never hold database locks."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ACTIVE = ("validating", "rendering", "auditing")
LEASE_SECONDS = 45
SCHEMA_VERSION = 14
TRANSITIONS = {
    "validating": {"rendering", "blocked", "failed"},
    "rendering": {"auditing", "failed"},
    "auditing": {"needs_review", "failed"},
}


class Conflict(Exception):
    """The requested operation would violate the persisted job lifecycle."""


def validate_script(title, script, seconds):
    title, script = title.strip(), script.strip()
    lines = [line.strip() for line in script.splitlines() if line.strip()]
    if not title or len(title) > 120:
        raise ValueError("标题须为 1–120 字")
    if not 1 <= len(lines) <= 30 or any(len(line) > 100 for line in lines):
        raise ValueError("脚本须有 1–30 个非空行，每行最多 100 字")
    if len(script) > 3000 or any(ord(c) < 32 and c not in "\n\r\t" for c in script):
        raise ValueError("脚本过长或包含控制字符")
    if not 1 <= seconds <= 15 or len(lines) * seconds > 120:
        raise ValueError("每镜须为 1–15 秒，默认总长不得超过 120 秒")
    return title, "\n".join(lines)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            # SQLite table rebuilds require FK checks disabled outside the transaction.
            # Validate every reference before committing, then restore normal enforcement.
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("BEGIN IMMEDIATE")
            try:
                version = c.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError("数据库版本高于当前程序；请使用匹配版本，禁止自动降级")
                for target, filename in (
                    (1, "001_initial.sql"),
                    (2, "002_products.sql"),
                    (3, "003_distribution.sql"),
                    (4, "004_qianchuan.sql"),
                    (5, "005_storyboard.sql"),
                    (6, "006_creative.sql"),
                    (7, "007_customer.sql"),
                    (8, "008_media_analysis.sql"),
                    (9, "009_agent.sql"),
                    (10, "010_agent_runtime.sql"),
                    (11, "011_review_snapshots.sql"),
                    (12, "012_experiments.sql"),
                    (13, "013_voice_takes.sql"),
                    (14, "014_voice_patches.sql"),
                ):
                    if version >= target:
                        continue
                    sql = (Path(__file__).parent / "migrations" / filename).read_text(
                        encoding="utf-8"
                    )
                    statement = ""
                    for line in sql.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            c.execute(statement)
                            statement = ""
                    c.execute(
                        "INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (target, time.time())
                    )
                    c.execute(f"PRAGMA user_version={target}")
                if c.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise RuntimeError("迁移外键校验失败，已回滚")
                c.commit()
            except BaseException:
                c.rollback()
                raise
            finally:
                c.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def transaction(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def _row(self, c, jid):
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if row is None:
            raise KeyError(jid)
        return dict(row)

    def _event(self, c, jid, old, new, message, now):
        c.execute(
            "INSERT INTO events(job_id,from_status,to_status,message,created_at) VALUES(?,?,?,?,?)",
            (jid, old, new, message, now),
        )
        c.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (new, now, jid))

    def get(self, jid):
        with self.connect() as c:
            j = self._row(c, jid)
            for name in ("snapshot", "audit", "provenance", "storyboard"):
                j[name] = json.loads(j[name]) if j[name] else None
            j["assets"] = [
                dict(x)
                for x in c.execute("SELECT * FROM assets WHERE job_id=? ORDER BY position", (jid,))
            ]
            for a in j["assets"]:
                a["metadata"] = json.loads(a["metadata"])
            for table in ("events", "artifacts", "reviews"):
                j[table] = [
                    dict(x)
                    for x in c.execute(
                        f"SELECT * FROM {table} WHERE job_id=? ORDER BY rowid", (jid,)
                    )
                ]
            return j

    def list_jobs(self):
        with self.connect() as c:
            return [
                dict(x)
                for x in c.execute(
                    "SELECT id,title,status,created_at,updated_at,attempts,error FROM jobs ORDER BY created_at DESC LIMIT 100"
                )
            ]

    def create_job(self, title, script, seconds=3, parent_id=None, provenance=None):
        title, script = validate_script(title, script, seconds)
        jid, now = uuid.uuid4().hex, time.time()
        with self.transaction() as c:
            c.execute(
                "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at,parent_id,provenance) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    jid,
                    title,
                    script,
                    seconds,
                    "draft",
                    now,
                    now,
                    parent_id,
                    json.dumps(provenance, ensure_ascii=False) if provenance else None,
                ),
            )
            self._event(c, jid, None, "draft", "创建草稿", now)
        return self.get(jid)

    def update_draft(self, jid, title, script, seconds):
        title, script = validate_script(title, script, seconds)
        with self.transaction() as c:
            existing = self._row(c, jid)
            if existing["status"] != "draft":
                raise Conflict("脚本已锁定；请复制为新草稿修改")
            if existing["provenance"] and (
                script != existing["script"] or title != existing["title"]
            ):
                raise Conflict("产品脚本已人工确认；请回产品资料夹修改脚本并重新确认")
            if script != existing["script"] or seconds != existing["seconds"]:
                saved = json.loads(existing["storyboard"]) if existing["storyboard"] else None
                rebased = None
                if saved and (saved.get("creative") or saved.get("creative_required")):
                    from .storyboard import rebase_board

                    assets = [
                        dict(a)
                        for a in c.execute(
                            "SELECT * FROM assets WHERE job_id=? ORDER BY position", (jid,)
                        )
                    ]
                    rebased = json.dumps(
                        rebase_board(existing, script, seconds, assets), ensure_ascii=False
                    )
                c.execute(
                    "UPDATE jobs SET storyboard=?,storyboard_revision=storyboard_revision+1 WHERE id=?",
                    (rebased, jid),
                )
            c.execute(
                "UPDATE jobs SET title=?,script=?,seconds=?,updated_at=? WHERE id=?",
                (title, script, seconds, time.time(), jid),
            )
        return self.get(jid)

    def add_asset(self, jid, asset):
        with self.transaction() as c:
            if self._row(c, jid)["status"] != "draft":
                raise Conflict("仅草稿可以修改素材")
            rows = c.execute(
                "SELECT kind,size,position FROM assets WHERE job_id=?", (jid,)
            ).fetchall()
            if sum(a["size"] for a in rows) + asset["size"] > 500 * 1024**2:
                raise Conflict("单任务素材总量不得超过 500 MiB")
            if asset["kind"] == "audio" and sum(a["kind"] == "audio" for a in rows) >= 2:
                raise Conflict("最多两条音频，分别用于配音和背景音乐")
            if asset["kind"] != "audio" and sum(a["kind"] != "audio" for a in rows) >= 30:
                raise Conflict("最多上传 30 个画面素材")
            position = max((r["position"] for r in rows), default=-1) + 1
            c.execute(
                "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    asset["id"],
                    jid,
                    asset["name"],
                    asset["path"],
                    asset["kind"],
                    asset["sha256"],
                    asset["size"],
                    position,
                    json.dumps(asset["metadata"]),
                ),
            )
        return self.get(jid)

    def save_storyboard(self, jid, board, revision):
        from .storyboard import validate_board

        with self.transaction() as c:
            j = self._row(c, jid)
            if j["status"] != "draft" or j["storyboard_revision"] != revision:
                raise Conflict("分镜已更新或任务已锁定，请重新载入")
            j["assets"] = [
                dict(a) for a in c.execute("SELECT * FROM assets WHERE job_id=?", (jid,))
            ]
            normalized = validate_board(j, board)
            prior = json.loads(j["storyboard"]) if j["storyboard"] else {}
            previous = {s.get("shot_id"): s for s in prior.get("shots", []) if s.get("shot_id")}
            for shot in normalized["shots"]:
                old = previous.get(shot.get("shot_id"))
                if (
                    old
                    and shot.get("motion_plan")
                    and (
                        old["asset_id"] != shot["asset_id"] or old["source_in"] != shot["source_in"]
                    )
                ):
                    old_windows = (old.get("motion_plan") or {}).get("windows", [])
                    shot["motion_plan"]["windows"] = [
                        w
                        for w in shot["motion_plan"]["windows"]
                        if w["basis"] == "voice_hint"
                        or (w["basis"] == "manual" and w not in old_windows)
                    ]
            if prior.get("creative") or prior.get("creative_required"):
                normalized["creative_required"] = True
            c.execute(
                "UPDATE jobs SET storyboard=?,storyboard_revision=storyboard_revision+1,updated_at=? WHERE id=?",
                (json.dumps(normalized, ensure_ascii=False), time.time(), jid),
            )
        return self.get(jid)

    def remove_asset(self, jid, aid):
        with self.transaction() as c:
            if self._row(c, jid)["status"] != "draft":
                raise Conflict("仅草稿可以修改素材")
            board = self._row(c, jid)["storyboard"]
            if board:
                b = json.loads(board)
                used = [s["asset_id"] for s in b["shots"]] + [
                    b["music_id"],
                    b["narration"]["asset_id"],
                ]
                if aid in used:
                    raise Conflict("素材已被分镜引用，请先修改并保存分镜")
            row = c.execute(
                "SELECT path FROM assets WHERE id=? AND job_id=?", (aid, jid)
            ).fetchone()
            if not row:
                raise KeyError(aid)
            c.execute("DELETE FROM assets WHERE id=?", (aid,))
            return row["path"]

    def submit(self, jid, guard=None, *, receipt=None):
        with self.transaction() as c:
            if receipt:
                receipt.guard(c)
            j = self._row(c, jid)
            if guard:
                guard(c, j)
            if j["status"] != "draft":
                if j["snapshot"]:
                    return self.get(jid)  # Repeated submit is a no-op, never a retry.
                raise Conflict("当前任务不可提交")
            from .customer import validate_customer_submission

            validate_customer_submission(c, j)
            from .experiments import validate_experiment_submission

            validate_experiment_submission(c, j)
            assets = [
                dict(a)
                for a in c.execute("SELECT * FROM assets WHERE job_id=? ORDER BY position", (jid,))
            ]
            if not any(a["kind"] != "audio" for a in assets):
                raise Conflict("请至少上传一个图片或视频")
            board = None
            alignment = None
            if j["storyboard"]:
                from .storyboard import validate_board

                board = validate_board({**j, "assets": assets}, json.loads(j["storyboard"]))
                from .production import validate_production

                validate_production(board, assets)
                if board.get("creative_required") and not board.get("creative"):
                    raise ValueError("请到创意工作室重新推荐并选定风格；已保留镜头编辑")
                if (
                    board.get("creative")
                    and board["narration"]["mode"] == "uploaded"
                    and not board["creative"].get("alignment_id")
                ):
                    raise ValueError("Remotion 上传配音必须先完成本机对齐并听核确认")
                if board.get("creative") and board["creative"].get("alignment_id"):
                    from .alignment import confirmed_alignment

                    alignment = confirmed_alignment(c, j, assets, board)
            elif sum(a["kind"] == "audio" for a in assets) > 1:
                raise Conflict("多条音频请先保存分镜，指定配音与背景音乐")
            digest = hashlib.sha256(j["script"].encode()).hexdigest()
            provenance = json.loads(j["provenance"]) if j["provenance"] else None
            if provenance and provenance["script_approval"]["script_hash"] != digest:
                raise Conflict("脚本与确认记录不一致")
            snapshot = {
                "storyboard": board,
                "alignment": alignment,
                "storyboard_revision": j["storyboard_revision"],
                "provenance": provenance,
                "title": j["title"],
                "script": j["script"],
                "seconds": j["seconds"],
                "assets": assets,
            }
            c.execute(
                "UPDATE jobs SET script_hash=?,snapshot=? WHERE id=?",
                (digest, json.dumps(snapshot, ensure_ascii=False), jid),
            )
            self._event(c, jid, "draft", "queued", "锁定脚本和素材，等待渲染", time.time())
            if receipt:
                receipt(c, jid)
        return self.get(jid)

    def claim(self, owner, now=None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            expired = c.execute(
                "SELECT * FROM jobs WHERE status IN ('validating','rendering','auditing') AND lease_until<=?",
                (now,),
            ).fetchall()
            for j in expired:
                target = "queued" if j["attempts"] < j["max_attempts"] else "failed"
                c.execute(
                    "UPDATE jobs SET lease_token=NULL,lease_until=NULL,worker_id=NULL,error=? WHERE id=?",
                    ("执行进程失联，租约已过期", j["id"]),
                )
                self._event(
                    c,
                    j["id"],
                    j["status"],
                    target,
                    "租约超时，自动恢复" if target == "queued" else "恢复次数耗尽，请复制为新草稿",
                    now,
                )
            row = c.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            jid = row["id"]
            c.execute(
                "UPDATE jobs SET attempts=attempts+1,lease_token=?,lease_until=?,worker_id=?,error=NULL WHERE id=?",
                (uuid.uuid4().hex, now + LEASE_SECONDS, owner, jid),
            )
            self._event(c, jid, "queued", "validating", "检查脚本与素材", now)
        return self.get(jid)

    def _owned(self, c, jid, token, now):
        j = self._row(c, jid)
        if (
            not token
            or j["lease_token"] != token
            or j["status"] not in ACTIVE
            or j["lease_until"] <= now
        ):
            raise Conflict("任务已取消或执行租约失效")
        return j

    def heartbeat(self, jid, token, now=None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            try:
                self._owned(c, jid, token, now)
            except Conflict:
                return False
            c.execute("UPDATE jobs SET lease_until=? WHERE id=?", (now + LEASE_SECONDS, jid))
        return True

    def advance(self, jid, token, target, now=None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            j = self._owned(c, jid, token, now)
            if target not in ACTIVE or target not in TRANSITIONS[j["status"]]:
                raise Conflict("非法任务状态迁移")
            self._event(
                c,
                jid,
                j["status"],
                target,
                {"rendering": "正在合成视频", "auditing": "检查成片与生成审核报告"}[target],
                now,
            )

    def finish(self, jid, token, target, artifacts, audit, error=None, *, guard=None):
        now = time.time()
        with self.transaction() as c:
            if guard:
                guard(c)
            j = self._owned(c, jid, token, now)
            if target not in TRANSITIONS[j["status"]] or target in ACTIVE:
                raise Conflict("非法完成状态")
            c.execute("DELETE FROM artifacts WHERE job_id=?", (jid,))
            for a in artifacts:
                c.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex,
                        jid,
                        a["kind"],
                        a["path"],
                        a["sha256"],
                        a["size"],
                        j["attempts"],
                    ),
                )
            c.execute(
                "UPDATE jobs SET audit=?,error=?,lease_token=NULL,lease_until=NULL,worker_id=NULL WHERE id=?",
                (json.dumps(audit, ensure_ascii=False), error, jid),
            )
            self._event(
                c,
                jid,
                j["status"],
                target,
                error
                or {
                    "blocked": "脚本命中阻断规则，请复制后修改",
                    "needs_review": "成片已生成，请人工复核",
                }.get(target, target),
                now,
            )

    def cancel(self, jid):
        with self.transaction() as c:
            j = self._row(c, jid)
            if j["status"] == "cancelled":
                return self.get(jid)
            if j["status"] not in ("draft", "queued", *ACTIVE):
                raise Conflict("当前任务不可取消")
            c.execute(
                "UPDATE jobs SET lease_token=NULL,lease_until=NULL,worker_id=NULL WHERE id=?",
                (jid,),
            )
            self._event(c, jid, j["status"], "cancelled", "用户取消任务", time.time())
        return self.get(jid)

    def retry(self, jid):
        with self.transaction() as c:
            j = self._row(c, jid)
            if j["status"] != "failed" or j["attempts"] >= j["max_attempts"]:
                raise Conflict("仅可重试未耗尽次数的失败任务；也可以复制为新草稿")
            c.execute("UPDATE jobs SET error=NULL WHERE id=?", (jid,))
            self._event(c, jid, "failed", "queued", "用户重试", time.time())
        return self.get(jid)

    def review(self, jid, decision, reviewer, note, confirmed):
        if (
            decision not in ("ready", "rejected")
            or not reviewer.strip()
            or not note.strip()
            or not confirmed
        ):
            raise ValueError("请填写审核人、复核说明并确认检查清单")
        with self.transaction() as c:
            j = self._row(c, jid)
            if j["status"] != "needs_review":
                raise Conflict("当前任务不能人工放行")
            if not c.execute(
                "SELECT 1 FROM artifacts WHERE job_id=? AND kind='video'", (jid,)
            ).fetchone():
                raise Conflict("缺少可复核成片")
            now = time.time()
            c.execute(
                "INSERT INTO reviews(job_id,decision,reviewer,note,checklist_confirmed,script_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                (jid, decision, reviewer.strip(), note.strip(), 1, j["script_hash"], now),
            )
            self._event(
                c,
                jid,
                "needs_review",
                decision,
                "人工复核通过" if decision == "ready" else "人工复核退回",
                now,
            )
        return self.get(jid)

    def worker_heartbeat(self, owner):
        with self.connect() as c:
            c.execute(
                "INSERT INTO workers VALUES(?,?) ON CONFLICT(id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at",
                (owner, time.time()),
            )

    def workers(self):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM workers WHERE heartbeat_at>?", (time.time() - 30,)
                )
            ]
