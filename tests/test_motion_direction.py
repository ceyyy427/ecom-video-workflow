import copy

import pytest
from pydantic import ValidationError


def test_motion_controls_are_bounded_and_old_shots_stay_opted_out():
    from ecom_video.customer_api import ShotChanges
    from ecom_video.storyboard import Shot

    assert Shot().model_dump().get("motion_plan") is None
    controls = {
        "version": 2,
        "strength": "subtle",
        "cue_offset": 0.25,
        "protect_action": True,
        "windows": [{"start": 0.5, "end": 1.8, "basis": "manual"}],
        "repeat_limit": 2,
        "intent": "action",
    }
    assert (
        Shot(shot_recipe="marker-underline-title", motion_plan=controls).motion_plan.strength
        == "subtle"
    )
    assert ShotChanges(motion_plan=controls).model_dump()["motion_plan"]["cue_offset"] == 0.25
    for changes in [
        {"cue_offset": 10},
        {"strength": "arbitrary-code"},
        {"repeat_limit": 0},
        {"windows": [{"start": 1.5, "end": 0.5}]},
        {"windows": [{"start": 0, "end": 30}]},
    ]:
        with pytest.raises(ValidationError):
            Shot(motion_plan={**controls, **changes})


def test_guard_defers_an_effect_or_falls_back_without_changing_words_or_source():
    from ecom_video.shotcraft import resolve_motion

    scene = {
        "frames": 120,
        "headline": "倒入咖啡",
        "text": "倒入咖啡，看清杯壁。",
        "shot_recipe": "crash-zoom-punch",
        "motion_plan": {
            "version": 2,
            "strength": "bold",
            "cue_offset": 0,
            "protect_action": True,
            "windows": [{"start": 0, "end": 1.5, "basis": "manual"}],
            "repeat_limit": 2,
            "intent": "action",
        },
    }
    words = [{"text": "倒", "start": 0.2, "end": 0.4}]
    before = copy.deepcopy((scene, words))
    result = resolve_motion(scene, words)
    assert result["recipe"] == "crash-zoom-punch"
    assert result["cue_frame"] >= 49  # 45-frame action + 4-frame separation
    assert result["guard_outcome"] == "deferred"
    assert (scene, words) == before
    scene["motion_plan"]["windows"][0]["end"] = 3.8
    result = resolve_motion(scene, words)
    assert result["recipe"] == "none" and result["guard_outcome"] == "static_during_action"
    scene["motion_plan"]["protect_action"] = False
    assert resolve_motion(scene, words)["cue_frame"] == 6


def test_protected_boundary_disables_both_halves_and_does_not_rewrite_old_boards():
    from ecom_video.shotcraft import effective_transitions

    scenes = [
        {
            "frames": 90,
            "transition": "cut",
            "motion_plan": {
                "version": 2,
                "protect_action": True,
                "windows": [{"start": 2.6, "end": 3, "basis": "manual"}],
            },
        },
        {"frames": 90, "transition": "push-stack"},
        {"frames": 90, "transition": "line-carry"},
    ]
    before = copy.deepcopy(scenes)
    assert effective_transitions(scenes) == ["cut", "cut", "line-carry"]
    assert scenes == before
    del scenes[0]["motion_plan"]
    assert effective_transitions(scenes) == ["cut", "push-stack", "line-carry"]


def test_new_planning_caps_repetition_preserves_action_media_and_records_intent(tmp_path):
    from ecom_video.customer_api import Settings
    from ecom_video.shotcraft import choreography

    assert Settings(motion_repeat_limit=1).motion_repeat_limit == 1
    lines = ["先看这个杯子。", "查看杯口细节。", "查看杯壁细节。", "查看杯底细节。", "最后看整体。"]
    planned = choreography(lines, "lab", [3] * 5, repeat_limit=1)
    effects = [s["shot_recipe"] for s in planned if s["shot_recipe"] != "none"]
    assert len(effects) == len(set(effects))
    assert planned[-1]["motion_plan"]["intent"] == "outro"
    assert all(s["motion_plan"]["repeat_limit"] == 1 for s in planned)


