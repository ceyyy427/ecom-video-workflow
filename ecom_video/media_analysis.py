"""Persistent media analysis with source binding, bounded leases and cancellation."""

import json
import time
import uuid
from pathlib import Path

from .creative import signature
from .db import Conflict
from .media import digest, safe_path
from .product_inspection import context_for, current_context, inspect_segment


def attach(c, media):
    for a in media:
        r = c.execute(
            "SELECT * FROM media_analyses WHERE media_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (a["id"],),
        ).fetchone()
        a["analysis"] = decode(r) if r else None
    return media


def decode(r):
    value = dict(r)
    value["result"] = json.loads(value["result"]) if value["result"] else None
    if value["result"]:
        from .material_suitability import visible_ranges

        for segment in value["result"].get("segments", []):
            motion = segment.get("motion_check") or {}
            if motion.get("material_checks_version"):
                motion["material_visible_ranges"] = visible_ranges(
                    {"motion_check": motion, "asset_sha256": value["source_sha256"]},
                    motion.get("reference_sha256"),
                )
    value.pop("lease_token", None)
    value.pop("lease_until", None)
    return value


def identities(media):
    return {
        a["id"]: a["analysis"]["id"]
        if a.get("analysis") and a["analysis"]["status"] == "ready"
        else None
        for a in media
        if a["kind"] != "audio"
    }


def snapshot_guard(c, media):
    current = attach(c, [dict(a) for a in media])

    def snapshots(items):
        return {
            a["id"]: (a["analysis"]["id"], a["analysis"]["status"])
            if a.get("analysis") and a["analysis"]["status"] in ("ready", "partial")
            else None
            for a in items
            if a["kind"] != "audio"
        }

    if snapshots(current) != snapshots(media):
        raise Conflict("素材识别版本已变化，请重新准备制作版本")


