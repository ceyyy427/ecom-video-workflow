"""Customer intake and immutable visual revisions, built on product evidence and the existing queue."""

import copy
import json
import shutil
import time
import uuid
from pathlib import Path

from .alignment import confirmed_alignment, matches_input
from .creative import rebase_fingerprint, signature
from .db import Conflict
from .material_suitability import VERSION as MATERIAL_VERSION
from .media import digest, safe_path
from .media_analysis import attach, identities, snapshot_guard
from .product_motion import VERSION as MOTION_VERSION
from .products import Products, encoded
from .storyboard import validate_board


def uid():
    return uuid.uuid4().hex


class Customers:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.products = Products(store)

    def row(self, c, pid, revision=None):
        row = c.execute("SELECT * FROM customer_projects WHERE product_id=?", (pid,)).fetchone()
        if not row:
            raise KeyError(pid)
        if revision is not None and row["revision"] != revision:
            raise Conflict("客户项目已更新，请重新载入后继续")
        return dict(row)

    def touch(self, c, pid, job=None):
        c.execute(
            "UPDATE customer_projects SET revision=revision+1,updated_at=? WHERE product_id=?",
            (time.time(), pid),
        )
        if job:
            c.execute("UPDATE customer_projects SET active_job_id=? WHERE product_id=?", (job, pid))

    def create(self, title, settings):
        product = self.products.create(title)
        now = time.time()
        with self.store.transaction() as c:
            c.execute(
                "INSERT INTO customer_projects VALUES(?,0,?,NULL,?,?)",
                (product["id"], encoded(settings), now, now),
            )
        return self.get(product["id"])

    def listing(self):
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT p.product_id AS id,t.title,p.updated_at,p.active_job_id FROM customer_projects p JOIN products t ON t.id=p.product_id ORDER BY p.updated_at DESC LIMIT 100"
                )
            ]

    @staticmethod
    def fingerprint(p):
        return signature(
            {
                "settings": p["settings"],
                **(
                    {"material_checks_version": MATERIAL_VERSION}
                    if p["settings"].get("material_checks")
                    else {}
                ),
                **(
                    {"inspection_version": MOTION_VERSION}
                    if p["settings"].get("auto_select")
                    and (p["settings"].get("strict_product") or p["settings"].get("action_timing"))
                    else {}
                ),
                "review": p["product"]["current_review_id"],
                "draft": p["product"]["current_draft_id"],
                **(
                    {"analysis": identities(p["media"])} if p["settings"].get("auto_select") else {}
                ),
                "media": [
                    {k: a[k] for k in ("id", "sha256", "kind", "role", "source_in", "note")}
                    for a in p["media"]
                ],
            }
        )

    @staticmethod
    def basis(p):
        return signature(
            {
                "settings": p["settings"],
                "review": p["product"]["current_review_id"],
                "draft": p["product"]["current_draft_id"],
                "audio": [
                    {"sha256": a["sha256"], "role": a["role"]}
                    for a in p["media"]
                    if a["kind"] == "audio"
                ],
            }
        )

    def get(self, pid):
        with self.store.connect() as c:
            p = self.row(c, pid)
            p["settings"] = json.loads(p["settings"])
            p["id"] = p.pop("product_id")
            p["media"] = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM customer_media WHERE product_id=? ORDER BY rowid", (pid,)
                )
            ]
            attach(c, p["media"])
            from .product_inspection import context_for, current_context

            context = context_for(c, pid, required=False)
            for a in p["media"]:
                a["analysis_stale"] = bool(
                    a.get("analysis") and not current_context(a["analysis"], context)
                )
            for a in p["media"]:
                a["metadata"] = json.loads(a["metadata"])
            from .voice_takes import listing as voice_takes

            p["voice_takes"] = voice_takes(c, pid)
            from .shot_voice import ShotVoice

            p["voice_patches"] = ShotVoice.listing(c, pid)
            p["versions"] = [
                dict(r)
                for r in c.execute(
                    "SELECT j.id,j.title,j.status,j.created_at,j.parent_id FROM customer_jobs v JOIN jobs j ON j.id=v.job_id WHERE v.product_id=? ORDER BY v.created_at DESC",
                    (pid,),
                )
            ]
            active = c.execute(
                "SELECT * FROM customer_jobs WHERE job_id=? AND product_id=?",
                (p["active_job_id"], pid),
            ).fetchone()
            iteration = c.execute(
                "SELECT id,review_id,parent_job_id,status FROM experiments WHERE result_job_id=?",
                (p["active_job_id"],),
            ).fetchone()
            p["iteration"] = dict(iteration) if iteration else None
            if iteration:
                from .creative_features import sha

                job = c.execute(
                    "SELECT storyboard,storyboard_revision FROM jobs WHERE id=?",
                    (p["active_job_id"],),
                ).fetchone()
                board = json.loads(job["storyboard"]) if job["storyboard"] else None
                p["iteration"]["style_confirm_needed"] = not bool(
                    board
                    and c.execute(
                        "SELECT 1 FROM experiment_styles WHERE experiment_id=? AND job_id=? AND board_revision=? AND board_hash=?",
                        (
                            iteration["id"],
                            p["active_job_id"],
                            job["storyboard_revision"],
                            sha(board),
                        ),
                    ).fetchone()
                )
        p["product"] = self.products.get(pid)
        p["job"] = self.store.get(p["active_job_id"]) if active else None
        p["inputs_changed"] = bool(active and active["input_fingerprint"] != self.fingerprint(p))
        p["visual_revision_allowed"] = bool(active and active["basis_fingerprint"] == self.basis(p))
        p["planning_notes"] = json.loads(active["planning_notes"]) if active else []
        from .customer_directions import directions, preparation_blockers

        p["recommendations"], p["direction_basis"] = directions(p)
        p["preparation_blockers"] = preparation_blockers(p)
        p["alignment"] = None
        if p["job"]:
            voice = next(
                (a for a in p["job"]["assets"] if a["metadata"].get("customer_role") == "voice"),
                None,
            )
            if voice:
                with self.store.connect() as c:
                    row = next(
                        (
                            r
                            for r in c.execute(
                                "SELECT * FROM alignments WHERE job_id=? ORDER BY updated_at DESC,rowid DESC",
                                (p["job"]["id"],),
                            )
                            if matches_input(r, p["job"], voice)
                        ),
                        None,
                    )
                if row:
                    p["alignment"] = dict(row)
                    p["alignment"]["result"] = json.loads(row["result"]) if row["result"] else None
        p["matching_script_drafts"] = []
        diagnostic = (p.get("alignment") or {}).get("result") or {}
        if diagnostic.get("diagnostic", {}).get("transcript"):
            from .speech_match import matching_drafts

            review = next(
                (
                    r
                    for r in p["product"]["fact_reviews"]
                    if r["id"] == p["product"]["current_review_id"]
                ),
                None,
            )
            p["matching_script_drafts"] = matching_drafts(
                p["product"]["script_drafts"],
                diagnostic["diagnostic"]["transcript"],
                set(review["fact_ids"] if review else []),
            )
        return p

    def settings(self, pid, revision, settings):
        with self.store.transaction() as c:
            self.row(c, pid, revision)
            reference_id = settings.get("product_reference_id")
            if (
                reference_id
                and not c.execute(
                    "SELECT 1 FROM customer_media WHERE id=? AND product_id=? AND kind='image'",
                    (reference_id, pid),
                ).fetchone()
            ):
                raise ValueError("商品参照图必须是本项目上传的图片")
            c.execute(
                "UPDATE customer_projects SET settings=? WHERE product_id=?",
                (encoded(settings), pid),
            )
            self.touch(c, pid)
        return self.get(pid)

    def add_media(
        self, pid, revision, a, *, product_revision=None, replace_voice_id=None, voice_take=None
    ):
        with self.store.transaction() as c:
            self.row(c, pid, revision)
            if product_revision is not None:
                self.products._row(c, pid, product_revision)
            old_voice = None
            if replace_voice_id:
                old_voice = c.execute(
                    "SELECT * FROM customer_media WHERE id=? AND product_id=? AND role='voice'",
                    (replace_voice_id, pid),
                ).fetchone()
                if not old_voice or a["kind"] != "audio" or a["role"] != "voice":
                    raise Conflict("待替换的配音已变化，请重新载入")
            from .voice_takes import archive, budget, insert, saved_file

            already_saved = saved_file(c, pid, a)
            archive_count = int(bool(old_voice and not saved_file(c, pid, old_voice)))
            budget(
                c,
                pid,
                0 if already_saved else a["size"],
                archive_count + int(bool(voice_take and not already_saved)),
            )
            rows = c.execute(
                "SELECT kind,role,size FROM customer_media WHERE product_id=?", (pid,)
            ).fetchall()
            if a["kind"] == "audio" and not old_voice and any(r["role"] == a["role"] for r in rows):
                raise ValueError("配音和音乐各保留一条，请先移除旧素材再上传")
            if a["kind"] != "audio" and sum(r["kind"] != "audio" for r in rows) >= 30:
                raise ValueError("最多30份画面素材")
            if old_voice:
                archive(c, dict(old_voice), pid)
                c.execute("DELETE FROM customer_media WHERE id=?", (old_voice["id"],))
            if voice_take:
                insert(c, a, pid, **voice_take)
            c.execute(
                "INSERT INTO customer_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a["id"],
                    pid,
                    a["name"],
                    a["path"],
                    a["kind"],
                    a["role"],
                    a["sha256"],
                    a["size"],
                    encoded(a["metadata"]),
                    0,
                    "",
                    time.time(),
                ),
            )
            self.touch(c, pid)
        return self.get(pid)

    def edit_media(self, pid, aid, revision, role, source_in, note):
        with self.store.transaction() as c:
            self.row(c, pid, revision)
            a = c.execute(
                "SELECT * FROM customer_media WHERE id=? AND product_id=?", (aid, pid)
            ).fetchone()
            if not a:
                raise KeyError(aid)
            if (a["kind"] == "audio") != (role in ("voice", "music")):
                raise ValueError("声音与画面的用途不能互换")
            if (
                a["kind"] == "audio"
                and c.execute(
                    "SELECT 1 FROM customer_media WHERE product_id=? AND role=? AND id!=?",
                    (pid, role, aid),
                ).fetchone()
            ):
                raise ValueError("此声音用途已经存在")
            source_in = round(source_in * 30) / 30
            if source_in and (
                a["kind"] != "video" or source_in >= json.loads(a["metadata"])["duration"]
            ):
                raise ValueError("只有视频支持入点，且必须在源视频时长内")
            c.execute(
                "UPDATE customer_media SET role=?,source_in=?,note=? WHERE id=?",
                (role, source_in, note, aid),
            )
            self.touch(c, pid)
        return self.get(pid)

    def remove_media(self, pid, aid, revision):
        with self.store.transaction() as c:
            self.row(c, pid, revision)
            a = c.execute(
                "SELECT path FROM customer_media WHERE id=? AND product_id=?", (aid, pid)
            ).fetchone()
            if not a:
                raise KeyError(aid)
            analyses = [
                r["id"] for r in c.execute("SELECT id FROM media_analyses WHERE media_id=?", (aid,))
            ]
            c.execute("DELETE FROM customer_media WHERE id=?", (aid,))
            retained = bool(
                c.execute(
                    "SELECT 1 FROM voice_takes WHERE product_id=? AND path=?", (pid, a["path"])
                ).fetchone()
            )
            self.touch(c, pid)
        if not retained:
            safe_path(self.root, a["path"]).unlink(missing_ok=True)
        from .media_analysis import cleanup_removed

        for analysis_id in analyses:
            cleanup_removed(self.root, self.store, aid, analysis_id)
        return self.get(pid)

    def copy_assets(self, jid, assets, library=False):
        result = []
        mapping = {}
        try:
            for a in assets:
                source = safe_path(self.root, a["path"])
                if not source.is_file() or digest(source) != a["sha256"]:
                    raise Conflict("原素材缺失或内容变化，请重新上传；未修改旧版本")
                aid = uid()
                mapping[a["id"]] = aid
                relative = f"jobs/{jid}/assets/{aid}{source.suffix}"
                target = safe_path(self.root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if digest(target) != a["sha256"]:
                    raise Conflict("复制过程中素材发生变化，请重试")
                meta = copy.deepcopy(a["metadata"])
                if library:
                    if a.get("analysis") and a["analysis"]["status"] in ("ready", "partial"):
                        meta["content_analysis"] = copy.deepcopy(a["analysis"]["result"])
                    meta.update(
                        customer_role=a["role"],
                        library_id=a["id"],
                        source_in=a["source_in"],
                        evidence_note=a["note"],
                    )
                result.append({**a, "id": aid, "path": relative, "metadata": meta})
            return result, mapping
        except BaseException:
            shutil.rmtree(self.root / "jobs" / jid, ignore_errors=True)
            raise

    def insert_job(self, c, jid, source, assets, board=None, parent=None):
        now = time.time()
        c.execute(
            "INSERT INTO jobs(id,title,script,seconds,status,created_at,updated_at,parent_id,provenance,storyboard,storyboard_revision) VALUES(?,?,?,?,'draft',?,?,?,?,?,?)",
            (
                jid,
                source["title"],
                source["script"],
                source["seconds"],
                now,
                now,
                parent,
                encoded(source["provenance"]) if source.get("provenance") else None,
                encoded(board) if board else None,
                1 if board else 0,
            ),
        )
        for position, a in enumerate(assets):
            c.execute(
                "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    a["id"],
                    jid,
                    a["name"],
                    a["path"],
                    a["kind"],
                    a["sha256"],
                    a["size"],
                    position,
                    encoded(a["metadata"]),
                ),
            )
        self.store._event(c, jid, None, "draft", "客户素材快照；保留事实和脚本确认来源", now)

    def prepare(self, pid, revision, *, receipt=None):
        p = self.get(pid)
        if p["revision"] != revision:
            raise Conflict("客户项目已更新，请重新载入")
        prod = p["product"]
        approval = next(
            (a for a in prod["script_approvals"] if a["draft_id"] == prod["current_draft_id"]), None
        )
        if not approval or prod["status"] != "script_confirmed":
            raise Conflict("请先核对事实并确认当前文稿")
        if not any(a["kind"] != "audio" for a in p["media"]):
            raise ValueError("请上传商品图片或实拍视频")
        if p["settings"]["brief"]["format"] != "showcase" and not any(
            a["role"] == "voice" for a in p["media"]
        ):
            raise ValueError("此片种需要与文稿一致的成品配音；纯展示可不上传")
        if p["settings"].get("auto_select"):
            from .product_inspection import context_for

            with self.store.connect() as c:
                context_for(c, pid)
        if p["settings"].get("auto_select") and any(
            a["kind"] != "audio"
            and (
                not a.get("analysis")
                or a.get("analysis_stale")
                or a["analysis"]["status"] != "ready"
                or a["analysis"]["source_sha256"] != a["sha256"]
            )
            for a in p["media"]
        ):
            raise Conflict("请等待素材内容识别完成；失败时重试，或关闭自动选段使用手动模式")
        for s in prod["sources"]:
            path = safe_path(self.root, s["path"])
            if not path.is_file() or digest(path) != s["sha256"]:
                raise Conflict("产品资料缺失或内容变化，请重新核实来源")
        if p["job"] and not p["inputs_changed"]:
            if receipt:
                with self.store.transaction() as c:
                    receipt.guard(c)
                    receipt(c, p["job"]["id"])
            return p
        source = self.store.get(approval["job_id"])
        jid = uid()
        assets, _ = self.copy_assets(jid, p["media"], library=True)
        try:
            with self.store.transaction() as c:
                if receipt:
                    receipt.guard(c)
                self.row(c, pid, revision)
                self.products._row(c, pid, prod["revision"])
                snapshot_guard(c, p["media"])
                self.insert_job(c, jid, source, assets, parent=source["id"])
                c.execute(
                    "INSERT INTO customer_jobs VALUES(?,?,?,?,?,?)",
                    (jid, pid, self.fingerprint(p), self.basis(p), "[]", time.time()),
                )
                self.touch(c, pid, jid)
                if receipt:
                    receipt(c, jid)
        except BaseException:
            shutil.rmtree(self.root / "jobs" / jid, ignore_errors=True)
            raise
        return self.get(pid)

    def current(self, pid, revision, jid, board_revision, allow_media_change=False):
        p = self.get(pid)
        if (
            p["revision"] != revision
            or (p["inputs_changed"] and not (allow_media_change and p["visual_revision_allowed"]))
            or not p["job"]
            or p["job"]["id"] != jid
        ):
            raise Conflict("项目输入或当前制作版本已变化，请重新准备并选择风格")
        if p["job"]["storyboard_revision"] != board_revision:
            raise Conflict("分镜已更新，请重新载入")
        return p

    def plan(
        self,
        pid,
        revision,
        jid,
        board_revision,
        style_id,
        fingerprint,
        alignment_id,
        *,
        receipt=None,
    ):
        from .customer_planner import plan_board

        p = self.current(pid, revision, jid, board_revision)
        job = p["job"]
        if job["status"] != "draft":
            raise Conflict("此版本已锁定，请修改单镜创建新版本")
        if p["recommendations"]["fingerprint"] != fingerprint:
            raise Conflict("风格推荐已过期，请重新推荐")
        if job["storyboard"]:
            raise Conflict("已有分镜，请直接编辑；如需重新选择风格可打开创意工作室")
        alignment = (
            p["alignment"] if p["alignment"] and p["alignment"]["id"] == alignment_id else None
        )
        if p["settings"].get("auto_select"):
            from .readiness import project_preflight

            coverage = project_preflight(p)
            gaps = [r for r in coverage["lines"] if r["status"] == "gap"]
            if gaps:
                raise ValueError(
                    "制作前素材缺口："
                    + "；".join(f"第{r['line']}句 {r['message']}" for r in gaps[:3])
                    + "。请先检查并补拍，或关闭自动选段后人工安排；未修改文稿和原版。"
                )
        board, notes = plan_board(job, p["settings"], style_id, alignment)
        with self.store.transaction() as c:
            if receipt:
                receipt.guard(c)
            self.row(c, pid, revision)
            self.products._row(c, pid, p["product"]["revision"])
            if p["settings"].get("auto_select"):
                snapshot_guard(c, p["media"])
            row = self.store._row(c, jid)
            if row["storyboard_revision"] != board_revision or row["status"] != "draft":
                raise Conflict("分镜已更新")
            confirmed_alignment(c, job, job["assets"], board)
            c.execute(
                "UPDATE jobs SET storyboard=?,storyboard_revision=storyboard_revision+1,updated_at=? WHERE id=?",
                (encoded(board), time.time(), jid),
            )
            c.execute(
                "UPDATE customer_jobs SET planning_notes=? WHERE job_id=?", (encoded(notes), jid)
            )
            if receipt:
                receipt(c, jid)
        return self.get(pid)

    def submit(self, pid, revision, jid, board_revision, *, receipt=None):
        p = self.current(pid, revision, jid, board_revision)

        def guard(c, j):
            row = self.row(c, pid, revision)
            self.products._row(c, pid, p["product"]["revision"])
            if row["active_job_id"] != jid or j["storyboard_revision"] != board_revision:
                raise Conflict("项目或分镜已更新")

        self.store.submit(jid, guard=guard, receipt=receipt)
        return self.get(pid)

    def revise(self, pid, data, *, receipt=None):
        request_hash = signature(data)
        with self.store.connect() as c:
            prior = c.execute(
                "SELECT * FROM customer_edits WHERE request_id=?", (data["request_id"],)
            ).fetchone()
        if prior:
            if prior["product_id"] != pid or prior["request_hash"] != request_hash:
                raise Conflict("同一修改请求不能用于不同内容")
            return {**self.get(pid), "edit_result_job_id": prior["result_job_id"]}
        p = self.current(
            pid, data["revision"], data["job_id"], data["board_revision"], allow_media_change=True
        )
        original = p["job"]
        if original["status"] not in ("needs_review", "ready", "rejected", "failed", "cancelled"):
            raise Conflict("请等待生成结束，或取消任务后再修改单镜")
        if not original["storyboard"] or not original["storyboard"].get("creative"):
            raise ValueError("此版本没有可复用的创意分镜")
        board = copy.deepcopy(original["storyboard"])
        shot = next((s for s in board["shots"] if s["shot_id"] == data["shot_id"]), None)
        if not shot:
            raise KeyError(data["shot_id"])
        changes = dict(data["changes"])
        media_id = changes.pop("media_id", None)
        if not changes and not media_id:
            raise ValueError("请选择要修改的镜头参数")
        selected = None
        if media_id:
            selected = next(
                (a for a in p["media"] if a["id"] == media_id and a["kind"] != "audio"), None
            )
            if not selected:
                raise ValueError("替换画面不属于当前项目")
        jid = uid()
        assets, mapping = self.copy_assets(jid, original["assets"])
        try:
            if selected:
                existing = next(
                    (a for a in assets if a["metadata"].get("library_id") == media_id), None
                )
                if not existing:
                    if (
                        sum(a["kind"] != "audio" for a in assets) >= 30
                        or sum(a["size"] for a in assets) + selected["size"] > 500 * 1024**2
                    ):
                        raise ValueError("修订素材超过项目限制，请新建制作版本")
                    extra, _ = self.copy_assets(jid, [selected], library=True)
                    assets += extra
                    existing = extra[0]
                shot["asset_id"] = existing["id"]
                shot["role"] = selected["role"]
                shot["evidence_note"] = selected["note"]
                shot["source_in"] = selected["source_in"]
                shot["motion"] = "static" if selected["kind"] == "video" else "push"
                if selected["kind"] != "video" and "source_framing" not in changes:
                    shot["source_framing"] = "original"
            for s in board["shots"]:
                s["asset_id"] = mapping.get(s["asset_id"], s["asset_id"])
            for obj, key in ((board, "music_id"), (board["narration"], "asset_id")):
                if obj[key]:
                    obj[key] = mapping[obj[key]]
            if isinstance(changes.get("motion_plan"), dict):
                from .shotcraft import MotionPlan

                changes["motion_plan"] = MotionPlan.model_validate(
                    {**(shot.get("motion_plan") or {}), **changes["motion_plan"]}
                ).model_dump()
            manual_windows_submitted = (
                isinstance(data["changes"].get("motion_plan"), dict)
                and "windows" in data["changes"]["motion_plan"]
            )
            shot.update(changes)
            if (selected or "source_in" in changes) and shot.get("motion_plan"):
                shot["motion_plan"]["windows"] = [
                    w
                    for w in shot["motion_plan"]["windows"]
                    if w.get("basis") == "voice_hint"
                    or (manual_windows_submitted and w.get("basis") == "manual")
                ]
            from .shotcraft import effective_transitions

            def boundaries(value):
                return effective_transitions(
                    [{**s, "frames": round(s["duration"] * 30)} for s in value["shots"]]
                )

            if boundaries(board) != boundaries(original["storyboard"]):
                raise ValueError(
                    "此动作保护区间会改变相邻转场；单镜修订保留原转场。请保留边界区间，或在新草稿中整体调整转场。"
                )
            candidate = {**original, "id": jid, "assets": assets}
            board["creative"]["fingerprint"] = rebase_fingerprint(
                original, candidate, board["creative"]
            )
            board = validate_board(candidate, board)
            from .production import validate_production

            validate_production(board, assets)
            with self.store.transaction() as c:
                if receipt:
                    receipt.guard(c)
                self.row(c, pid, data["revision"])
                self.products._row(c, pid, p["product"]["revision"])
                if selected:
                    snapshot_guard(c, [selected])
                unchanged = self.store._row(c, original["id"])
                if (
                    unchanged["storyboard_revision"] != data["board_revision"]
                    or unchanged["status"] != original["status"]
                ):
                    raise Conflict("原版本已变化")
                inherited = confirmed_alignment(
                    c, original, original["assets"], original["storyboard"]
                )
                old_alignment = None
                if inherited:
                    old_alignment = dict(
                        c.execute(
                            "SELECT * FROM alignments WHERE id=?",
                            (board["creative"]["alignment_id"],),
                        ).fetchone()
                    )
                    board["creative"]["alignment_id"] = uid()
                self.insert_job(c, jid, original, assets, board, parent=original["id"])
                if old_alignment:
                    result = json.loads(old_alignment["result"])
                    result["inherited_from_alignment_id"] = old_alignment["id"]
                    c.execute(
                        "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            board["creative"]["alignment_id"],
                            jid,
                            old_alignment["fingerprint"],
                            "confirmed",
                            encoded(result),
                            None,
                            old_alignment["reviewer"],
                            time.time(),
                            old_alignment["updated_at"],
                        ),
                    )
                    confirmed_alignment(c, candidate, assets, board)
                notes = p["planning_notes"] + [
                    f"仅修改 {data['shot_id']}，其他镜头和配音保持；成片需要重新复核。"
                ]
                c.execute(
                    "INSERT INTO customer_jobs VALUES(?,?,?,?,?,?)",
                    (jid, pid, self.fingerprint(p), self.basis(p), encoded(notes), time.time()),
                )
                c.execute(
                    "INSERT INTO customer_edits VALUES(?,?,?,?,?,?)",
                    (data["request_id"], pid, original["id"], request_hash, jid, time.time()),
                )
                self.touch(c, pid, jid)
                if receipt:
                    receipt(c, jid)
        except BaseException:
            shutil.rmtree(self.root / "jobs" / jid, ignore_errors=True)
            raise
        return self.get(pid)


