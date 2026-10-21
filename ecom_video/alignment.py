"""Local CPU alignment, immutable input identity, explicit human acceptance."""

import json
import sys
import threading
import time
import uuid
from pathlib import Path

from .creative import signature
from .db import Conflict
from .media import digest, input_options, run_checked, safe_path

PROJECT = Path(__file__).resolve().parent.parent
MODEL = PROJECT / "var/models/firered"
SCRIPT = PROJECT / "ecom_video/local_asr.py"
LOCK = threading.Lock()


def input_hash(job, asset):
    return signature(
        {
            "script": job["script"],
            "audio": asset["sha256"],
            "engine": "firered-ctc-int8-2026-02-25",
            "adapter": digest(SCRIPT),
        }
    )


def matches_input(row, job, asset):
    if row["fingerprint"] == input_hash(job, asset):
        return True
    result = row.get("result") if isinstance(row, dict) else row["result"]
    result = json.loads(result) if isinstance(result, str) else result
    if not isinstance(result, dict):
        return False
    adapter = result.get("adapter_sha256", "")
    if len(adapter) != 64 or any(c not in "0123456789abcdef" for c in adapter):
        return False
    if result.get("audio_sha256") != asset["sha256"] or result.get("engine") not in (
        "firered-ctc-int8",
        "single-shot-splice-v1",
    ):
        return False
    legacy = signature(
        {
            "script": job["script"],
            "audio": asset["sha256"],
            "engine": "firered-ctc-int8-2026-02-25",
            "adapter": adapter,
        }
    )
    return legacy == row["fingerprint"]


def validate_result(result, script, duration):
    if not isinstance(result, dict) or len(result.get("sentences", [])) != len(script.splitlines()):
        raise ValueError("对齐句数与脚本不一致")
    previous = 0
    for sent, line in zip(result["sentences"], script.splitlines(), strict=True):
        if sent["text"] != line or not sent.get("words"):
            raise ValueError("对齐文字与脚本不一致或没有锚点")
        # Text is immutable even when timestamps are edited.
        import re

        def normalized(s):
            return re.sub(r"[^\w\u3400-\u9fff]", "", s).lower()

        if normalized("".join(w["text"] for w in sent["words"])) != normalized(line):
            raise ValueError("字级内容不得改写脚本")
        for w in sent["words"]:
            start, end = float(w["start"]), float(w["end"])
            if not (previous <= start < end <= duration + 0.001):
                raise ValueError("时间戳必须有限、顺序单调且在配音时长内")
            if not isinstance(w.get("anchored"), bool):
                raise ValueError("缺少锚点来源标记")
            w["start"], w["end"] = start, end
            previous = end
        sent["start"] = sent["words"][0]["start"]
        sent["end"] = sent["words"][-1]["end"]
    return result


