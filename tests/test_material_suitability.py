import pytest


def sample(t, **changes):
    return {
        "time": t,
        "match": "same",
        "target_count": "one",
        "visibility": "full",
        "bbox": [180, 100, 820, 900],
        "flow": "absent",
        "lid": "unclear",
        "handling_lid": False,
        "appearance_evidence": {
            "match": "same",
            "permanent_features": ["rim_shape", "base_facets"],
            "uncertainty": "none",
        },
        **changes,
    }


def candidate(**changes):
    from ecom_video.material_suitability import VERSION

    return {
        "id": "c",
        "asset_id": "a",
        "asset_sha256": "a" * 64,
        "kind": "video",
        "start": 0,
        "end": 8,
        "analysis_id": "analysis",
        "segment_id": "s",
        "role": "product",
        "note": "",
        "observation": {
            "description": "透明玻璃杯放在桌面上",
            "subjects": ["透明玻璃杯", "桌面"],
            "actions": [],
            "framing": "whole",
            "usable": True,
            "uncertainty": "",
        },
        "motion_check": {
            "material_checks_version": VERSION,
            "reference_sha256": "ref",
            "samples": [sample(t) for t in range(9)],
            "events": [],
        },
        **changes,
    }


def test_small_subject_and_wrong_product_split_usable_ranges_without_extending_endpoints():
    from ecom_video.material_suitability import visible_ranges

    c = candidate()
    c["motion_check"]["samples"][2]["bbox"] = [490, 490, 510, 510]
    c["motion_check"]["samples"][5]["match"] = "different"
    c["motion_check"]["samples"][8]["visibility"] = "absent"
    assert visible_ranges(c, "ref") == [
        {"start": 0, "end": 1},
        {"start": 3, "end": 4},
        {"start": 6, "end": 7},
    ]
    assert visible_ranges(c, "other-reference") == []


def test_missing_or_invalid_visual_evidence_cannot_be_treated_as_clear():
    from ecom_video.material_suitability import visible_ranges

    for bbox in ([0, 0, 0, 0], [0, 0, 1001, 700], [800, 0, 100, 500], [0, 0, float("nan"), 500]):
        c = candidate()
        c["motion_check"]["samples"] = [sample(0, bbox=bbox), sample(1, bbox=bbox)]
        assert visible_ranges(c, "ref") == []
    c = candidate()
    c["motion_check"].pop("material_checks_version")
    assert visible_ranges(c, "ref") == []


def test_action_window_requires_complete_beginning_and_end_even_without_voice_anchor():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    c["motion_check"]["samples"][3]["flow"] = "visible"
    c["motion_check"]["samples"][4]["flow"] = "visible"
    c["motion_check"]["events"] = [{"kind": "pour", "start": 3, "end": 4, "anchor": 3}]
    windows = line_windows(c, "向玻璃杯倒入咖啡。", 4, [], "ref")
    assert windows and all(w["start"] <= 2 and w["start"] + 4 >= 5 for w in windows)
    assert not line_windows(c, "向玻璃杯倒入咖啡。", 2, [], "ref")
    c["motion_check"]["events"] = []
    c["observation"]["actions"] = ["倒入咖啡"]
    assert not line_windows(c, "向玻璃杯倒入咖啡。", 4, [], "ref")


def test_overlap_is_measured_on_same_source_not_filename_and_similarity_is_only_a_hint():
    from ecom_video.material_suitability import repeat_report

    a = candidate(start=1)
    b = candidate(id="b", asset_id="renamed", start=3)
    result = repeat_report(b, 4, [{**a, "duration": 4}])
    assert result["overlap_seconds"] == 2 and result["overlap_ratio"] == 0.5
    b["asset_sha256"] = "b" * 64
    a["motion_check"]["samples"][3]["frame_hash"] = "0123456789abcdef"
    b["motion_check"]["samples"][3]["frame_hash"] = "0123456789abcdef"
    result = repeat_report(b, 4, [{**a, "duration": 4}])
    assert result["overlap_seconds"] == 0 and result["similar_frame_warning"]