def test_phase_labels_are_only_approved_excerpts_with_local_word_times():
    from ecom_video.shotcraft import resolve_motion

    scene = {
        "frames": 120,
        "text": "拿起杯子，再放回桌边。",
        "headline": "拿起杯子",
        "shot_recipe": "product-card-progressive-assemble",
        "motion_plan": {"version": 2, "protect_action": False},
    }
    words = [
        {"text": c, "start": i * 0.2, "end": i * 0.2 + 0.1}
        for i, c in enumerate("拿起杯子再放回桌边")
    ]
    d = resolve_motion(scene, words)
    assert d["beats"] == [{"text": "拿起杯子", "frame": 0}, {"text": "再放回桌边", "frame": 24}]


def test_unobserved_action_has_explicit_voice_hint_provenance():
    from ecom_video.shotcraft import voice_guard

    words = [{"text": c, "start": i * 0.2, "end": i * 0.2 + 0.1} for i, c in enumerate("拿起杯子")]
    ranges = voice_guard("拿起杯子。", words, 2)
    assert ranges and all(r["basis"] == "voice_hint" for r in ranges)
    assert ranges[0]["start"] == 0 and 0.3 <= ranges[0]["end"] <= 2
    assert voice_guard("透明杯子。", words, 2) == []


@pytest.mark.parametrize(
    "style,want",
    [
        ("cinema", (255, 255, 255)),
        ("social", (255, 255, 255)),
        ("lab", (238, 233, 222)),
        ("editorial", (18, 52, 86)),
    ],
)
def test_narrative_subtitles_match_actual_film_social_and_study_plates(style, want):
    import base64
    import io

    from PIL import Image

    from ecom_video.subtitle_layout import prepare_captions

    props = {
        "motionPlan": {"version": 2},
        "shotRecipe": "none",
        "style": style,
        "treatment": "footage",
        "text": "杯口清楚可见",
        "words": [],
        "voiceStart": 0,
        "voiceEnd": 2,
        "brand": {"ink": "#123456", "paper": "#eee9de", "subtitle_size": 60},
    }
    im = Image.open(
        io.BytesIO(base64.b64decode(prepare_captions(props)[0]["image"].split(",", 1)[1]))
    ).convert("RGBA")
    assert {(r, g, b) for r, g, b, a in im.get_flattened_data() if a == 255} == {want}


def test_single_shot_guard_edit_cannot_silently_change_neighboring_transition(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    # Explicitly author a boundary; new narrative plans no longer force shot two's transition.
    board = p["job"]["storyboard"]
    board["shots"][1]["transition"] = "iris"
    saved = c.put(
        f"/api/jobs/{p['job']['id']}/storyboard",
        json={"revision": p["job"]["storyboard_revision"], "board": board},
    )
    assert saved.status_code == 200
    p = c.get(f"/api/customer-projects/{p['id']}").json()
    request = lock_and_revision(c, p)
    request["changes"] = {
        "motion_plan": {"version": 2, "windows": [{"start": 0, "end": 1, "basis": "manual"}]}
    }
    before = c.get("/api/jobs").json()
    r = c.post(f"/api/customer-projects/{p['id']}/revise-shot", json=request)
    assert r.status_code == 422, r.text
    assert "相邻转场" in r.json()["detail"]
    assert c.get("/api/jobs").json() == before


def test_single_motion_parameter_revision_keeps_other_shots_and_review_gate(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    request = lock_and_revision(c, p)
    request["changes"] = {
        "motion_plan": {
            **p["job"]["storyboard"]["shots"][1]["motion_plan"],
            "strength": "bold",
            "cue_offset": 0.3,
        }
    }
    r = c.post(f"/api/customer-projects/{p['id']}/revise-shot", json=request)
    assert r.status_code == 201, r.text
    child = r.json()["job"]
    assert (
        child["parent_id"] == p["job"]["id"] and child["status"] == "draft" and not child["reviews"]
    )
    for i, (old, new) in enumerate(
        zip(p["job"]["storyboard"]["shots"], child["storyboard"]["shots"], strict=True)
    ):
        if i != 1:
            assert {k: v for k, v in old.items() if k != "asset_id"} == {
                k: v for k, v in new.items() if k != "asset_id"
            }


def test_late_semantic_beat_cannot_animate_inside_a_protected_action():
    from ecom_video.shotcraft import resolve_motion

    line = "拿起杯子，再放回桌边。"
    words = [
        {
            "text": c,
            "start": i * 0.2 if i < 4 else 3 + (i - 4) * 0.2,
            "end": i * 0.2 + 0.1 if i < 4 else 3 + (i - 4) * 0.2 + 0.1,
        }
        for i, c in enumerate("拿起杯子再放回桌边")
    ]
    d = resolve_motion(
        {
            "frames": 150,
            "text": line,
            "headline": "拿起杯子",
            "shot_recipe": "product-card-progressive-assemble",
            "motion_plan": {"version": 2, "windows": [{"start": 3, "end": 3.6, "basis": "manual"}]},
        },
        words,
    )
    if d["recipe"] != "none":
        for i, b in enumerate(d["beats"]):
            start = max(d["cue_frame"] + i * 8, b["frame"])
            assert start >= 108 or start + 12 <= 90
    assert d["guard_outcome"] != "unchanged"


def test_iris_guard_covers_full_entrance_and_the_first_scene():
    from ecom_video.shotcraft import effective_transitions

    scene = {
        "frames": 90,
        "transition": "iris",
        "motion_plan": {
            "version": 2,
            "protect_action": True,
            "windows": [{"start": 0.6, "end": 0.75, "basis": "manual"}],
        },
    }
    assert effective_transitions([scene]) == ["cut"]
    assert effective_transitions([{"frames": 90, "transition": "cut"}, scene]) == ["cut", "cut"]


def test_replacement_visual_drops_old_observed_action_windows(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, picture(c, project(c))))))
    board = copy.deepcopy(p["job"]["storyboard"])
    board["shots"][1]["motion_plan"]["windows"] = [{"start": 0.7, "end": 1.3, "basis": "analysis"}]
    r = c.put(
        "/api/jobs/" + p["job"]["id"] + "/storyboard",
        json={"revision": p["job"]["storyboard_revision"], "board": board},
    )
    assert r.status_code == 200, r.text
    p = c.get("/api/customer-projects/" + p["id"]).json()
    req = lock_and_revision(c, p)
    req["changes"] = {"media_id": p["media"][0]["id"]}
    r = c.post("/api/customer-projects/" + p["id"] + "/revise-shot", json=req)
    assert r.status_code == 201, r.text
    assert not r.json()["job"]["storyboard"]["shots"][1]["motion_plan"]["windows"]


