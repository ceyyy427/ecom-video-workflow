import pytest

from ecom_video.creative import Brief, recommend, validate_creative


def fixture():
    return {
        "title": "陶瓷杯",
        "script": "看杯口细节\n放到桌上",
        "assets": [{"id": "a", "sha256": "abc", "kind": "image", "name": "hero.png"}],
    }


def test_three_deterministic_material_aware_choices():
    j = fixture()
    a = recommend(j, Brief(category="家居", audience="办公", tone="安静"))
    assert len(a["options"]) == 3
    assert len({x["id"] for x in a["options"]}) == 3
    assert a == recommend(j, Brief(category="家居", audience="办公", tone="安静"))
    assert all(x["reason"] and x["missing"] is not None for x in a["options"])


def test_selection_is_bound_to_input_and_recommendations():
    j = fixture()
    r = recommend(j, Brief())
    c = {
        "brief": r["brief"],
        "fingerprint": r["fingerprint"],
        "style_id": r["options"][0]["id"],
        "brand": {},
        "alignment_id": None,
        "sfx": False,
    }
    validate_creative(j, c)
    j["script"] = "更换脚本"
    with pytest.raises(ValueError, match="重新推荐"):
        validate_creative(j, c)


def test_contrast_and_claim_boundary(tmp_path):
    import copy

    from test_storyboard import draft

    from ecom_video.storyboard import default_board, validate_board

    store, j = draft(tmp_path)
    b = default_board(j)
    r = recommend(j, Brief())
    b["creative"] = {
        "brief": r["brief"],
        "fingerprint": r["fingerprint"],
        "style_id": r["options"][0]["id"],
    }
    for i, s in enumerate(b["shots"]):
        s["shot_id"] = f"shot-{i}"
    validate_board(j, b)
    bad = copy.deepcopy(b)
    bad["shots"][0]["headline"] = "保证有效"
    with pytest.raises(ValueError, match="动态字卡"):
        validate_board(j, bad)
    bad = copy.deepcopy(b)
    bad["creative"]["brand"] = {"ink": "#eeeeee", "paper": "#ffffff"}
    with pytest.raises(ValueError, match="对比度"):
        validate_board(j, bad)
    bad = copy.deepcopy(b)
    bad["shots"][1]["shot_id"] = bad["shots"][0]["shot_id"]
    with pytest.raises(ValueError, match="唯一"):
        validate_board(j, bad)


def test_alignment_matching_and_interpolation():
    from ecom_video.alignment import validate_result
    from ecom_video.local_asr import align

    raw = [{"text": "杯", "start": 0.2, "end": 0.4}, {"text": "好", "start": 0.8, "end": 1}]
    result = align("杯子好", raw, 1.2)
    assert [w["anchored"] for w in result["sentences"][0]["words"]] == [True, False, True]
    validate_result(result, "杯子好", 1.2)
    result["sentences"][0]["words"][0]["start"] = float("nan")
    with pytest.raises(ValueError, match="时间戳"):
        validate_result(result, "杯子好", 1.2)
    with pytest.raises(ValueError, match="匹配不足"):
        align("完全无关", raw, 1.2)


def test_alignment_confirmation_is_input_bound_and_immutable(tmp_path):
    import json
    import time

    from test_storyboard import draft

    from ecom_video.alignment import AlignmentService, confirmed_alignment, input_hash
    from ecom_video.db import Conflict
    from ecom_video.local_asr import align
    from ecom_video.storyboard import default_board

    store, j = draft(tmp_path)
    store.add_asset(
        j["id"],
        {
            "id": "audio",
            "name": "a",
            "kind": "audio",
            "path": "audio.wav",
            "sha256": "voice",
            "size": 10,
            "metadata": {"duration": 4},
        },
    )
    j = store.get(j["id"])
    audio = j["assets"][-1]
    result = align(
        j["script"],
        [
            {"text": "展示外观", "start": 0.2, "end": 1.8},
            {"text": "查看细节", "start": 2.1, "end": 3.8},
        ],
        4,
    )
    aid = "a" * 32
    with store.transaction() as c:
        c.execute(
            "INSERT INTO alignments VALUES(?,?,?,?,?,?,?,?,?)",
            (
                aid,
                j["id"],
                input_hash(j, audio),
                "needs_review",
                json.dumps(result),
                None,
                None,
                time.time(),
                time.time(),
            ),
        )
    svc = AlignmentService(tmp_path, store)
    b = default_board(j)
    b["creative"] = {"alignment_id": aid}
    b["narration"].update(mode="uploaded", asset_id="audio")
    with store.connect() as c, pytest.raises(ValueError, match="未确认"):
        confirmed_alignment(c, j, j["assets"], b)
    svc.confirm(j["id"], aid, None, "fixture")
    with store.connect() as c:
        assert confirmed_alignment(c, j, j["assets"], b)
    with pytest.raises(Conflict):
        svc.confirm(j["id"], aid, None, "again")
    j["script"] = "新脚本"
    with store.connect() as c, pytest.raises(ValueError, match="变化"):
        confirmed_alignment(c, j, j["assets"], b)