def test_allocator_rejects_tiny_subject_even_if_local_model_gives_high_score():
    from ecom_video.clip_matching import allocate
    from ecom_video.product_motion import VERSION as MOTION

    bad = candidate()
    good = candidate(id="good", asset_id="other", asset_sha256="b" * 64)
    for c in (bad, good):
        c["motion_check"]["version"] = MOTION
    for s in bad["motion_check"]["samples"]:
        s["bbox"] = [490, 490, 510, 510]
    rankings = [
        {
            "line": 1,
            "choices": [
                {"clip_id": "c", "score": 3, "reason": "fixture"},
                {"clip_id": "good", "score": 2, "reason": "fixture"},
            ],
        }
    ]
    out = allocate(
        ["透明玻璃杯。"],
        [3],
        [bad, good],
        rankings,
        "narrated",
        {"material_checks": True, "reference_sha256": "ref"},
    )
    assert out[0]["asset_id"] == "other" and out[0]["material_check"]["status"] == "suggestion"


def test_allocator_never_silently_reuses_an_overlapping_range_under_enhanced_checks():
    from ecom_video.clip_matching import allocate

    c = candidate(end=3)
    c["motion_check"]["samples"] = [sample(t) for t in range(4)]
    rankings = [
        {"line": n, "choices": [{"clip_id": "c", "score": 3, "reason": "fixture"}]} for n in (1, 2)
    ]
    with pytest.raises(ValueError, match="重复|不足|素材"):
        allocate(
            ["透明玻璃杯。"] * 2,
            [3, 3],
            [c],
            rankings,
            "narrated",
            {"material_checks": True, "reference_sha256": "ref"},
        )


def test_quality_checks_are_explicit_and_reference_bound_without_rewriting_legacy_settings(
    tmp_path,
):
    from test_customer import client, picture, project

    c = client(tmp_path)
    p = picture(c, project(c))
    base = "/api/customer-projects/" + p["id"]
    r = c.put(
        base,
        json={"revision": p["revision"], "settings": {**p["settings"], "material_checks": True}},
    )
    assert r.status_code == 200
    assert c.post(base + "/assets/" + p["media"][0]["id"] + "/analysis", json={}).status_code == 422


def test_script_candidates_and_three_styles_explain_same_material_gap_without_changing_confirmations(
    tmp_path,
):
    from test_customer import approve, client, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    base = "/api/customer-projects/" + p["id"]
    p = c.put(
        base,
        json={
            "revision": p["revision"],
            "settings": {
                **p["settings"],
                "material_checks": True,
                "product_reference_id": p["media"][0]["id"],
            },
        },
    ).json()
    preflight = c.get(base + "/preflight").json()
    assert preflight["unknown_count"] > 0 and preflight["material_checks"]
    rec = p["recommendations"]
    assert len(rec["options"]) == 3 and all(
        o["material_fit"]["status"] == "unknown" for o in rec["options"]
    )
    product = p["product"]
    before = c.get("/api/products/" + p["id"]).json()
    result = c.post(
        "/api/products/" + p["id"] + "/scripts/alternatives",
        json={"revision": product["revision"], "brief": p["settings"]["brief"]},
    )
    assert result.status_code == 200, result.text
    assert all(x["material_fit"]["unknown_count"] > 0 for x in result.json()["candidates"])
    assert c.get("/api/products/" + p["id"]).json() == before


def test_preflight_uses_new_subject_evidence_and_reports_global_overlap_not_three_fake_candidates():
    from ecom_video.readiness import check_materials

    c = candidate(end=4)
    check = c["motion_check"]
    asset = {
        "id": "a",
        "name": "neutral.mp4",
        "kind": "video",
        "sha256": "a" * 64,
        "metadata": {
            "duration": 4,
            "content_analysis": {
                "source_sha256": "a" * 64,
                "analysis_id": "v",
                "segments": [
                    {
                        "id": "s",
                        "start": 0,
                        "end": 4,
                        "observation": c["observation"],
                        "quality": {"blank": False},
                        "motion_check": check,
                    }
                ],
            },
        },
    }
    result = check_materials(
        ["透明玻璃杯。"] * 2,
        [asset],
        [3, 3],
        constraints={"material_checks": True, "reference_sha256": "ref"},
    )
    assert result["lines"][0]["status"] == "suggestion"
    assert result["lines"][1]["status"] == "gap" and result["lines"][1]["code"] == "repeated_range"
    assert result["duration_basis"] == "measured"
    for s in check["samples"]:
        s["bbox"] = [490, 490, 510, 510]
    result = check_materials(
        ["透明玻璃杯。"],
        [asset],
        [3],
        constraints={"material_checks": True, "reference_sha256": "ref"},
    )
    assert result["lines"][0]["code"] == "subject_not_visible"