def validate_customer_submission(c, job):
    """Apply customer gates even when the legacy job submission endpoint is used."""
    version = c.execute("SELECT * FROM customer_jobs WHERE job_id=?", (job["id"],)).fetchone()
    if not version:
        return
    project = c.execute(
        "SELECT * FROM customer_projects WHERE product_id=?", (version["product_id"],)
    ).fetchone()
    product = dict(
        c.execute("SELECT * FROM products WHERE id=?", (version["product_id"],)).fetchone()
    )
    settings = json.loads(project["settings"])
    current = {
        "settings": settings,
        "product": product,
        "media": [
            dict(a)
            for a in c.execute(
                "SELECT * FROM customer_media WHERE product_id=? ORDER BY rowid",
                (version["product_id"],),
            )
        ],
    }
    attach(c, current["media"])
    if (
        project["active_job_id"] != job["id"]
        or product["status"] != "script_confirmed"
        or version["input_fingerprint"] != Customers.fingerprint(current)
    ):
        raise Conflict("客户项目输入或当前版本已变化，请重新准备")
    board = json.loads(job["storyboard"]) if job["storyboard"] else None
    if not board or not board.get("creative"):
        raise Conflict("请先选定推荐风格并生成客户分镜")
    if board["creative"]["brief"] != settings["brief"]:
        raise Conflict("分镜片种或制作要求与客户项目不一致，请重新准备")
    if settings["brief"]["format"] != "showcase" and board["narration"]["mode"] != "uploaded":
        raise Conflict("客户口播须使用上传的成品配音并完成听核")
