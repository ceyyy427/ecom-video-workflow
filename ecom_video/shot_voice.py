"""Single-sentence cloud retakes; preview is separate from manual adoption."""

import copy
import hashlib
import json
import math
import shutil
import sys
import time
import wave

import numpy as np

from . import voice_takes
from .alignment import MODEL, SCRIPT, confirmed_alignment, input_hash, validate_result
from .creative import signature
from .customer import uid
from .db import Conflict
from .media import digest, input_options, inspect_media, run_checked, safe_path
from .products import encoded
from .resource_leases import Lease
from .storyboard import validate_board

RATE = 24000
PAD = 0.15


def read_pcm(path):
    with wave.open(str(path), "rb") as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, RATE):
            raise ValueError("配音拼接需要24kHz单声道PCM")
        return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").copy()


def write_pcm(path, samples):
    with wave.open(str(path), "wb") as f:
        f.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        f.writeframes(np.asarray(samples, dtype="<i2").tobytes())


def splice(original, replacement, start, end, new_duration, output, lead=PAD):
    old, new = read_pcm(original), read_pcm(replacement)
    if (
        not 0 <= start < end
        or not 0.9 <= new_duration <= 15.1
        or len(new) + round(lead * RATE) > round(new_duration * RATE)
    ):
        raise ValueError("新句时长不在镜头边界内")
    old = np.pad(old, (0, max(0, round(end * RATE) - len(old))))
    slot = np.zeros(round(new_duration * RATE), dtype="<i2")
    offset = round(lead * RATE)
    slot[offset : offset + len(new)] = new
    combined = np.concatenate([old[: round(start * RATE)], slot, old[round(end * RATE) :]])
    write_pcm(output, combined)
    return len(combined) / RATE


def slot_bounds(board, alignment, index):
    start = sum(s["duration"] for s in board["shots"][:index])
    end = start + board["shots"][index]["duration"]
    sentence = alignment["sentences"][index]
    left = max(
        alignment["sentences"][index - 1]["end"] if index else 0, min(start, sentence["start"])
    )
    right = min(
        alignment["sentences"][index + 1]["start"]
        if index + 1 < len(board["shots"])
        else float("inf"),
        max(end, sentence["end"]),
    )
    if left > sentence["start"] + 0.0001 or right < sentence["end"] - 0.0001 or not left < right:
        raise Conflict("语句之间没有安全切点，请先校正本版听核时间")
    lead = (round((start + PAD) * RATE) - round(left * RATE)) / RATE
    if not 0.1 <= lead <= 0.2:
        raise Conflict("声音边界偏离镜头，请先校正听核时间")
    return left, right, lead


def slot_samples(start, end, delta):
    return round(end * RATE) - round(start * RATE) + round(delta * RATE)


def retime(board, alignment, index, segment, new_duration):
    b, a = copy.deepcopy(board), copy.deepcopy(alignment)
    position = sum(s["duration"] for s in b["shots"][:index])
    delta = new_duration - b["shots"][index]["duration"]
    b["shots"][index]["duration"] = new_duration
    changed = copy.deepcopy(segment["sentences"][0])
    changed["i"] = index
    for w in changed["words"]:
        w["start"] = round(w["start"] + position + PAD, 4)
        w["end"] = round(w["end"] + position + PAD, 4)
    changed["start"] = changed["words"][0]["start"]
    changed["end"] = changed["words"][-1]["end"]
    a["sentences"][index] = changed
    for sent in a["sentences"][index + 1 :]:
        for w in sent["words"]:
            w["start"] = w["start"] + delta
            w["end"] = w["end"] + delta
        sent["start"] = sent["words"][0]["start"]
        sent["end"] = sent["words"][-1]["end"]
    a["total"] = round(sum(s["duration"] for s in b["shots"]), 6)
    a.pop("timing_review", None)
    a["raw_words"] = []
    a["recovery"] = segment.get("recovery")
    return b, a