def test_synonyms_and_repeated_actions_cannot_bypass_complete_event_checks():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    for line in ("向玻璃杯注水。", "拧开瓶盖。", "向杯中倒出咖啡。", "先旋开再合盖。"):
        assert not line_windows(c, line, 3, [], "ref")
    c["motion_check"]["events"] = [{"kind": "pour", "start": 3, "end": 4, "anchor": 3}]
    c["motion_check"]["samples"][3]["flow"] = "visible"
    c["motion_check"]["samples"][4]["flow"] = "visible"
    assert not line_windows(c, "先倒入咖啡，然后再倒入咖啡。", 7, [], "ref")


def test_style_fit_checks_style_shot_requirements_and_actual_intro_duration():
    from ecom_video.material_suitability import check_materials, fit_summary

    c = candidate(end=4)
    asset = {
        "id": "a",
        "name": "neutral.mp4",
        "kind": "video",
        "sha256": "a" * 64,
        "metadata": {
            "duration": 4,
            "content_analysis": {
                "source_sha256": "a" * 64,
                "analysis_id": "v",
                "segments": [
                    {
                        "id": "s",
                        "start": 0,
                        "end": 4,
                        "observation": c["observation"],
                        "quality": {"blank": False},
                        "motion_check": c["motion_check"],
                    }
                ],
            },
        },
    }
    constraints = {"material_checks": True, "reference_sha256": "ref"}
    r = check_materials(["透明玻璃杯。"], [asset], constraints=constraints)
    detail = fit_summary(r, "evidence", assets=[asset], constraints=constraints)
    whole = fit_summary(r, "cinema", assets=[asset], constraints=constraints, format="showcase")
    scene = fit_summary(r, "quiet", assets=[asset], constraints=constraints)
    assert detail["style_gap"]["code"] == "detail_shot_missing"
    assert (
        whole["status"] == "needs_material" and whole["style_gap"]["code"] == "intro_duration_short"
    )
    assert scene["style_gap"] is None


def test_preflight_reserves_handle_shot_instead_of_falsely_blocking_feasible_assignment():
    from ecom_video.readiness import check_materials

    assets = []
    for name, subjects in [("A", ["玻璃杯", "把手"]), ("B", ["玻璃杯"])]:
        c = candidate(end=3)
        c["observation"]["subjects"] = subjects
        c["observation"]["description"] = "带把手的玻璃杯" if name == "A" else "透明玻璃杯"
        assets.append(
            {
                "id": name,
                "name": name + ".mp4",
                "kind": "video",
                "sha256": name * 64,
                "metadata": {
                    "duration": 3,
                    "content_analysis": {
                        "source_sha256": name * 64,
                        "analysis_id": name,
                        "segments": [
                            {
                                "id": "s",
                                "start": 0,
                                "end": 3,
                                "observation": c["observation"],
                                "quality": {"blank": False},
                                "motion_check": c["motion_check"],
                            }
                        ],
                    },
                },
            }
        )
    r = check_materials(
        ["透明玻璃杯。", "玻璃杯的把手。"],
        assets,
        [3, 3],
        constraints={"material_checks": True, "reference_sha256": "ref"},
    )
    assert r["gap_count"] == 0 and r["unknown_count"] == 0
    assert [x["candidates"][0]["asset_id"] for x in r["lines"]] == ["B", "A"]


def test_derived_pour_event_cannot_replace_missing_raw_flow_observations():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    c["motion_check"]["events"] = [{"kind": "pour", "start": 3, "end": 4, "anchor": 3}]
    assert not line_windows(c, "向杯中倒入咖啡。", 5, [], "ref")


