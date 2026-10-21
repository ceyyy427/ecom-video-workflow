"""Creative descriptors from immutable submitted inputs; never inferred performance causes."""

import hashlib
import json
import time
import uuid
from decimal import Decimal

from .db import Conflict
from .distribution import encode
from .review_contracts import FEATURE_VERSION, LabelInput, enabled, identifier, parse

FIELDS = (
    "format",
    "style_id",
    "hook_text",
    "shot_count",
    "video_shot_count",
    "image_shot_count",
    "narration_mode",
    "duration_s",
    "storyboard_revision",
    "music_present",
)


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def extract(job, video_sha256):
    raw = job["snapshot"]
    snapshot = json.loads(raw) if raw else None
    fields = dict.fromkeys(FIELDS)
    sources = {}
    missing = []
    status = "unavailable"
    if not isinstance(snapshot, dict):
        missing.append("submitted_snapshot_missing")
    else:
        script = snapshot.get("script")
        if isinstance(script, str) and script.splitlines():
            fields["hook_text"] = script.splitlines()[0]
            sources["hook_text"] = "/script/line/0"
        board = snapshot.get("storyboard")
        if isinstance(board, dict):
            creative = board.get("creative") or {}
            for key, value, path in [
                (
                    "format",
                    (creative.get("brief") or {}).get("format"),
                    "/storyboard/creative/brief/format",
                ),
                ("style_id", creative.get("style_id"), "/storyboard/creative/style_id"),
                (
                    "narration_mode",
                    (board.get("narration") or {}).get("mode"),
                    "/storyboard/narration/mode",
                ),
                (
                    "storyboard_revision",
                    snapshot.get("storyboard_revision"),
                    "/storyboard_revision",
                ),
            ]:
                fields[key] = value
                sources[key] = path
            if "music_id" in board:
                fields["music_present"] = bool(board["music_id"])
                sources["music_present"] = "/storyboard/music_id"
            shots = board.get("shots")
            if isinstance(shots, list) and shots:
                fields["shot_count"] = len(shots)
                sources["shot_count"] = "/storyboard/shots"
                kinds = {
                    a["id"]: a["kind"]
                    for a in snapshot.get("assets", [])
                    if "id" in a and "kind" in a
                }
                if all(s.get("asset_id") in kinds for s in shots):
                    fields["video_shot_count"] = sum(kinds[s["asset_id"]] == "video" for s in shots)
                    fields["image_shot_count"] = sum(kinds[s["asset_id"]] == "image" for s in shots)
                    sources.update(
                        video_shot_count="/storyboard/shots + /assets/kind",
                        image_shot_count="/storyboard/shots + /assets/kind",
                    )
                try:
                    fields["duration_s"] = format(
                        sum((Decimal(str(s["duration"])) for s in shots), Decimal(0)), "f"
                    )
                except (KeyError, ValueError, TypeError):
                    pass
                else:
                    sources["duration_s"] = "/storyboard/shots/duration"
        for key, value in fields.items():
            if value is None:
                missing.append("feature_missing:" + key)
        status = "partial" if missing else "complete"
    return {
        "feature_version": FEATURE_VERSION,
        "job_id": job["id"],
        "parent_job_id": job["parent_id"],
        "video_sha256": video_sha256,
        "input_snapshot_hash": sha(snapshot),
        "status": status,
        "features": fields,
        "field_sources": sources,
        "missing_reasons": missing,
        "origin": "deterministic_submitted_snapshot_extraction;configuration_not_causal_evidence",
        "video_integrity": "recorded_binding_and_artifact_hash;not_rehashed",
    }