@pytest.mark.parametrize(
    "controls",
    [{"version": 2, "strength": "bold"}, {"version": 2, "windows": [{"start": 0.7, "end": 1.3}]}],
)
def test_partial_motion_plan_can_change_source_without_500_or_losing_new_manual_window(
    tmp_path, controls
):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    req = lock_and_revision(c, p)
    req["changes"] = {"source_in": 0, "motion_plan": controls}
    r = c.post(f"/api/customer-projects/{p['id']}/revise-shot", json=req)
    assert r.status_code == 201, r.text
    expected = controls.get("windows", [])
    assert len(r.json()["job"]["storyboard"]["shots"][1]["motion_plan"]["windows"]) == len(expected)


def test_draft_advanced_source_change_cannot_keep_stale_analysis_window(tmp_path):
    from test_customer import approve, client, picture, plan, prepare, project

    c = client(tmp_path)
    p = plan(c, prepare(c, approve(c, picture(c, picture(c, project(c))))))
    board = copy.deepcopy(p["job"]["storyboard"])
    board["shots"][1]["motion_plan"]["windows"] = [{"start": 0.7, "end": 1.3, "basis": "analysis"}]
    jid = p["job"]["id"]
    rev = p["job"]["storyboard_revision"]
    saved = c.put(f"/api/jobs/{jid}/storyboard", json={"revision": rev, "board": board})
    assert saved.status_code == 200, saved.text
    current = c.get("/api/jobs/" + jid).json()
    board = copy.deepcopy(current["storyboard"])
    other = next(
        a["id"]
        for a in current["assets"]
        if a["kind"] == "image" and a["id"] != board["shots"][1]["asset_id"]
    )
    board["shots"][1]["asset_id"] = other
    saved = c.put(
        f"/api/jobs/{jid}/storyboard",
        json={"revision": current["storyboard_revision"], "board": board},
    )
    assert saved.status_code == 200, saved.text
    assert not c.get("/api/jobs/" + jid).json()["storyboard"]["shots"][1]["motion_plan"]["windows"]


def test_sequence_words_alone_do_not_turn_detail_explanation_into_physical_action():
    from ecom_video.shotcraft import choreography

    shots = choreography(
        ["先看整体。", "再看杯壁，透明轮廓可见。", "然后看接口细节。", "看清后再选。"],
        "lab",
        [3] * 4,
    )
    assert [s["motion_plan"]["intent"] for s in shots[1:3]] == ["detail", "detail"]