def test_lid_event_requires_the_stated_direction_and_real_adjacent_endpoints():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    proof = {
        "same_single_product": True,
        "hand_manipulates_cap": True,
        "visible_before_and_after": True,
        "uncertainty": "none",
        "cap_moves_away_from_mouth": False,
        "cap_moves_onto_mouth": True,
    }
    c["motion_check"]["events"] = [
        {"kind": "open_lid", "start": 2, "end": 3, "anchor": 2.5, "temporal_observation": proof}
    ]
    assert not line_windows(c, "打开杯盖。", 4, [], "ref")


def test_complete_action_sequence_rejects_reversed_events_but_accepts_correct_order():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    events = []
    for kind, a, b in [("close_lid", 1, 2), ("open_lid", 5, 6)]:
        opening = kind == "open_lid"
        c["motion_check"]["samples"][b]["lid"] = "detached" if opening else "attached"
        proof = {
            "same_single_product": True,
            "hand_manipulates_cap": True,
            "visible_before_and_after": True,
            "uncertainty": "none",
            "cap_moves_away_from_mouth": opening,
            "cap_moves_onto_mouth": not opening,
        }
        events.append(
            {
                "kind": kind,
                "start": a,
                "end": b,
                "anchor": (a + b) / 2,
                "temporal_observation": proof,
            }
        )
    c["motion_check"]["events"] = events
    assert not line_windows(c, "先打开玻璃杯的杯盖，然后合上杯盖。", 8, [], "ref")
    assert line_windows(c, "先合上杯盖，然后打开玻璃杯的杯盖。", 8, [], "ref")


def test_negation_after_positive_action_does_not_erase_required_opening():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    for text in (
        "打开玻璃杯的杯盖但不要倒水。",
        "打开玻璃杯的杯盖并且无需取下杯套。",
        "打开玻璃杯的杯盖看看里面未使用的空间。",
    ):
        assert not line_windows(c, text, 4, [], "ref")
    assert line_windows(c, "不用打开杯盖，看看杯身。", 4, [], "ref")


def test_more_valid_events_do_not_hide_a_later_feasible_sequence():
    from ecom_video.material_suitability import line_windows

    c = candidate(end=15)
    c["motion_check"]["samples"] = [sample(i * 0.75) for i in range(21)]
    events = []
    for a, b, opening in [(0, 0.75, True)] + [
        (i * 0.75, (i + 1) * 0.75, i % 2 == 0) for i in range(5, 19)
    ]:
        c["motion_check"]["samples"][round(b / 0.75)]["lid"] = "detached" if opening else "attached"
        events.append(
            {
                "kind": "open_lid" if opening else "close_lid",
                "start": a,
                "end": b,
                "anchor": (a + b) / 2,
                "temporal_observation": {
                    "same_single_product": True,
                    "hand_manipulates_cap": True,
                    "visible_before_and_after": True,
                    "uncertainty": "none",
                    "cap_moves_away_from_mouth": opening,
                    "cap_moves_onto_mouth": not opening,
                },
            }
        )
    c["motion_check"]["events"] = events
    assert line_windows(c, "打开杯盖，然后合上杯盖，然后打开杯盖。", 4, [], "ref")


def test_style_inventory_never_borrows_full_subject_before_asset_source_in():
    from ecom_video.material_suitability import check_materials, fit_summary

    c = candidate()
    for s in c["motion_check"]["samples"][3:]:
        s["visibility"] = "partial"
    a = {
        "id": "a",
        "name": "neutral.mp4",
        "kind": "video",
        "sha256": "a" * 64,
        "metadata": {
            "duration": 8,
            "source_in": 3,
            "content_analysis": {
                "source_sha256": "a" * 64,
                "analysis_id": "v",
                "segments": [
                    {
                        "id": "s",
                        "start": 0,
                        "end": 8,
                        "observation": c["observation"],
                        "quality": {"blank": False},
                        "motion_check": c["motion_check"],
                    }
                ],
            },
        },
    }
    constraints = {"material_checks": True, "reference_sha256": "ref"}
    r = check_materials(["透明玻璃杯。"], [a], [3], constraints=constraints)
    f = fit_summary(r, "cinema", assets=[a], constraints=constraints, format="narrated")
    assert f["observed_shot_types"]["whole"] == 0 and f["style_gap"]["code"] == "whole_shot_missing"


