"""Single-sentence retakes, never rewrite the confirmed product script."""

import copy
import json
import wave

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def private_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("DOUBAO_TTS_API_KEY", raising=False)
    from ecom_video import alignment, shot_voice

    # These tests replace ASR/transport; readiness and receipt hashing must not
    # depend on a developer's real model weights in the repository's var/.
    model = tmp_path / "fixture-model"
    model.mkdir()
    (model / "model.int8.onnx").write_bytes(b"not-a-real-model-test-fixture")
    (model / "tokens.txt").write_text("fixture-token\n")
    monkeypatch.setattr(alignment, "MODEL", model)
    monkeypatch.setattr(shot_voice, "MODEL", model)


def test_splice_preserves_other_samples_and_retimes_only_target(tmp_path):
    from ecom_video.shot_voice import splice

    rate = 24000
    old = np.arange(rate * 6, dtype=np.int16)
    new = np.full(rate * 2, 99, dtype=np.int16)
    for name, samples in [("old", old), ("new", new)]:
        with wave.open(str(tmp_path / (name + ".wav")), "wb") as f:
            f.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            f.writeframes(samples.tobytes())
    duration = splice(tmp_path / "old.wav", tmp_path / "new.wav", 2, 4, 2.3, tmp_path / "out.wav")
    with wave.open(str(tmp_path / "out.wav"), "rb") as f:
        result = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
    assert duration == pytest.approx(6.3)
    assert np.array_equal(result[: 2 * rate], old[: 2 * rate])
    assert np.array_equal(result[-2 * rate :], old[-2 * rate :])


def test_timeline_preserves_shots_and_local_words():
    from ecom_video.shot_voice import retime

    board = {
        "shots": [
            {"shot_id": str(i), "duration": 2, "source_in": i, "headline": "字卡"} for i in range(3)
        ]
    }
    alignment = {
        "sentences": [
            {
                "i": i,
                "text": str(i),
                "start": 2 * i + 0.2,
                "end": 2 * i + 1.4,
                "words": [
                    {"text": str(i), "start": 2 * i + 0.2, "end": 2 * i + 1.4, "anchored": True}
                ],
                "match": 1,
                "ok": True,
            }
            for i in range(3)
        ]
    }
    before = copy.deepcopy((board, alignment))
    segment = {
        "sentences": [
            {
                "i": 0,
                "text": "1",
                "start": 0.1,
                "end": 2.2,
                "words": [{"text": "1", "start": 0.1, "end": 2.2, "anchored": True}],
                "match": 1,
                "ok": True,
            }
        ]
    }
    b, a = retime(board, alignment, 1, segment, 2.5)
    assert (board, alignment) == before
    assert b["shots"][0] == board["shots"][0] and b["shots"][2] == board["shots"][2]
    assert b["shots"][1]["duration"] == 2.5
    assert a["sentences"][0] == alignment["sentences"][0]
    assert a["sentences"][2]["start"] == pytest.approx(4.7)
    assert a["sentences"][1]["start"] == pytest.approx(2.25)
    assert a["sentences"][2]["words"][0]["anchored"] is True


def test_trusted_tts_estimate_never_claims_measured_words_or_changes_script():
    from ecom_video.alignment_recovery import estimated_tts

    script = "这一句是商品的原稿。"
    raw = [{"text": "商品的", "start": 0.2, "end": 1.5}]
    result = estimated_tts(script, raw, 2)
    assert result["sentences"][0]["text"] == script
    assert not any(w["anchored"] for w in result["sentences"][0]["words"])
    assert result["recovery"]["method"] == "tts_receipt_estimate"
    assert result["raw_words"] == raw
    with pytest.raises(ValueError):
        estimated_tts(script, [], 2)