class Analysis:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    def asset(self, c, pid, mid):
        a = c.execute(
            "SELECT * FROM customer_media WHERE id=? AND product_id=?", (mid, pid)
        ).fetchone()
        if not a:
            raise KeyError(mid)
        if a["kind"] == "audio":
            raise ValueError("此入口识别画面素材，配音沿用口播对齐")
        return dict(a)

    def get(self, pid, mid):
        with self.store.connect() as c:
            self.asset(c, pid, mid)
            r = c.execute(
                "SELECT * FROM media_analyses WHERE media_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (mid,),
            ).fetchone()
        return decode(r) if r else None

    def start(self, pid, mid, *, receipt=None, refresh=False, force_inference=False):
        refresh = refresh or force_inference
        with self.store.transaction() as c:
            if receipt:
                receipt.guard(c)
            a = self.asset(c, pid, mid)
            context = context_for(c, pid)
            prior = c.execute(
                "SELECT * FROM media_analyses WHERE media_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (mid,),
            ).fetchone()
            if (
                prior
                and prior["status"] in ("queued", "running", "ready")
                and prior["source_sha256"] == a["sha256"]
                and current_context(decode(prior), context)
                and (not refresh or prior["status"] in ("queued", "running"))
                and (
                    not force_inference
                    or bool((decode(prior).get("result") or {}).get("force_inference"))
                )
            ):
                if receipt:
                    receipt(c, prior["id"], owned_override=False)
                return decode(prior)
            c.execute(
                "UPDATE media_analyses SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE media_id=? AND status IN ('queued','running')",
                (mid,),
            )
            aid = uuid.uuid4().hex
            now = time.time()
            c.execute(
                "INSERT INTO media_analyses(id,media_id,source_sha256,status,stage,result,created_at,updated_at) VALUES(?,?,?,'queued','等待本机识别',?,?,?)",
                (
                    aid,
                    mid,
                    a["sha256"],
                    json.dumps(
                        {
                            "context": context,
                            **({"force_inference": True} if force_inference else {}),
                        }
                    )
                    if context or force_inference
                    else None,
                    now,
                    now,
                ),
            )
            if receipt:
                receipt(c, aid)
        if prior:
            cleanup_removed(self.root, self.store, mid, prior["id"])
        return self.get(pid, mid)

    def cancel(self, pid, mid):
        with self.store.transaction() as c:
            self.asset(c, pid, mid)
            c.execute(
                "UPDATE media_analyses SET status='cancelled',stage='已取消',lease_token=NULL,lease_until=NULL,updated_at=? WHERE media_id=? AND status IN ('queued','running')",
                (time.time(), mid),
            )
        return self.get(pid, mid)

    def frame(self, pid, mid, aid, clip, index):
        with self.store.connect() as c:
            self.asset(c, pid, mid)
            r = c.execute(
                "SELECT * FROM media_analyses WHERE id=? AND media_id=? AND status IN ('ready','partial')",
                (aid, mid),
            ).fetchone()
        if not r:
            raise KeyError(aid)
        segments = json.loads(r["result"])["segments"]
        s = next((s for s in segments if s["id"] == clip), None)
        if not s or not 0 <= index < len(s["frames"]):
            raise KeyError(clip)
        return safe_path(self.root, f"analyses/{aid}/{s['frames'][index]}")

    def claim(self):
        with self.store.transaction() as c:
            # Expired work requires explicit retry; never launch an unlimited retry loop.
            c.execute(
                "UPDATE media_analyses SET status='failed',error='识别进程中断，请重试',lease_token=NULL WHERE status='running' AND lease_until<?",
                (time.time(),),
            )
            if c.execute("SELECT 1 FROM media_analyses WHERE status='running'").fetchone():
                return None
            r = c.execute(
                "SELECT * FROM media_analyses WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not r:
                return None
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE media_analyses SET status='running',lease_token=?,lease_until=?,updated_at=? WHERE id=?",
                (token, time.time() + 60, time.time(), r["id"]),
            )
            return {**dict(r), "lease_token": token}

    def progress(self, row, stage=None):
        with self.store.transaction() as c:
            changed = c.execute(
                "UPDATE media_analyses SET lease_until=?,updated_at=?,stage=COALESCE(?,stage) WHERE id=? AND lease_token=? AND status='running'",
                (time.time() + 60, time.time(), stage, row["id"], row["lease_token"]),
            ).rowcount
        if not changed:
            raise Conflict("识别已取消或素材已移除")

    def run(self, row, check, *, resource=None):
        from .inference_reuse import scope
        from .vision_model import execution_scope

        request = json.loads(row["result"]) if row.get("result") else {}
        with (
            scope(self.root, check, bypass=bool(request.get("force_inference"))) as cache,
            execution_scope(check) as execution,
        ):
            return self._run(row, check, resource=resource, cache=cache, execution=execution)

    def _run(self, row, check, *, resource=None, cache, execution):
        started = time.monotonic()
        from .clip_scan import scan
        from .vision_model import identity, observe

        with self.store.connect() as c:
            asset = c.execute(
                "SELECT * FROM customer_media WHERE id=?", (row["media_id"],)
            ).fetchone()
        if not asset:
            raise Conflict("素材已移除")
        context = (json.loads(row["result"]) if row.get("result") else {}).get("context", {})
        path = safe_path(self.root, asset["path"])
        if not path.is_file() or digest(path) != row["source_sha256"]:
            raise ValueError("素材哈希不符，请重新上传")
        model = None
        check()
        folder = self.root / "analyses" / row["id"]
        failure = None
        result = None
        try:
            model = identity()
        except ValueError as exc:
            failure = str(exc)[:500]
        if model is not None and context and not cache.bypass:
            from .current_observation_reuse import reuse
            from .inspection_cache import reuse_observations

            self.progress(row, "校验可复用的既有观测")
            result = reuse(self.root, self.store, asset, context, model, folder, check)
            if result is None:
                result = reuse_observations(
                    self.root, self.store, asset, context, model, folder, check
                )
        reused = result is not None
        if not reused:
            self.progress(row, "检测切点并抽取关键帧")
            result = scan(path, asset["kind"], json.loads(asset["metadata"]), folder, check)
            for segment in result["segments"]:
                segment["observation"] = {
                    "description": "内容尚未识别；可根据关键帧人工选段",
                    "subjects": [],
                    "actions": [],
                    "framing": "unknown",
                    "usable": False,
                    "uncertainty": "未完成视觉识别",
                }
        try:
            if failure:
                raise ValueError(failure)
            for i, segment in enumerate(result["segments"]):
                check()
                self.progress(row, f"识别片段 {i + 1}/{len(result['segments'])}")
                if segment["quality"]["blank"]:
                    segment["observation"]["description"] = "抽样画面接近全黑或全白，不参与自动选择"
                elif reused:
                    from .product_inspection import refine_segment

                    self.progress(row, f"复核既有观测的动作 {i + 1}/{len(result['segments'])}")
                    refine_segment(segment, folder, model, check, context)
                else:
                    segment["observation"] = observe([folder / f for f in segment["frames"]], model)
                    if context:
                        self.progress(row, f"核对商品外观与动作 {i + 1}/{len(result['segments'])}")
                        inspect_segment(
                            self.root,
                            path,
                            asset["kind"],
                            segment,
                            folder,
                            context,
                            model,
                            check,
                            lambda stage: self.progress(row, stage),
                        )
            if identity() != model:
                raise Conflict("识别期间模型变化，请重试")
        except ValueError as exc:
            failure = str(exc)[:500]
        check()
        if digest(path) != row["source_sha256"]:
            raise Conflict("识别期间素材变化，请重试")
        if context:
            reference = safe_path(self.root, context["reference_path"])
            if not reference.is_file() or digest(reference) != context["reference_sha256"]:
                raise Conflict("识别期间商品参照图变化，请重新识别")
        result["recognition"] = "unavailable" if failure else "complete"
        result.update(
            context=context,
            model=model,
            source_sha256=row["source_sha256"],
            analysis_id=row["id"],
            engine=signature(
                {
                    "model": model,
                    "scanner": digest(Path(__file__).with_name("clip_scan.py")),
                    "adapter": digest(Path(__file__).with_name("vision_model.py")),
                    "inspection": digest(Path(__file__).with_name("product_inspection.py")),
                }
            ),
        )
        if not failure:
            from .current_observation_reuse import seal

            seal(result, folder)
        from .vision_model import finish_execution

        finish_execution(execution)
        result["performance"] = {
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "model_cache": cache.metrics(),
            "execution": execution,
        }
        with self.store.transaction() as c:
            if resource:
                resource.guard(c)
            if context_for(c, asset["product_id"], required=False) != context:
                raise Conflict("识别期间商品参照或动作设置变化，请重新识别")
            changed = c.execute(
                "UPDATE media_analyses SET status=?,stage=?,error=?,result=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND lease_token=? AND status='running'",
                (
                    "partial" if failure else "ready",
                    "已完成切点与抽帧，内容识别未就绪" if failure else "关键帧识别完成，仍需核对",
                    failure,
                    json.dumps(result, ensure_ascii=False),
                    time.time(),
                    row["id"],
                    row["lease_token"],
                ),
            ).rowcount
            if not changed:
                raise Conflict("识别已取消")

    def fail(self, row, error):
        with self.store.transaction() as c:
            c.execute(
                "UPDATE media_analyses SET status='failed',error=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=? AND lease_token=? AND status='running'",
                (str(error)[:500], time.time(), row["id"], row["lease_token"]),
            )


def cleanup_removed(root, store, mid, aid):
    """Retain current usable previews and historical evidence, not abandoned derivatives."""
    import shutil

    with store.connect() as c:
        exists = c.execute("SELECT 1 FROM customer_media WHERE id=?", (mid,)).fetchone()
        row = c.execute("SELECT status FROM media_analyses WHERE id=?", (aid,)).fetchone()
        latest = c.execute(
            "SELECT id FROM media_analyses WHERE media_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (mid,),
        ).fetchone()
        if (
            exists
            and row
            and (
                row["status"] in ("ready", "running", "queued")
                or (row["status"] == "partial" and latest and latest["id"] == aid)
            )
        ):
            return
        if c.execute(
            "SELECT 1 FROM assets WHERE json_extract(metadata,'$.content_analysis.analysis_id')=? LIMIT 1",
            (aid,),
        ).fetchone():
            return
    shutil.rmtree(safe_path(root, f"analyses/{aid}"), ignore_errors=True)