def test_complete_event_ranges_survive_without_spoken_action_timestamps():
    from ecom_video.material_suitability import line_windows

    c = candidate()
    c["motion_check"]["samples"][3]["flow"] = "visible"
    c["motion_check"]["samples"][4]["flow"] = "visible"
    c["motion_check"]["events"] = [{"kind": "pour", "start": 3, "end": 4, "anchor": 3}]
    windows = line_windows(c, "向杯中倒入咖啡。", 4, [], "ref")
    assert windows and all(
        w["complete_actions"][0]["source_start"] == 2
        and w["complete_actions"][0]["source_end"] == 5
        for w in windows
    )


def test_enhanced_appearance_requires_distinct_permanent_features_not_just_same_label(monkeypatch):
    from ecom_video import product_inspection as inspect

    for evidence, uncertainty, expected in [
        (["rim_shape", "base_facets"], "none", "same"),
        (["rim_shape", "rim_shape"], "none", "uncertain"),
        (["rim_shape", "body_shape"], "occlusion", "uncertain"),
    ]:
        monkeypatch.setattr(
            inspect,
            "generate",
            lambda *a, features=evidence, u=uncertainty, **k: {
                "match": "same",
                "permanent_features": features,
                "uncertainty": u,
            },
        )
        r = inspect.appearance("ref", "frame", {"model": "fixture"}, "cup", enhanced=True)
        assert r["match"] == expected and r["permanent_features"] == evidence


def test_similar_frame_hint_breaks_equal_match_ties_without_rejecting_the_candidate():
    from ecom_video.clip_matching import allocate

    a = candidate()
    b = candidate(id="b", asset_id="b", asset_sha256="b" * 64)
    fresh = candidate(id="fresh", asset_id="fresh", asset_sha256="c" * 64)
    for row in a["motion_check"]["samples"]:
        row["frame_hash"] = "0000000000000000"
    for row in b["motion_check"]["samples"]:
        row["frame_hash"] = "0000000000000000"
    for row in fresh["motion_check"]["samples"]:
        row["frame_hash"] = "ffffffffffffffff"
    ranking = [
        {"line": 1, "choices": [{"clip_id": "c", "score": 3, "reason": "fixture"}]},
        {
            "line": 2,
            "choices": [
                {"clip_id": "b", "score": 3, "reason": "fixture"},
                {"clip_id": "fresh", "score": 3, "reason": "fixture"},
            ],
        },
    ]
    r = allocate(
        ["透明玻璃杯。"] * 2,
        [3, 3],
        [a, b, fresh],
        ranking,
        "narrated",
        {"material_checks": True, "reference_sha256": "ref"},
    )
    assert r[1]["asset_id"] == "fresh"
    r = allocate(
        ["透明玻璃杯。"] * 2,
        [3, 3],
        [a, b],
        ranking[:1] + [{"line": 2, "choices": [{"clip_id": "b", "score": 3, "reason": "fixture"}]}],
        "narrated",
        {"material_checks": True, "reference_sha256": "ref"},
    )
    assert r[1]["material_check"]["similar_frame_warning"]


def test_unreleased_enhanced_cache_without_permanent_evidence_is_stale_and_not_selectable():
    from ecom_video.material_suitability import line_windows
    from ecom_video.product_inspection import current_context

    c = candidate()
    context = {
        "material_checks": c["motion_check"]["material_checks_version"],
        "reference_sha256": "ref",
    }
    result = {
        "context": context,
        "source_sha256": c["asset_sha256"],
        "segments": [{"motion_check": c["motion_check"]}],
    }
    assert current_context({"result": result}, context)
    for row in c["motion_check"]["samples"]:
        row.pop("appearance_evidence", None)
    assert not current_context({"result": result}, context)
    assert not line_windows(c, "透明玻璃杯。", 3, [], "ref")
    # The exact reference file can identify itself by its bound digest, without comparing pictures.
    c["asset_sha256"] = "ref"
    result["source_sha256"] = "ref"
    assert current_context({"result": result}, context)
    assert line_windows(c, "透明玻璃杯。", 3, [], "ref")