def setup_project(tmp_path, monkeypatch, legacy_context=False):
    from test_customer import approve, picture, prepare, project
    from test_volc_voice import configured

    from ecom_video.alignment import input_hash
    from ecom_video.local_asr import align

    c, _ = configured(tmp_path, monkeypatch)
    p = approve(c, picture(c, project(c)))
    base = "/api/customer-projects/" + p["id"]
    product = p["product"]
    facts = product["facts"][:2]
    product = c.post(
        "/api/products/" + p["id"] + "/scripts",
        json={
            "revision": product["revision"],
            "scenes": [{"text": f["text"], "fact_ids": [f["id"]]} for f in facts],
        },
    ).json()
    c.post(
        "/api/products/" + p["id"] + "/scripts/confirm",
        json={
            "revision": product["revision"],
            "draft_id": product["current_draft_id"],
            "reviewer": "AUTOMATED FIXTURE",
            "note": "fixture",
            "confirmed": True,
            "seconds": 2,
        },
    )
    p = c.get(base).json()
    p = c.put(
        base,
        json={
            "revision": p["revision"],
            "settings": {**p["settings"], "brief": {"format": "narrated"}},
        },
    ).json()
    audio = tmp_path / "original.wav"
    samples = np.arange(24000 * 4, dtype=np.int16)
    with wave.open(str(audio), "wb") as f:
        f.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        f.writeframes(samples.tobytes())
    p = c.post(
        base + "/assets",
        data={"revision": p["revision"], "role": "voice"},
        files={"file": ("old.wav", audio.read_bytes(), "audio/wav")},
    ).json()
    p = prepare(c, p)
    j = p["job"]
    voice = next(a for a in j["assets"] if a["metadata"].get("customer_role") == "voice")
    result = align(
        j["script"],
        [
            {"text": t, "start": i * 2 + 0.2, "end": i * 2 + 1.6}
            for i, t in enumerate(j["script"].splitlines())
        ],
        4,
    )
    aid = "a" * 32
    with c.app.state.volc_voice.store.transaction() as db:
        db.execute(
            "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
            (
                aid,
                j["id"],
                input_hash(j, voice),
                "confirmed",
                json.dumps(result),
                None,
                "AUTOMATED FIXTURE",
                1,
                1,
            ),
        )
    p = c.get(base).json()
    p = c.post(
        base + "/plan",
        json={
            "revision": p["revision"],
            "job_id": j["id"],
            "board_revision": j["storyboard_revision"],
            "style_id": "social",
            "fingerprint": p["recommendations"]["fingerprint"],
            "alignment_id": aid,
        },
    ).json()
    assert p.get("job"), p
    if legacy_context:
        from ecom_video.creative import fingerprint
        from ecom_video.customer import Customers

        p["settings"]["brief"].update(category="家居", audience="办公室咖啡爱好者", tone="安静自然")
        store = c.app.state.volc_voice.store
        with store.transaction() as db:
            db.execute(
                "UPDATE customer_projects SET settings=? WHERE product_id=?",
                (json.dumps(p["settings"]), p["id"]),
            )
            db.execute(
                "UPDATE customer_jobs SET input_fingerprint=?,basis_fingerprint=? WHERE job_id=?",
                (Customers.fingerprint(p), Customers.basis(p), p["job"]["id"]),
            )
        board = p["job"]["storyboard"]
        board["creative"]["brief"] = p["settings"]["brief"]
        board["creative"]["fingerprint"] = fingerprint(p["job"], p["settings"]["brief"])
        store.save_storyboard(j["id"], board, p["job"]["storyboard_revision"])
        p = c.get(base).json()
    return c, p


def request_body(p):
    return {
        "revision": p["revision"],
        "product_revision": p["product"]["revision"],
        "draft_id": p["product"]["current_draft_id"],
        "job_id": p["job"]["id"],
        "board_revision": p["job"]["storyboard_revision"],
    }