class ShotVoice:
    def __init__(self, voice):
        self.voice = voice
        self.root = voice.root
        self.store = voice.store
        self.customers = voice.customers

    def source(self, pid, data):
        p = self.customers.current(pid, data["revision"], data["job_id"], data["board_revision"])
        if (
            p["product"]["revision"] != data["product_revision"]
            or p["product"]["current_draft_id"] != data["draft_id"]
        ):
            raise Conflict("文稿版本已变化")
        self.voice.confirmed(pid, data["revision"], data["product_revision"], data["draft_id"])
        j = p["job"]
        b = j["storyboard"]
        if (
            not b
            or b["narration"]["mode"] != "uploaded"
            or j["status"] in ("queued", "validating", "rendering", "auditing")
        ):
            raise Conflict("请先完成配音听核和分镜，等待制作结束")
        with self.store.connect() as c:
            alignment = confirmed_alignment(c, j, j["assets"], b)
        if not alignment:
            raise Conflict("请先完成当前声音的人工听核")
        asset = next(a for a in j["assets"] if a["id"] == b["narration"]["asset_id"])
        if digest(safe_path(self.root, asset["path"])) != asset["sha256"]:
            raise Conflict("原配音文件已变化")
        basis = signature(
            {
                "project": p["revision"],
                "product": p["product"]["revision"],
                "job": j["id"],
                "board_revision": j["storyboard_revision"],
                "board": b,
                "audio": asset["sha256"],
                "alignment": alignment,
            }
        )
        return p, j, b, alignment, asset, basis

    @staticmethod
    def listing(c, pid):
        rows = c.execute(
            "SELECT * FROM voice_patches WHERE product_id=? ORDER BY created_at DESC,id DESC",
            (pid,),
        )
        return [
            {
                k: (json.loads(r[k]) if k in ("params", "alignment") else r[k])
                for k in (
                    "id",
                    "job_id",
                    "shot_id",
                    "board_revision",
                    "sentence_index",
                    "params",
                    "duration",
                    "alignment",
                    "result_job_id",
                    "reviewer",
                    "created_at",
                )
            }
            for r in rows
        ]

    def record(self, pid, tid):
        with self.store.connect() as c:
            row = c.execute(
                "SELECT * FROM voice_patches WHERE product_id=? AND id=?", (pid, tid)
            ).fetchone()
        if not row:
            raise KeyError(tid)
        return dict(row)

    def file(self, pid, tid, kind):
        row = self.record(pid, tid)
        if kind not in ("old", "new", "raw"):
            raise KeyError(kind)
        info = json.loads(row["files"])[kind]
        path = safe_path(self.root, info["path"])
        if not path.is_file() or digest(path) != info["sha256"]:
            raise Conflict("单句声音文件缺失或已变化")
        return path

    def generate(self, pid, shot_id, data):
        from .voice_profiles import PROFILES, VERSION
        from .volc_voice import MAX_AUDIO, SPEAKERS, read_config, synthesize

        with self.voice.lock(pid), Lease(self.store) as lease:
            p, j, b, a, asset, basis = self.source(pid, data)
            index = next((i for i, s in enumerate(b["shots"]) if s["shot_id"] == shot_id), None)
            if index is None:
                raise KeyError(shot_id)
            slot_bounds(b, a, index)
            profile = PROFILES.get(b["creative"]["style_id"])
            if not profile:
                raise ValueError("此旧风格暂不支持单句云配音，请使用三种客户商品风格")
            speaker = data.get("speaker") or profile["speaker"]
            if speaker not in SPEAKERS:
                raise ValueError("请选择支持的普通音色")
            if not all((MODEL / f).is_file() for f in ("model.int8.onnx", "tokens.txt")):
                raise ValueError("本机对齐模型未安装，未发起新的云请求")
            old_voice = next(x for x in p["media"] if x["role"] == "voice")
            with self.store.connect() as c:
                old_count = int(not voice_takes.saved_file(c, pid, old_voice))
                voice_takes.budget(c, pid, MAX_AUDIO + 3 * 1024**2, 2 + old_count)
            key, _ = read_config()
            text = j["script"].splitlines()[index]
            audio = synthesize(
                text,
                speaker,
                key,
                self.voice.transport,
                direction=profile["direction"],
                speech_rate=profile["speech_rate"],
            )
            tid = uid()
            folder = safe_path(self.root, f"customers/{pid}/voice-patches/{tid}")
            folder.mkdir(parents=True)
            committed = False
            try:

                def check():
                    lease.check()
                    if self.source(pid, data)[-1] != basis:
                        raise Conflict("分镜或声音已变化，本次结果未采用")

                check()
                (folder / "raw.mp3").write_bytes(audio)
                inspect_media(folder / "raw.mp3", "audio")
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(folder / "raw.mp3"),
                        "-ar",
                        str(RATE),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(folder / "speech.wav"),
                    ],
                    check,
                )
                seconds = len(read_pcm(folder / "speech.wav")) / RATE
                duration = max(1, math.ceil((seconds + 2 * PAD) * 30) / 30)
                if duration > 15:
                    raise ValueError("新句超过15秒，请拆分文稿后重新确认；原版未改变")
                start, end, lead = slot_bounds(b, a, index)
                slot_duration = (
                    slot_samples(start, end, duration - b["shots"][index]["duration"]) / RATE
                )
                self.decode(asset, folder / "full.wav", check)
                old = read_pcm(folder / "full.wav")
                old = np.pad(old, (0, max(0, round(end * RATE) - len(old))))
                write_pcm(folder / "old.wav", old[round(start * RATE) : round(end * RATE)])
                slot = np.zeros(round(slot_duration * RATE), dtype="<i2")
                speech = read_pcm(folder / "speech.wav")
                offset = round(lead * RATE)
                slot[offset : offset + len(speech)] = speech
                write_pcm(folder / "new.wav", slot)
                result = self.align_segment(folder, text, seconds, check)
                params = {
                    "provider": "volcengine",
                    "speaker": speaker,
                    "style_id": b["creative"]["style_id"],
                    "profile_version": VERSION,
                    "speech_rate": profile["speech_rate"],
                    "direction": profile["direction"],
                    "text": text,
                    "script_hash": hashlib.sha256(j["script"].encode()).hexdigest(),
                    "draft_id": data["draft_id"],
                    "source_audio_sha256": asset["sha256"],
                    "source_alignment_id": b["creative"]["alignment_id"],
                    "audio_start": start,
                    "audio_end": end,
                    "lead": lead,
                }
                files = {
                    k: {
                        "path": str((folder / name).relative_to(self.root)),
                        "sha256": digest(folder / name),
                        "size": (folder / name).stat().st_size,
                    }
                    for k, name in [("raw", "raw.mp3"), ("old", "old.wav"), ("new", "new.wav")]
                }
                size = sum(f["size"] for f in files.values())
                for name in (
                    "full.wav",
                    "speech.wav",
                    "script.txt",
                    "timestamps.json",
                    "asr.wav",
                    "retry.json",
                    "retry-chunk.wav",
                ):
                    (folder / name).unlink(missing_ok=True)
                with self.store.transaction() as c:
                    lease.guard(c)
                    self.customers.row(c, pid, data["revision"])
                    self.customers.products._row(c, pid, data["product_revision"])
                    current = self.store._row(c, j["id"])
                    if (
                        current["storyboard_revision"] != data["board_revision"]
                        or current["status"] != j["status"]
                    ):
                        raise Conflict("原版本已变化")
                    voice_takes.budget(c, pid, size, 1)
                    c.execute(
                        "INSERT INTO voice_patches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)",
                        (
                            tid,
                            pid,
                            j["id"],
                            data["board_revision"],
                            shot_id,
                            index,
                            basis,
                            encoded(params),
                            encoded(files),
                            size,
                            duration,
                            encoded(result),
                            time.time(),
                        ),
                    )
                committed = True
            finally:
                if not committed:
                    shutil.rmtree(folder, ignore_errors=True)
        return self.customers.get(pid)

    def decode(self, asset, dest, check):
        source = safe_path(self.root, asset["path"])
        if digest(source) != asset["sha256"]:
            raise Conflict("原声音文件已变化")
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
                str(RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(dest),
            ],
            check,
        )

    def align_segment(self, folder, text, duration, check):
        from .alignment_recovery import estimated_tts

        script = folder / "script.txt"
        script.write_text(text)
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(folder / "speech.wav"),
                "-ar",
                "16000",
                str(folder / "asr.wav"),
            ],
            check,
        )
        output = folder / "timestamps.json"
        run_checked(
            [
                sys.executable,
                "-m",
                "ecom_video.local_asr",
                str(folder / "asr.wav"),
                str(script),
                str(MODEL),
                str(output),
            ],
            check,
            timeout=180,
        )
        result = json.loads(output.read_text())
        attempts = ["original"]
        if result.get("diagnostic") and result.get("raw_words"):
            retry = folder / "retry.json"
            run_checked(
                [
                    sys.executable,
                    "-m",
                    "ecom_video.alignment_recovery",
                    str(folder / "asr.wav"),
                    str(script),
                    str(MODEL),
                    str(retry),
                ],
                check,
                timeout=180,
            )
            candidate = json.loads(retry.read_text())
            attempts.append("normalized_12s_windows")
            if not candidate.get("diagnostic") or candidate["diagnostic"].get(
                "script_coverage", 0
            ) > result["diagnostic"].get("script_coverage", 0):
                result = candidate
        if result.get("diagnostic") and result.get("raw_words"):
            try:
                estimate = estimated_tts(text, result["raw_words"], duration)
            except ValueError:
                pass
            else:
                estimate["recovery"]["original_diagnostic"] = result["diagnostic"]
                result = estimate
        result["attempts"] = attempts
        return result if result.get("diagnostic") else validate_result(result, text, duration)

    def apply(self, pid, tid, data):
        if not data["reviewer"].strip():
            raise ValueError("请填写采用声音的确认人")
        with self.voice.lock(pid), Lease(self.store) as lease:
            take = self.record(pid, tid)
            if take["result_job_id"]:
                return {
                    **self.customers.get(pid),
                    "voice_patch_result_job_id": take["result_job_id"],
                }
            p, j, b, a, asset, basis = self.source(pid, data)
            if take["job_id"] != j["id"] or take["basis"] != basis:
                raise Conflict("这条试听来自旧分镜/声音，请在当前版本重新生成")
            for kind in ("old", "new", "raw"):
                self.file(pid, tid, kind)
            segment = json.loads(take["alignment"])
            if segment.get("diagnostic"):
                raise Conflict("新句识别内容仍需核对，可以试听但不能直接采用；原版未改变")
            index = take["sentence_index"]
            b, result = retime(b, a, index, segment, take["duration"])
            if result["total"] > 120:
                raise ValueError("新配音使成片超过120秒，原版未改变")
            jid, alignment_id, libid = uid(), uid(), uid()
            relative = f"customers/{pid}/media/{libid}.wav"
            full = safe_path(self.root, relative)
            full.parent.mkdir(exist_ok=True, parents=True)
            temp = safe_path(self.root, f"customers/{pid}/voice-patches/{tid}/assembly")
            temp.mkdir(exist_ok=True)
            committed = False
            try:

                def check():
                    lease.check()
                    if self.source(pid, data)[-1] != basis:
                        raise Conflict("项目或分镜已变化")

                check()
                with self.store.connect() as c:
                    voice_takes.budget(c, pid, round(result["total"] * RATE * 2) + 44, 2)
                self.decode(asset, temp / "old.wav", check)
                original = read_pcm(temp / "old.wav")
                length = round(sum(s["duration"] for s in j["storyboard"]["shots"]) * RATE)
                original = np.pad(original, (0, max(0, length - len(original))))
                write_pcm(temp / "old.wav", original)
                # Use unpadded PCM decoded from the retained provider response.
                run_checked(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(self.file(pid, tid, "raw")),
                        "-ar",
                        str(RATE),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(temp / "speech.wav"),
                    ],
                    check,
                )
                start, end, lead = slot_bounds(j["storyboard"], a, index)
                slot_duration = (
                    slot_samples(
                        start, end, take["duration"] - j["storyboard"]["shots"][index]["duration"]
                    )
                    / RATE
                )
                splice(
                    temp / "old.wav",
                    temp / "speech.wav",
                    start,
                    end,
                    slot_duration,
                    full,
                    lead=lead,
                )
                metadata = inspect_media(full, "audio")
                params = json.loads(take["params"])
                metadata["voice_source"] = {
                    **params,
                    "provider": "assembled",
                    "take_id": libid,
                    "voice_patch_id": tid,
                    "parent_job_id": j["id"],
                    "human_listening": "pending",
                }
                library = {
                    "id": libid,
                    "name": f"第{index + 1}镜换声后的完整配音.wav",
                    "path": relative,
                    "kind": "audio",
                    "role": "voice",
                    "sha256": digest(full),
                    "size": full.stat().st_size,
                    "metadata": metadata,
                    "source_in": 0.0,
                    "note": "",
                }
                assets, mapping = self.customers.copy_assets(jid, j["assets"])
                old_copy = next(x for x in assets if x["id"] == mapping[asset["id"]])
                safe_path(self.root, old_copy["path"]).unlink()
                assets.remove(old_copy)
                extra, _ = self.customers.copy_assets(jid, [library], library=True)
                new_voice = extra[0]
                assets += extra
                mapping[asset["id"]] = new_voice["id"]
                for shot in b["shots"]:
                    shot["asset_id"] = mapping[shot["asset_id"]]
                from .delivery_plan import remap_cuts

                remap_cuts(b, mapping)
                if b["music_id"]:
                    b["music_id"] = mapping[b["music_id"]]
                b["narration"]["asset_id"] = new_voice["id"]
                b["creative"]["alignment_id"] = alignment_id
                candidate = {**j, "id": jid, "assets": assets}
                from .creative import rebase_fingerprint

                b["creative"]["fingerprint"] = rebase_fingerprint(j, candidate, b["creative"])
                b = validate_board(candidate, b)
                from .production import validate_production

                validate_production(b, assets)
                result.update(
                    engine="single-shot-splice-v1",
                    adapter_sha256=digest(SCRIPT),
                    parent_adapter_sha256=a.get("adapter_sha256"),
                    audio_sha256=library["sha256"],
                    parent_alignment_id=j["storyboard"]["creative"]["alignment_id"],
                    voice_patch_id=tid,
                    changed_sentence_index=index,
                )
                validate_result(result, j["script"], metadata["duration"])
                with self.store.transaction() as c:
                    lease.guard(c)
                    self.customers.row(c, pid, data["revision"])
                    self.customers.products._row(c, pid, data["product_revision"])
                    row = self.store._row(c, j["id"])
                    if (
                        row["storyboard_revision"] != data["board_revision"]
                        or row["status"] != j["status"]
                    ):
                        raise Conflict("原分镜已变化")
                    old = c.execute(
                        "SELECT * FROM customer_media WHERE product_id=? AND role='voice'", (pid,)
                    ).fetchone()
                    if not old or old["sha256"] != asset["sha256"]:
                        raise Conflict("当前声音已变化")
                    voice_takes.budget(
                        c, pid, library["size"], 1 + int(not voice_takes.saved_file(c, pid, old))
                    )
                    voice_takes.archive(c, dict(old), pid)
                    c.execute("DELETE FROM customer_media WHERE id=?", (old["id"],))
                    voice_takes.insert(
                        c,
                        library,
                        pid,
                        data["draft_id"],
                        params["script_hash"],
                        "full",
                        metadata["voice_source"],
                        signature({"patch": tid}),
                    )
                    c.execute(
                        "INSERT INTO customer_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            libid,
                            pid,
                            library["name"],
                            relative,
                            "audio",
                            "voice",
                            library["sha256"],
                            library["size"],
                            encoded(metadata),
                            0,
                            "",
                            time.time(),
                        ),
                    )
                    self.customers.insert_job(c, jid, j, assets, b, parent=j["id"])
                    c.execute(
                        "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            alignment_id,
                            jid,
                            input_hash(candidate, new_voice),
                            "needs_review",
                            encoded(result),
                            None,
                            None,
                            time.time(),
                            time.time(),
                        ),
                    )
                    p["media"] = [x for x in p["media"] if x["id"] != old["id"]] + [library]
                    notes = p["planning_notes"] + [
                        f"仅重做第{index + 1}镜配音；其他镜头原音与局部节奏保留。目标动作需重新试听核对，新版待听核和审片。"
                    ]
                    c.execute(
                        "INSERT INTO customer_jobs VALUES(?,?,?,?,?,?)",
                        (
                            jid,
                            pid,
                            self.customers.fingerprint(p),
                            self.customers.basis(p),
                            encoded(notes),
                            time.time(),
                        ),
                    )
                    c.execute(
                        "UPDATE voice_patches SET result_job_id=?,reviewer=? WHERE id=? AND result_job_id IS NULL",
                        (jid, data["reviewer"], tid),
                    )
                    self.customers.touch(c, pid, jid)
                committed = True
            finally:
                shutil.rmtree(temp, ignore_errors=True)
                if not committed:
                    full.unlink(missing_ok=True)
                    shutil.rmtree(self.root / "jobs" / jid, ignore_errors=True)
        return self.customers.get(pid)