def test_material_gallery_is_readonly_and_requires_complete_evidence(tmp_path, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ecom_video import sample_library

    gallery = tmp_path / "gallery"
    monkeypatch.setattr(sample_library, "MATERIAL_LIBRARY", gallery)
    app = FastAPI()
    app.include_router(sample_library.material_router())
    c = TestClient(app)
    assert c.get("/api/samples/material-checks").json() == []
    folder = gallery / "cup"
    folder.mkdir(parents=True)
    for filename in (
        "output.mp4",
        "retake.mp4",
        "poster.jpg",
        "shotbook.json",
        "subtitles.srt",
        "narration.wav",
        "recognition.json",
        "preflight.json",
        "selection.json",
        "recommendations.json",
        "license.json",
        "acceptance.json",
    ):
        (folder / filename).write_bytes(b"fixture")
    (gallery / "library.json").write_text(
        json.dumps({"samples": [{"style": "cup", "duration": 18.1}]})
    )
    rows = c.get("/api/samples/material-checks").json()
    assert len(rows) == 1 and rows[0]["status"] == "needs_review"
    assert len(rows[0]["review_required"]) == 5
    assert (
        c.get("/api/samples/material-checks/cup/retake", headers={"Range": "bytes=0-2"}).status_code
        == 206
    )
    assert c.get("/api/samples/material-checks/cup/source").status_code == 404
    (folder / "recognition.json").unlink()
    assert c.get("/api/samples/material-checks").json() == []


def test_target_crop_recheck_is_bounded_keeps_primary_and_never_rescues_tiny_or_multiple(
    tmp_path, monkeypatch
):
    from PIL import Image

    from ecom_video import product_inspection as inspect

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (100, 100), "gray").save(frame)
    primary = {"match": "different", "permanent_features": [], "uncertainty": "none"}
    clear = {
        "match": "same",
        "permanent_features": ["rim_shape", "base_facets"],
        "uncertainty": "none",
    }
    calls = []

    def compare(ref, image, *args, **kwargs):
        calls.append(image)
        return primary.copy() if image == frame else clear.copy()

    monkeypatch.setattr(inspect, "appearance", compare)
    monkeypatch.setattr(inspect, "motion_state", lambda *a, **k: sample(0))
    budget = [2]
    result = inspect.inspect_material_state("ref", frame, {}, "cup", budget)
    assert result["match"] == "same" and budget == [1]
    assert result["appearance_evidence"]["primary"] == primary
    assert (
        result["comparison_frame"] != "frame.jpg"
        and (tmp_path / result["comparison_frame"]).is_file()
    )
    for state in (sample(0, bbox=[490, 490, 510, 510]), sample(0, target_count="multiple")):
        calls.clear()
        monkeypatch.setattr(inspect, "motion_state", lambda *a, s=state, **k: s)
        assert inspect.inspect_material_state("ref", frame, {}, "cup", [2])["match"] != "same"
        assert calls == [frame]
    calls.clear()
    assert inspect.inspect_material_state("ref", frame, {}, "cup", [0])["match"] == "different"
    assert calls == [frame]


def test_same_file_distinct_times_can_warn_of_static_similarity_without_fake_time_overlap():
    from ecom_video.material_suitability import repeat_report

    c = candidate(start=0)
    for row in c["motion_check"]["samples"]:
        row["frame_hash"] = "0123456789abcdef"
    r = repeat_report(c, 2, [{**c, "start": 4, "duration": 2}])
    assert r["overlap_seconds"] == 0 and r["similar_frame_warning"]
    # A common endpoint isn't part of both rendered frame intervals.
    c["motion_check"]["samples"] = [{**sample(2), "frame_hash": "0123456789abcdef"}]
    r = repeat_report(c, 2, [{**c, "start": 2, "duration": 2}])
    assert r["overlap_seconds"] == 0 and not r["similar_frame_warning"]