@pytest.mark.parametrize("legacy_context", [False, True])
def test_preview_only_sends_selected_sentence_and_apply_is_atomic(
    tmp_path, monkeypatch, legacy_context
):
    import httpx
    from test_volc_voice import mp3 as make_mp3
    from test_volc_voice import sse

    from ecom_video.local_asr import align

    c, p = setup_project(tmp_path, monkeypatch, legacy_context=legacy_context)
    base = "/api/customer-projects/" + p["id"]
    calls = []
    audio = make_mp3.__wrapped__(tmp_path)
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, content=sse(audio))
    )
    service = c.app.state.shot_voice
    monkeypatch.setattr(
        service,
        "align_segment",
        lambda folder, text, duration, check: align(
            text, [{"text": text, "start": 0.1, "end": duration - 0.05}], duration
        ),
    )
    body = request_body(p)
    shot = p["job"]["storyboard"]["shots"][1]["shot_id"]
    old_job = copy.deepcopy(p["job"])
    old_media = copy.deepcopy(p["media"])
    r = c.post(base + "/voice/shots/" + shot + "/takes", json={**body, "external_consent": True})
    assert r.status_code == 201, r.text
    preview = r.json()
    assert (
        preview["revision"] == p["revision"]
        and preview["job"] == old_job
        and preview["media"] == old_media
    )
    take = preview["voice_patches"][0]
    assert (
        len(calls) == 1
        and json.loads(calls[0].content)["req_params"]["text"] == old_job["script"].splitlines()[1]
    )
    assert c.get(base + "/voice/shots/takes/" + take["id"] + "/old").status_code == 200
    assert c.get(base + "/voice/shots/takes/" + take["id"] + "/new").status_code == 200
    assert (
        c.post(
            base + "/voice/shots/takes/" + take["id"] + "/use",
            json={**body, "reviewer": "AUTOMATED FIXTURE", "confirmed": False},
        ).status_code
        == 422
    )
    r = c.post(
        base + "/voice/shots/takes/" + take["id"] + "/use",
        json={**body, "reviewer": "AUTOMATED FIXTURE", "confirmed": True},
    )
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["job"]["id"] != old_job["id"] and new["job"]["parent_id"] == old_job["id"]
    assert (
        new["job"]["script"] == old_job["script"]
        and new["alignment"]["status"] == "needs_review"
        and not new["inputs_changed"]
    )
    denied = c.post("/api/jobs/" + new["job"]["id"] + "/submit")
    assert denied.status_code in (409, 422) and "对齐" in denied.text
    heard = c.post(
        "/api/jobs/" + new["job"]["id"] + "/alignments/" + new["alignment"]["id"] + "/confirm",
        json={"reviewer": "AUTOMATED FIXTURE", "confirmed": True},
    )
    assert heard.status_code == 200, heard.text
    allowed = c.post(
        base + "/submit",
        json={
            "revision": new["revision"],
            "job_id": new["job"]["id"],
            "board_revision": new["job"]["storyboard_revision"],
        },
    )
    assert allowed.status_code == 200, allowed.text
    assert c.get("/api/jobs/" + old_job["id"]).json() == old_job
    assert (
        new["job"]["storyboard"]["shots"][0]["duration"]
        == old_job["storyboard"]["shots"][0]["duration"]
    )
    assert (
        new["job"]["storyboard"]["shots"][0]["source_in"]
        == old_job["storyboard"]["shots"][0]["source_in"]
    )
    original = next(a for a in old_job["assets"] if a["metadata"].get("customer_role") == "voice")
    changed = next(a for a in new["job"]["assets"] if a["metadata"].get("customer_role") == "voice")
    from ecom_video.shot_voice import read_pcm

    old = read_pcm(c.app.state.volc_voice.root / original["path"])
    composite = read_pcm(c.app.state.volc_voice.root / changed["path"])
    assert np.array_equal(old[:48000], composite[:48000])
    repeat = c.post(
        base + "/voice/shots/takes/" + take["id"] + "/use",
        json={**body, "reviewer": "AUTOMATED FIXTURE", "confirmed": True},
    )
    assert (
        repeat.status_code == 200
        and repeat.json()["job"]["id"] == new["job"]["id"]
        and len(calls) == 1
    )