class Features:
    def __init__(self, store):
        self.store = store

    def capture(self, c, binding):
        job = c.execute("SELECT * FROM jobs WHERE id=?", (binding["job_id"],)).fetchone()
        video = c.execute(
            "SELECT sha256 FROM artifacts WHERE job_id=? AND kind='video'", (binding["job_id"],)
        ).fetchone()
        if not job:
            return None, "job_missing"
        if job["status"] != "ready":
            return None, "job_not_ready"
        if not video or video["sha256"] != binding["video_sha256"]:
            return None, "video_hash_mismatch"
        data = extract(dict(job), binding["video_sha256"])
        old = c.execute(
            "SELECT * FROM creative_features WHERE job_id=? AND video_sha256=? AND input_snapshot_hash=? AND feature_version=?",
            (job["id"], binding["video_sha256"], data["input_snapshot_hash"], FEATURE_VERSION),
        ).fetchone()
        if old:
            fid = old["id"]
            data = json.loads(old["payload"])
            if sha(data) != old["feature_hash"]:
                raise Conflict("创意特征校验失败，未冻结复盘。")
        else:
            fid = uuid.uuid4().hex
            c.execute(
                "INSERT INTO creative_features VALUES(?,?,?,?,?,?,?,?)",
                (
                    fid,
                    job["id"],
                    binding["video_sha256"],
                    data["input_snapshot_hash"],
                    FEATURE_VERSION,
                    sha(data),
                    encode(data),
                    time.time(),
                ),
            )
        return {
            **data,
            "feature_id": fid,
            "feature_hash": sha(data),
            "labels": self.labels(c, fid),
        }, "bound"

    def labels(self, c, fid):
        groups = {"human": [], "model": []}
        for origin in groups:
            for key in ("hook_type", "visual_tone", "product_category"):
                r = c.execute(
                    "SELECT id,payload,created_at FROM creative_labels WHERE feature_id=? AND origin=? AND label_key=? ORDER BY seq DESC LIMIT 1",
                    (fid, origin, key),
                ).fetchone()
                if r:
                    groups[origin].append(
                        {
                            **json.loads(r["payload"]),
                            "label_id": r["id"],
                            "created_at": r["created_at"],
                        }
                    )
        return groups

    def get(self, fid):
        identifier(fid)
        with self.store.connect() as c:
            c.execute("BEGIN")
            row = c.execute("SELECT * FROM creative_features WHERE id=?", (fid,)).fetchone()
            if not row:
                raise KeyError(fid)
            data = json.loads(row["payload"])
            if sha(data) != row["feature_hash"]:
                raise Conflict("创意特征校验失败。")
            return {
                **data,
                "feature_id": fid,
                "feature_hash": row["feature_hash"],
                "labels": self.labels(c, fid),
            }

    def label(self, fid, value):
        identifier(fid)
        cmd = parse(LabelInput, value)
        if not enabled():
            raise ValueError("冻结复盘入口未启用。")
        digest = sha({"feature_id": fid, **cmd.model_dump()})
        with self.store.transaction() as c:
            prior = c.execute(
                "SELECT * FROM creative_labels WHERE request_id=?", (cmd.request_id,)
            ).fetchone()
            if prior:
                if prior["command_hash"] != digest:
                    raise Conflict("该 request_id 已用于另一份标签，请使用新标识。")
                return {"label_id": prior["id"], **json.loads(prior["payload"])}
            row = c.execute("SELECT payload FROM creative_features WHERE id=?", (fid,)).fetchone()
            if not row:
                raise KeyError(fid)
            data = json.loads(row["payload"])
            if data["features"].get(cmd.evidence_field) is None:
                raise Conflict("该创意字段未知，不能据此登记标签。")
            label = {k: v for k, v in cmd.model_dump().items() if k != "request_id"}
            label["verified"] = cmd.origin == "human"
            label["provenance_status"] = (
                "human_confirmed"
                if cmd.origin == "human"
                else "self_reported_model_label;not_verified"
            )
            lid = uuid.uuid4().hex
            c.execute(
                "INSERT INTO creative_labels(id,feature_id,origin,label_key,request_id,command_hash,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    lid,
                    fid,
                    cmd.origin,
                    cmd.label_key,
                    cmd.request_id,
                    digest,
                    encode(label),
                    time.time(),
                ),
            )
        return {"label_id": lid, **label}
