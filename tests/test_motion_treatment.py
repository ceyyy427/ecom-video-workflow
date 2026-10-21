import copy

from ecom_video.production_direction import choreography_for, direction_for


def test_product_motion_language_is_explicit_and_does_not_claim_evidence():
    kinetic = direction_for("kinetic")["treatment"]
    calm = direction_for("editorial")["treatment"]
    assert kinetic["language"] != calm["language"]
    assert kinetic["route"] == "hybrid" and calm["route"] == "continuous"
    assert kinetic["version"] == calm["version"] == "huashu-method-v1"
    assert kinetic["source"]["commit"] == "3e927801e78b587878fb7dbb65d616326df00c21"
    assert "实拍" in kinetic["summary"] and "人工" in calm["summary"]


def test_new_planning_has_contrast_and_protects_actions_and_resolve():
    lines = ["先看耳机。", "再看耳罩细节。", "双手向内折叠耳罩。", "再看头梁。", "看清再选择。"]
    before = copy.deepcopy(lines)
    rows = choreography_for(lines, "kinetic", [3] * 5)
    assert [r["motion_plan"]["strength"] for r in rows] == [
        "bold",
        "balanced",
        "subtle",
        "bold",
        "subtle",
    ]
    assert rows[2]["shot_recipe"] == "none" and rows[2]["transition"] == "cut"
    assert rows[-1]["shot_recipe"] == "none"
    assert all(r["motion_plan"]["visual_finish"] == "polished-v1" for r in rows)
    assert lines == before
    assert rows == choreography_for(lines, "kinetic", [3] * 5)
    assert choreography_for(lines, "editorial", [3] * 5)[0]["motion_plan"]["strength"] == "subtle"


def test_treatment_receipt_is_based_on_actual_cues_and_does_not_retime():
    from ecom_video.motion_treatment import review_sheet

    scenes = [
        {
            "shot_id": "s1",
            "headline": "看耳罩",
            "start": 0,
            "end": 3,
            "frames": 90,
            "motion_plan": {"visual_finish": "polished-v1"},
            "motion_decision": {
                "cue_frame": 24,
                "recipe": "crash-zoom-punch",
                "strength": "bold",
                "guard_outcome": "unchanged",
            },
            "caption_layout": [
                {
                    "start": 0.3,
                    "end": 2,
                    "emphasis": {"text": "耳罩", "start": 1, "end": 1.5, "basis": "anchored_words"},
                }
            ],
        }
    ]
    before = copy.deepcopy(scenes)
    receipt = review_sheet(scenes, "kinetic")
    shot = receipt["shots"][0]
    assert shot["title_settled_at"] == 1.2
    assert shot["title_hold_seconds"] == 1.8
    assert shot["emphasis"][0]["start"] == 1
    assert receipt["human_review"] == "pending"
    assert receipt["energy_basis"] == "editorial_intent_not_measured_motion_or_effectiveness"
    assert scenes == before
    scenes[0]["motion_decision"]["cue_frame"] = 85
    assert "short_title_hold" in review_sheet(scenes, "kinetic")["shots"][0]["warnings"]


def test_old_saved_motion_is_not_rewritten_by_receipt():
    from ecom_video.motion_treatment import review_sheet
    from ecom_video.shotcraft import MotionPlan

    old = [{"shot_id": "old", "headline": "原版", "start": 0, "end": 2, "frames": 60}]
    before = copy.deepcopy(old)
    assert review_sheet(old, "quiet")["shots"][0]["motion"] == "legacy"
    assert old == before
    assert MotionPlan().visual_finish == "legacy"