@pytest.mark.parametrize("trusted,retry_ok", [(False, True), (False, False), (True, False)])
def test_alignment_repair_is_bounded_and_does_not_forge_uploads(
    tmp_path, monkeypatch, trusted, retry_ok
):
    import hashlib

    from ecom_video import alignment as module
    from ecom_video.local_asr import align

    c, p = setup_project(tmp_path, monkeypatch)
    store = c.app.state.volc_voice.store
    j = p["job"]
    asset = next(a for a in j["assets"] if a["metadata"].get("customer_role") == "voice")
    if trusted:
        asset["metadata"]["voice_source"] = {
            "provider": "volcengine",
            "script_hash": hashlib.sha256(j["script"].encode()).hexdigest(),
        }
    aid = "b" * 32
    with store.transaction() as db:
        db.execute(
            "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
            (aid, j["id"], module.input_hash(j, asset), "running", None, None, None, 1, 1),
        )
    real = module.run_checked
    calls = []
    poor = {
        "sentences": [],
        "total": 4,
        "sr": 16000,
        "raw_words": [{"text": "奶白色" if trusted else "商品", "start": 0.2, "end": 3.5}],
        "diagnostic": {
            "code": "script_mismatch",
            "script": j["script"],
            "transcript": "商品",
            "duration": 4,
            "script_coverage": 0.05,
            "message": "配音与稿件匹配不足",
        },
    }

    def run(cmd, check, **kw):
        if cmd[0] == "ffmpeg":
            return real(cmd, check, **kw)
        calls.append(cmd[2])
        check()
        value = poor
        if retry_ok and cmd[2] == "ecom_video.alignment_recovery":
            value = align(
                j["script"],
                [
                    {"text": t, "start": 2 * i + 0.1, "end": 2 * i + 1.5}
                    for i, t in enumerate(j["script"].splitlines())
                ],
                4,
            )
            value["raw_words"] = poor["raw_words"]
        __import__("pathlib").Path(cmd[-1]).write_text(json.dumps(value))

    monkeypatch.setattr(module, "run_checked", run)
    service = module.AlignmentService(c.app.state.volc_voice.root, store, recover=False)
    assert module.LOCK.acquire(blocking=False)
    service.run(aid, j, asset)
    row = service.get(j["id"], aid)
    assert calls == ["ecom_video.local_asr", "ecom_video.alignment_recovery"]
    assert row["status"] == ("needs_review" if trusted or retry_ok else "failed")
    assert len(row["result"]["attempts"]) == 2
    if trusted and not retry_ok:
        assert row["result"]["recovery"]["method"] == "tts_receipt_estimate"
        assert not any(w["anchored"] for s in row["result"]["sentences"] for w in s["words"])
    if not trusted and not retry_ok:
        assert row["result"]["diagnostic"]["script"] == j["script"]


def test_even_trusted_receipt_cannot_estimate_unrelated_speech():
    from ecom_video.alignment_recovery import estimated_tts

    with pytest.raises(ValueError, match="不同|证据"):
        estimated_tts(
            "奶白色杯身深色杯盖", [{"text": "完全无关的其他话题", "start": 0.1, "end": 3.8}], 4
        )


def test_slot_bounds_protect_adjacent_voice_inside_frame_tolerance():
    from ecom_video.shot_voice import slot_bounds

    board = {"shots": [{"duration": 2}, {"duration": 2}]}
    alignment = {"sentences": [{"start": 0.2, "end": 2.02}, {"start": 2.2, "end": 3.8}]}
    start, end, lead = slot_bounds(board, alignment, 1)
    assert start == pytest.approx(2.02) and end == 4 and lead == pytest.approx(0.13)


def test_legacy_approved_adapter_identity_stays_readable_without_mutating_approval(
    tmp_path, monkeypatch
):
    from ecom_video.creative import signature

    c, p = setup_project(tmp_path, monkeypatch)
    job = p["job"]
    voice = next(a for a in job["assets"] if a["metadata"].get("customer_role") == "voice")
    alignment = p["alignment"]
    result = alignment["result"]
    result.update(engine="firered-ctc-int8", audio_sha256=voice["sha256"], adapter_sha256="f" * 64)
    old_fingerprint = signature(
        {
            "script": job["script"],
            "audio": voice["sha256"],
            "engine": "firered-ctc-int8-2026-02-25",
            "adapter": "f" * 64,
        }
    )
    with c.app.state.volc_voice.store.transaction() as db:
        db.execute(
            "UPDATE alignments SET fingerprint=?,result=? WHERE id=?",
            (old_fingerprint, json.dumps(result), alignment["id"]),
        )
    fetched = c.get("/api/customer-projects/" + p["id"]).json()
    assert fetched["alignment"]["fingerprint"] == old_fingerprint
    assert fetched["alignment"]["status"] == "confirmed"