def confirmed_alignment(connection, job, assets, board):
    creative = board.get("creative")
    if not creative or not creative.get("alignment_id"):
        return None
    row = connection.execute(
        "SELECT * FROM alignments WHERE id=? AND job_id=?", (creative["alignment_id"], job["id"])
    ).fetchone()
    asset = next((a for a in assets if a["id"] == board["narration"]["asset_id"]), None)
    if not row or row["status"] != "confirmed" or not asset or not matches_input(row, job, asset):
        raise ValueError("口播对齐未确认或脚本/配音已变化，请重新对齐并听核")
    result = json.loads(row["result"])
    meta = asset["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else meta
    validate_result(result, job["script"], meta["duration"])
    position = 0
    for shot, sent in zip(board["shots"], result["sentences"], strict=True):
        end = position + shot["duration"]
        if sent["start"] < position - 0.034 or sent["end"] > end + 0.034:
            raise ValueError("分镜边界未覆盖对应口播，请应用对齐时间或调整分镜时长")
        position = end
    result["timing_review"] = {
        "reviewer": row["reviewer"],
        "confirmed_at": row["updated_at"],
        "input_fingerprint": row["fingerprint"],
        "automated_fixture": str(row["reviewer"]).startswith("AUTOMATED FIXTURE"),
    }
    return result


class AlignmentService:
    def __init__(self, root, store, recover=True):
        self.root = Path(root)
        self.store = store
        if not recover:
            return
        with store.transaction() as c:
            c.execute(
                "UPDATE alignments SET status='failed',error='服务中断，请重试',updated_at=? WHERE status='running'",
                (time.time(),),
            )

    def get(self, jid, aid):
        self.store.get(jid)
        with self.store.connect() as c:
            r = c.execute("SELECT * FROM alignments WHERE id=? AND job_id=?", (aid, jid)).fetchone()
        if not r:
            raise KeyError(aid)
        r = dict(r)
        r["result"] = json.loads(r["result"]) if r["result"] else None
        return r

    def start(self, jid, asset_id, *, receipt=None, before_start=None):
        job = self.store.get(jid)
        if job["status"] != "draft":
            raise Conflict("仅草稿可对齐")
        asset = next(
            (a for a in job["assets"] if a["id"] == asset_id and a["kind"] == "audio"), None
        )
        if not asset:
            raise ValueError("请选择本任务的配音")
        if not all((MODEL / f).is_file() for f in ["model.int8.onnx", "tokens.txt"]):
            raise ValueError("本机对齐模型未安装，请运行 scripts/setup_p5.py")
        from .resource_leases import Lease

        lease = Lease(self.store)
        if not lease.acquire():
            raise Conflict("本机正忙，请稍后对齐")
        lease.keepalive()
        if not LOCK.acquire(blocking=False):
            lease.release()
            raise Conflict("已有本机对齐任务运行，请稍后重试")
        aid = uuid.uuid4().hex
        try:
            if before_start:
                before_start()
            with self.store.transaction() as c:
                lease.guard(c)
                if receipt:
                    receipt.guard(c)
                c.execute(
                    "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        aid,
                        jid,
                        input_hash(job, asset),
                        "running",
                        None,
                        None,
                        None,
                        time.time(),
                        time.time(),
                    ),
                )
                if receipt:
                    receipt(c, aid, resource_token=lease.token)
            threading.Thread(target=self.run, args=(aid, job, asset, lease), daemon=True).start()
        except BaseException:
            LOCK.release()
            lease.release()
            raise
        return self.get(jid, aid)

    def run(self, aid, job, asset, lease=None):
        folder = self.root / "alignments" / aid
        folder.mkdir(parents=True, exist_ok=True)

        def check():
            from .agent_guard import check_target

            check_target(self.store, "alignment", aid)
            if lease:
                lease.check()
            current = self.store.get(job["id"])
            if (
                current["status"] != "draft"
                or current["script"] != job["script"]
                or self.get(job["id"], aid)["status"] != "running"
            ):
                raise Conflict("对齐已停止或任务内容已变化")

        try:
            check()
            source = safe_path(self.root, asset["path"])
            if digest(source) != asset["sha256"]:
                raise ValueError("配音文件已变化")
            wav = folder / "voice.wav"
            run_checked(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    *input_options(source),
                    "-i",
                    str(source),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(wav),
                ],
                check,
            )
            script_path = folder / "script.txt"
            script_path.write_text(job["script"])
            output = folder / "timestamps.json"
            try:
                run_checked(
                    [
                        sys.executable,
                        "-m",
                        "ecom_video.local_asr",
                        str(wav),
                        str(script_path),
                        str(MODEL),
                        str(output),
                    ],
                    check,
                    timeout=180,
                )
            except RuntimeError as exc:
                raise ValueError(
                    "本机语音识别未完成，请重试；若仍失败，请检查本机对齐模型。"
                ) from exc
            check()
            result = json.loads(output.read_text())
            from .alignment_recovery import VERSION, estimated_tts

            attempts = [
                {
                    "method": "original",
                    "coverage": result.get("diagnostic", {}).get("script_coverage"),
                }
            ]
            if result.get("diagnostic") and result.get("raw_words"):
                # Admission happens before the optional second inference, including Agent budgets.
                from .agent_guard import owner, reserve_call, scope

                rid = owner(self.store, "alignment", aid)
                if rid:
                    with scope(self.store, rid, check):
                        reserve_call()
                check()
                retry_output = folder / "retry-timestamps.json"
                run_checked(
                    [
                        sys.executable,
                        "-m",
                        "ecom_video.alignment_recovery",
                        str(wav),
                        str(script_path),
                        str(MODEL),
                        str(retry_output),
                    ],
                    check,
                    timeout=180,
                )
                recovered = json.loads(retry_output.read_text())
                attempts.append(
                    {
                        "method": "normalized_12s_windows",
                        "coverage": recovered.get("diagnostic", {}).get("script_coverage"),
                    }
                )
                if not recovered.get("diagnostic") or recovered.get("diagnostic", {}).get(
                    "script_coverage", 0
                ) > result.get("diagnostic", {}).get("script_coverage", 0):
                    result = recovered
                source_info = asset["metadata"].get("voice_source", {})
                import hashlib

                trusted = (
                    source_info.get("provider") in ("volcengine", "assembled")
                    and source_info.get("script_hash")
                    == hashlib.sha256(job["script"].encode()).hexdigest()
                )
                if trusted and result.get("diagnostic") and result.get("raw_words"):
                    original_diagnostic = result["diagnostic"]
                    try:
                        estimate = estimated_tts(
                            job["script"], result["raw_words"], asset["metadata"]["duration"]
                        )
                    except ValueError:
                        pass  # Different speech is never a timing-only repair.
                    else:
                        result = estimate
                        result["recovery"]["original_diagnostic"] = original_diagnostic
            result["attempts"] = attempts
            result["recovery_version"] = VERSION
            # Keep ASR evidence even for poor matches, never pretend interpolation is measured.
            result.update(
                engine="firered-ctc-int8",
                audio_sha256=asset["sha256"],
                model_sha256=digest(MODEL / "model.int8.onnx"),
                adapter_sha256=digest(SCRIPT),
            )
            diagnostic = result.get("diagnostic")
            if not diagnostic:
                validate_result(result, job["script"], asset["metadata"]["duration"])
            with self.store.transaction() as c:
                if lease:
                    lease.guard(c)
                c.execute(
                    "UPDATE alignments SET status=?,result=?,error=?,updated_at=? WHERE id=? AND status='running'",
                    (
                        "failed" if diagnostic else "needs_review",
                        json.dumps(result, ensure_ascii=False),
                        diagnostic["message"] if diagnostic else None,
                        time.time(),
                        aid,
                    ),
                )
        except BaseException as exc:
            with self.store.transaction() as c:
                c.execute(
                    "UPDATE alignments SET status='failed',error=?,updated_at=? WHERE id=?",
                    (str(exc)[:1000], time.time(), aid),
                )
        finally:
            LOCK.release()
            if lease:
                lease.release()

    def cancel(self, jid, aid):
        self.get(jid, aid)
        with self.store.transaction() as c:
            c.execute(
                "UPDATE alignments SET status='failed',error='用户停止对齐',updated_at=? WHERE id=? AND job_id=? AND status='running'",
                (time.time(), aid, jid),
            )
        return self.get(jid, aid)

    def confirm(self, jid, aid, result, reviewer):
        if not reviewer.strip():
            raise ValueError("请填写听核人")
        job = self.store.get(jid)
        row = self.get(jid, aid)
        if job["status"] != "draft" or row["status"] != "needs_review":
            raise Conflict("对齐状态已变化")
        asset = next(
            (a for a in job["assets"] if a["kind"] == "audio" and matches_input(row, job, a)),
            None,
        )
        if not asset:
            raise Conflict("脚本或配音已变化，请重新对齐")
        original = row["result"]
        proposed = result or original
        # Caller may edit timing only, not evidence/engine/match/source flags.
        if len(proposed.get("sentences", [])) != len(original["sentences"]):
            raise ValueError("不得增删对齐句子")
        for src, dst in zip(original["sentences"], proposed["sentences"], strict=True):
            if len(src["words"]) != len(dst["words"]):
                raise ValueError("不得增删字级锚点")
            for x, y in zip(src["words"], dst["words"], strict=True):
                x["start"] = y["start"]
                x["end"] = y["end"]
        validate_result(original, job["script"], asset["metadata"]["duration"])
        with self.store.transaction() as c:
            current = self.store._row(c, jid)
            if current["status"] != "draft" or current["script"] != job["script"]:
                raise Conflict("任务已变化")
            changed = c.execute(
                "UPDATE alignments SET status='confirmed',result=?,reviewer=?,updated_at=? WHERE id=? AND status='needs_review'",
                (json.dumps(original, ensure_ascii=False), reviewer, time.time(), aid),
            ).rowcount
            if not changed:
                raise Conflict("对齐结果已确认")
        return self.get(jid, aid)