def test_read_window_stops_before_the_next_scene_push_stack_exit():
    from ecom_video.motion_treatment import review_sheet

    scenes = [
        {
            "shot_id": "s1",
            "headline": "标题",
            "start": 0,
            "end": 3,
            "frames": 90,
            "motion_plan": {"visual_finish": "polished-v1"},
            "motion_decision": {
                "cue_frame": 24,
                "recipe": "crash-zoom-punch",
                "strength": "bold",
                "guard_outcome": "unchanged",
            },
        },
        {
            "shot_id": "s2",
            "headline": "收尾",
            "start": 3,
            "end": 6,
            "frames": 90,
            "effective_transition": "push-stack",
        },
    ]
    row = review_sheet(scenes, "kinetic")["shots"][0]
    assert abs(row["title_hold_seconds"] - 1.333333) < 1e-6


def test_legacy_title_animation_does_not_receive_a_false_common_reveal_estimate():
    from ecom_video.motion_treatment import review_sheet

    scene = {
        "shot_id": "legacy-v2",
        "headline": "旧标题",
        "start": 0,
        "end": 3,
        "frames": 90,
        "motion_decision": {
            "cue_frame": 0,
            "recipe": "blur-slide",
            "strength": "bold",
            "guard_outcome": "unchanged",
        },
    }
    assert review_sheet([scene], "quiet")["shots"][0]["motion"] == "legacy"


def test_refinement_gallery_is_read_only_and_keeps_both_categories_unapproved(
    tmp_path, monkeypatch
):
    import json

    from fastapi.testclient import TestClient

    from ecom_video import sample_library
    from ecom_video.api import create_app

    folder = tmp_path / "examples"
    for case in ["headphones", "serum"]:
        (folder / case).mkdir(parents=True)
        for name in [
            "output.mp4",
            "parent.mp4",
            "retake.mp4",
            "poster.jpg",
            "narration.wav",
            "subtitles.srt",
            "shotbook.json",
            "recommendations.json",
            "treatment.json",
            "manual-selection.json",
        ]:
            (folder / case / name).write_bytes(b"fixture")
    (folder / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": c, "title": c, "description": "fixture", "duration": 15}
                    for c in ["headphones", "serum"]
                ]
            }
        )
    )
    monkeypatch.setattr(sample_library, "REFINEMENT_LIBRARY", folder, raising=False)
    with TestClient(create_app(tmp_path / "data"), base_url="http://localhost") as c:
        response = c.get("/api/samples/refinement")
        assert response.status_code == 200
        assert len(response.json()) == 2 and all(
            r["status"] == "needs_review" for r in response.json()
        )
        assert c.get("/api/samples/refinement/headphones/treatment").status_code == 200
        assert c.get("/api/samples/refinement/headphones/source").status_code == 404
        assert c.post("/api/samples/refinement/headphones/video").status_code in [403, 405]
        assert c.get("/api/jobs").json() == []
        (folder / "serum/retake.mp4").unlink()
        assert c.get("/api/samples/refinement").json() == []


def test_entry_transition_is_counted_before_title_reading_window_and_clock_is_explicit():
    from ecom_video.motion_treatment import review_sheet

    scene = {
        "shot_id": "s2",
        "headline": "收尾",
        "start": 3,
        "end": 4,
        "frames": 30,
        "motion_plan": {"visual_finish": "polished-v1"},
        "effective_transition": "push-stack",
        "motion_decision": {
            "cue_frame": 0,
            "recipe": "none",
            "strength": "subtle",
            "guard_outcome": "unchanged",
        },
        "caption_layout": [
            {"emphasis": {"text": "收尾", "start": 0.1, "end": 0.7, "basis": "anchored_words"}}
        ],
    }
    receipt = review_sheet([scene], "quiet")
    row = receipt["shots"][0]
    assert abs(row["title_hold_seconds"] - 0.566667) < 1e-6
    assert "short_title_hold" in row["warnings"]
    assert abs(row["title_settled_at_global"] - 3.433333) < 1e-6
    assert row["emphasis"][0]["global_start"] == 3.1
    assert receipt["cue_and_emphasis_time_basis"] == "shot_local_seconds"
    assert receipt["scene_bounds_time_basis"] == "film_seconds"