def test_estimate_rejects_implausible_rate_inside_actual_speech_span():
    from ecom_video.alignment_recovery import estimated_tts

    with pytest.raises(ValueError):
        estimated_tts(
            "商品杯" + ("这是商品材质与使用情况的详细说明" * 3),
            [{"text": "商品杯", "start": 5, "end": 5.6}],
            20,
        )


def test_sample_quantization_uses_both_endpoints():
    from ecom_video.shot_voice import RATE, slot_samples

    start, end = 2.0201, 3.9802
    original = 6 * RATE
    deleted = round(end * RATE) - round(start * RATE)
    assert slot_samples(start, end, 0) == deleted
    assert (
        round(start * RATE) + slot_samples(start, end, 0.5) + original - round(end * RATE)
        == original + 12000
    )


def test_shot_request_guards_and_tampering_never_replace_parent(tmp_path, monkeypatch):
    import httpx
    from test_customer import project
    from test_volc_voice import mp3 as make_mp3
    from test_volc_voice import sse

    from ecom_video import voice_takes
    from ecom_video.local_asr import align

    c, p = setup_project(tmp_path, monkeypatch)
    base = "/api/customer-projects/" + p["id"]
    body = request_body(p)
    shot = p["job"]["storyboard"]["shots"][0]["shot_id"]
    calls = []
    audio = make_mp3.__wrapped__(tmp_path)
    c.app.state.volc_voice.transport = httpx.MockTransport(
        lambda req: calls.append(req) or httpx.Response(200, content=sse(audio))
    )
    endpoint = base + "/voice/shots/" + shot + "/takes"
    for change in [
        {"external_consent": False},
        {"speaker": "arbitrary"},
        {"text": "unapproved"},
        {"board_revision": 999},
    ]:
        r = c.post(endpoint, json={**body, "external_consent": True, **change})
        assert r.status_code in (409, 422)
    monkeypatch.setattr(voice_takes, "MAX_TAKES", 0)
    assert c.post(endpoint, json={**body, "external_consent": True}).status_code == 422
    assert not calls
    monkeypatch.setattr(voice_takes, "MAX_TAKES", 40)
    monkeypatch.setattr(
        c.app.state.shot_voice,
        "align_segment",
        lambda folder, text, duration, check: align(
            text, [{"text": text, "start": 0.1, "end": duration - 0.05}], duration
        ),
    )
    result = c.post(endpoint, json={**body, "external_consent": True})
    assert result.status_code == 201, result.text
    take = result.json()["voice_patches"][0]
    other = project(c, "other")
    assert (
        c.get(
            "/api/customer-projects/" + other["id"] + "/voice/shots/takes/" + take["id"] + "/new"
        ).status_code
        == 404
    )
    row = c.app.state.shot_voice.record(p["id"], take["id"])
    info = json.loads(row["files"])["new"]
    (c.app.state.volc_voice.root / info["path"]).write_bytes(b"tampered")
    assert c.get(base + "/voice/shots/takes/" + take["id"] + "/new").status_code == 409
    r = c.post(
        base + "/voice/shots/takes/" + take["id"] + "/use",
        json={**body, "reviewer": "AUTOMATED FIXTURE", "confirmed": True},
    )
    assert r.status_code == 409 and len(calls) == 1
    after = c.get(base).json()
    assert (
        after["job"] == p["job"]
        and after["media"] == p["media"]
        and after["revision"] == p["revision"]
    )


def test_frame_local_timing_signed_zero_does_not_invalidate_other_shot_cache():
    from ecom_video.creative import signature
    from ecom_video.remotion_renderer import frame_local_time

    assert signature({"start": frame_local_time(11.2, 11.2)}) == signature(
        {"start": frame_local_time(10.466666666666665, 10.466666666666667)}
    )