def test_recommend_api_token_and_foreign_alignment(tmp_path):
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app

    c = TestClient(create_app(tmp_path), base_url="http://localhost")
    assert c.post("/api/jobs/no/creative/recommend", json={}).status_code == 403
    c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
    j = c.post("/api/jobs", json={"title": "测试", "script": "看看商品"}).json()
    assert len(c.post(f"/api/jobs/{j['id']}/creative/recommend", json={}).json()["options"]) == 3
    assert c.get(f"/api/jobs/{j['id']}/alignments/foreign").status_code == 404


def test_p5_script_edit_preserves_shots_but_requires_new_choice(tmp_path):
    from test_storyboard import draft

    from ecom_video.storyboard import default_board

    store, j = draft(tmp_path)
    b = default_board(j)
    rec = recommend(j, Brief())
    b["creative"] = {
        "brief": rec["brief"],
        "fingerprint": rec["fingerprint"],
        "style_id": rec["options"][0]["id"],
        "brand": {"name": "已选品牌"},
    }
    for i, s in enumerate(b["shots"]):
        s["shot_id"] = f"keep-{i}"
    b["shots"][0]["motion"] = "pull"
    b["shots"][0]["headline"] = "展示外观"
    store.save_storyboard(j["id"], b, 0)
    revised = store.update_draft(j["id"], j["title"], "换一个开场\n查看细节", 2)
    assert revised["storyboard"]["shots"][0]["motion"] == "pull"
    assert revised["storyboard"]["shots"][0]["shot_id"] == "keep-0"
    assert revised["storyboard"]["shots"][0]["headline"] == ""
    assert revised["storyboard"]["previous_creative"]["brand"]["name"] == "已选品牌"
    with pytest.raises(ValueError, match="重新推荐"):
        store.submit(j["id"])


def test_subtitles_preserve_decimal_percent_and_brand_spacing():
    from ecom_video.captions import phrases
    from ecom_video.local_asr import align

    text = "容量1.5升，浓度0.9%，Air Pro。"
    result = align(text, [{"text": "容量15升浓度09AirPro", "start": 0.1, "end": 5}], 6)
    captions = phrases(text, result["sentences"][0]["words"])
    visible = "".join(c["text"] for c in captions)
    assert "1.5升" in visible and "0.9%" in visible and "Air Pro" in visible


def test_numeric_token_is_not_split_between_subtitle_cards():
    from ecom_video.captions import phrases

    cards = phrases("一二三四五六七八九十一二三1.5升", [], 0, 5)
    assert any("1.5" in c["text"] for c in cards)


def test_bad_timestamp_request_returns_422(tmp_path):
    from fastapi.testclient import TestClient

    from ecom_video.api import create_app

    c = TestClient(create_app(tmp_path), base_url="http://localhost")
    c.headers["x-workflow-token"] = c.get("/api/session").json()["token"]
    r = c.post(
        "/api/jobs/no/alignments/no/confirm",
        json={
            "confirmed": True,
            "reviewer": "fixture",
            "result": {"sentences": [{"words": [{"start": "not a time", "end": 1}]}]},
        },
    )
    assert r.status_code == 422


@pytest.mark.parametrize("action", ["cancel", "script_change", "timeout"])
def test_alignment_child_is_bounded_and_releases_lock(tmp_path, monkeypatch, action):
    import sys
    import threading
    import time

    from test_storyboard import draft

    from ecom_video import alignment as mod
    from ecom_video.media import digest, run_checked

    store, j = draft(tmp_path)
    path = tmp_path / "voice.wav"
    path.write_bytes(b"fixture source")
    store.add_asset(
        j["id"],
        {
            "id": "voice",
            "name": "voice.wav",
            "kind": "audio",
            "path": "voice.wav",
            "sha256": digest(path),
            "size": path.stat().st_size,
            "metadata": {"duration": 4},
        },
    )
    (tmp_path / "model.int8.onnx").touch()
    (tmp_path / "tokens.txt").touch()
    monkeypatch.setattr(mod, "MODEL", tmp_path)
    started = threading.Event()

    def child(cmd, check, timeout=300):
        if cmd[0] == "ffmpeg":
            return ""
        assert timeout == 180
        started.set()
        return run_checked(
            [sys.executable, "-c", "import time; time.sleep(20)"],
            check,
            timeout=0.3 if action == "timeout" else 10,
        )

    monkeypatch.setattr(mod, "run_checked", child)
    service = mod.AlignmentService(tmp_path, store)
    row = service.start(j["id"], "voice")
    assert started.wait(3)
    if action == "cancel":
        service.cancel(j["id"], row["id"])
    elif action == "script_change":
        store.update_draft(j["id"], j["title"], "改稿后重新听核\n查看细节", 2)
    deadline = time.monotonic() + 4
    while mod.LOCK.locked() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not mod.LOCK.locked()
    assert service.get(j["id"], row["id"])["status"] == "failed"