def test_later_exclusive_range_survives_a_higher_scoring_earlier_choice():
    from ecom_video.clip_matching import allocate

    a = candidate(end=2)
    a["motion_check"]["samples"] = [sample(t) for t in (0, 1, 2)]
    b = candidate(id="b", asset_id="b", asset_sha256="b" * 64, end=2)
    b["motion_check"]["samples"] = [sample(t) for t in (0, 1, 2)]
    rankings = [
        {
            "line": 1,
            "choices": [
                {"clip_id": "c", "score": 3, "reason": "相关整体"},
                {"clip_id": "b", "score": 2, "reason": "相关外观"},
            ],
        },
        {
            "line": 2,
            "choices": [
                {"clip_id": "c", "score": 3, "reason": "直接展示"},
                {"clip_id": "b", "score": 0, "reason": "不适合本句"},
            ],
        },
    ]
    selected = allocate(
        ["玻璃杯外观。", "再看玻璃杯。"],
        [2, 2],
        [a, b],
        rankings,
        "narrated",
        {"material_checks": True, "reference_sha256": "ref"},
    )
    assert [s["asset_id"] for s in selected] == ["b", "a"]
    assert all(s["material_check"]["overlap_seconds"] == 0 for s in selected)


def test_enhanced_ranking_scores_every_candidate_and_rejects_silent_omission(monkeypatch):
    import json

    from ecom_video import clip_matching

    pool = [candidate(id=f"c{i}", asset_id=f"a{i}") for i in range(5)]
    seen = []

    def generate(prompt, schema, **kwargs):
        payload = json.loads(prompt.split("\n", 1)[1])
        assert "观众观看" in prompt
        assert payload["script"][0]["action_requirement_hints"] == []
        rows = payload["candidates"]
        assert len(rows) <= 4
        choices = schema["$defs"]["LineRanking"]["properties"]["choices"]
        assert choices["minItems"] == choices["maxItems"] == len(rows)
        seen.extend(r["id"] for r in rows)
        return {
            "lines": [
                {
                    "line": 1,
                    "choices": [
                        {
                            "clip_id": r["id"],
                            "score": 0 if r["id"] == "c4" else 2,
                            "reason": "模拟逐个评价",
                        }
                        for r in rows
                    ],
                }
            ]
        }

    monkeypatch.setattr(clip_matching, "generate", generate)
    result = clip_matching.rank(["玻璃杯外观。"], pool, {"model": "fixture"}, complete=True)
    assert seen == [c["id"] for c in pool]
    assert len(result[0]["choices"]) == 5
    monkeypatch.setattr(
        clip_matching,
        "generate",
        lambda *a, **k: {
            "lines": [
                {"line": 1, "choices": [{"clip_id": "c0", "score": 3, "reason": "遗漏其他候选"}]}
            ]
        },
    )
    with pytest.raises(ValueError, match="候选评分不完整"):
        clip_matching.rank(["玻璃杯外观。"], pool, {"model": "fixture"}, complete=True)


def test_observation_rule_keeps_model_score_and_cannot_support_claims_or_uncertainty():
    from ecom_video.clip_matching import allocate
    from ecom_video.material_suitability import observation_match

    c = candidate()
    c["observation"]["description"] = "透明玻璃杯，杯身清晰，有竖条纹。"
    assert observation_match("看杯身。", c, 0, 2)
    assert not observation_match("看杯身保温8小时。", c, 0, 2)
    c["observation"]["uncertainty"] = "杯身细节看不清"
    assert not observation_match("看杯身。", c, 0, 2)
    c["observation"]["uncertainty"] = ""
    c["observation"]["description"] = "看不清杯身，只有背景桌面。"
    assert not observation_match("看杯身。", c, 0, 2)
    for sentence, description in (
        ("看纹理。", "透明玻璃杯在桌面，纹理不可见。"),
        ("看接口。", "接口缺失。"),
        ("看纹理。", "杯身无纹理。"),
        ("看接口。", "接口尚未展示。"),
    ):
        c["observation"]["description"] = description
        assert not observation_match(sentence, c, 0, 2)
    c["observation"]["description"] = "透明玻璃杯，杯身清晰。"
    votes = [{"line": 1, "choices": [{"clip_id": "c", "score": 0, "reason": "错误地要求观看动作"}]}]
    row = allocate(
        ["看杯身。"],
        [2],
        [c],
        votes,
        "narrated",
        {"material_checks": True, "reference_sha256": "ref"},
    )[0]
    assert row["score"] == 2 and row["model_score"] == 0
    assert row["ranking_method"] == "local_material_observation"
    with pytest.raises(ValueError):
        allocate(["看杯身。"], [2], [c], votes, "narrated")
    assert observation_match("看清楚，再选择。", c, 1, 2)
    assert not observation_match("看清楚，再选择。", c, 0, 2)
