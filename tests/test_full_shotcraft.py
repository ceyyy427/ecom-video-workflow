import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ecom_video.api import create_app
from ecom_video.creative import recommend


def test_library_has_full_bodies_code_and_all_style_sample_links():
    from ecom_video.shot_library import detail, inventory

    info = inventory()
    assert info["stats"] == {"cards": 124, "styles": 150, "samples": 150}
    cards = info["items"]
    assert len({c["id"] for c in cards}) == 124
    for c in cards:
        full = detail(c["id"])
        assert hashlib.sha256(full["body"].encode()).hexdigest() == full["body_sha256"]
        assert full["implementation_sources"] and full["styles"]
        assert all(
            s["sample_url"].startswith("https://vincentwei1021.github.io/video-shotcraft/media/")
            for s in full["styles"]
        )
    assert detail("before-after-slider-scrub")["status"] == "reference_only"
    assert detail("crash-zoom-punch")["status"] == "adapted"


def test_local_library_search_filters_actual_content_and_does_not_expose_paths(tmp_path):
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/prompt-library", params={"q": "瓶口", "limit": 20})
        assert r.status_code == 200
        result = c.get(
            "/api/prompt-library", params={"q": "文字遮罩", "category": "opening"}
        ).json()
        assert any(x["id"] == "text-as-mask" for x in result["items"])
        adapted = c.get("/api/prompt-library", params={"status": "adapted", "limit": 124}).json()
        assert adapted["items"] and all(x["status"] == "adapted" for x in adapted["items"])
        full = c.get("/api/prompt-library/text-as-mask").json()
        assert full["body"] and full["source_url"].startswith("https://raw.githubusercontent.com/")
        assert c.get("/api/prompt-library/not-a-card").status_code == 404
        assert c.get("/api/prompt-library", params={"category": "../../var"}).status_code == 422
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        assert c.post("/api/prompt-library/text-as-mask").status_code == 405
        assert c.get("/prompts").status_code == 200


def test_recommendations_include_traceable_reference_matches_without_changing_frozen_cards():
    s = {
        "title": "棕色滴管瓶",
        "script": "看清瓶身和瓶口。",
        "assets": [
            {"sha256": "a" * 64, "kind": "video", "metadata": {"width": 1440, "height": 1440}}
        ],
    }
    brief = {"format": "narrated", "category": "美妆包装", "audience": "新手", "tone": "温柔克制"}
    rec = recommend(s, brief)
    assert rec["reference_library"]["stats"] == {"cards": 124, "styles": 150, "samples": 150}
    for option in rec["options"]:
        assert len(option["reference_matches"]) == 3
        for ref in option["reference_matches"]:
            assert (
                ref["body_sha256"]
                and ref["license"] == "Apache-2.0"
                and ref["matched_terms"] is not None
            )
            assert ref["status"] in ("adapted", "reference_only")
    from ecom_video.prompt_catalog import card_record

    for key, old in json.loads(
        Path("tests/fixtures/compatibility/full-shotcraft-original-cards.json").read_text()
    ).items():
        assert card_record(key) == old


def test_explicit_impact_brief_uses_new_media_languages_but_old_tone_stays_classic():
    s = {
        "title": "棕色滴管瓶",
        "script": "看清瓶身和瓶口。",
        "assets": [
            {"sha256": "a" * 64, "kind": "video", "metadata": {"width": 1440, "height": 1440}}
        ],
    }
    brief = {
        "format": "narrated",
        "category": "美妆包装",
        "audience": "包装消费者",
        "tone": "精致克制，视觉冲击，字形与分屏",
    }
    rec = recommend(s, brief)
    assert {o["prompt_direction"]["cards"][0]["recipe"] for o in rec["options"]} == {
        "product-type-mask",
        "same-frame-panels",
        "detail-dual-window",
    }
    from ecom_video.shotcraft import MotionPlan, resolve_motion

    for option in rec["options"]:
        card = option["prompt_direction"]["cards"][0]
        raw = MotionPlan(prompt_card=card["id"], windows=[{"start": 0, "end": 4}]).model_dump()
        assert (
            resolve_motion(
                {
                    "text": "外观",
                    "headline": "外观",
                    "frames": 120,
                    "start": 0,
                    "shot_recipe": card["recipe"],
                    "motion_plan": raw,
                },
                [],
            )["recipe"]
            == "none"
        )
    brief["tone"] = "温柔克制"
    assert {
        o["prompt_direction"]["cards"][0]["recipe"] for o in recommend(s, brief)["options"]
    } == {"media-punch-in", "product-shape-reveal", "detail-dual-window"}


@pytest.mark.parametrize(
    "recipe,layer,count",
    [("product-type-mask", "product-type-mask", 2), ("same-frame-panels", "same-frame-panels", 3)],
)
def test_new_picture_methods_use_real_shared_clock_media_and_return_to_full_frame(
    recipe, layer, count
):
    import subprocess

    from bs4 import BeautifulSoup
    from test_live_action_render import NODE

    code = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('MediaMotion').MediaMotion;
const p={src:'same.mp4',kind:'video',frames:150,headline:'滴管瓶',index:1,focus_x:.5,focus_y:.4,brand:{paper:'#fff',ink:'#111',accent:'#ccc'},shotRecipe:RECIPE,motionPlan:{cue_frame:0,presentation:{zoom:1.18,travel_frames:30,shape:'rounded'}}};
const draw=at=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{p,mediaStyle:{width:'100%',height:'100%'}}));};
process.stdout.write(JSON.stringify([draw(15),draw(15),draw(149)]));
""".replace("RECIPE", json.dumps(recipe))
    )
    r = subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True)
    first, again, end = json.loads(r.stdout)
    assert first == again and first != end
    html = BeautifulSoup(first, "html.parser")
    assert html.select_one('[data-layer="' + layer + '"]')
    assert len(html.find_all("video")) == count and all(
        v["src"] == "same.mp4" for v in html.find_all("video")
    )
    assert len(BeautifulSoup(end, "html.parser").find_all("video")) == 1


def test_integrity_failure_is_closed_without_executing_or_serving_modified_index(
    tmp_path, monkeypatch
):
    from ecom_video import shot_library

    bad = tmp_path / "index.json"
    bad.write_text('{"cards":[],"payload":"untrusted"}')
    shot_library._load.cache_clear()
    monkeypatch.setattr(shot_library, "INDEX", bad)
    try:
        with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
            assert c.get("/api/prompt-library").status_code == 503
    finally:
        shot_library._load.cache_clear()


def test_full_library_gallery_requires_all_three_films_and_review_stays_pending(
    tmp_path, monkeypatch
):
    from ecom_video import sample_library

    library = tmp_path / "gallery"
    rows = []
    for style in ("editorial", "evidence", "collage"):
        folder = library / style
        folder.mkdir(parents=True)
        for name in (
            "output.mp4",
            "parent.mp4",
            "retake.mp4",
            "poster.jpg",
            "shotbook.json",
            "subtitles.srt",
            "narration.wav",
            "recommendations.json",
            "prompts.json",
        ):
            (folder / name).write_bytes(b"fixture")
        rows.append({"style": style, "title": "待审", "duration": 19})
    (library / "library.json").write_text(json.dumps({"samples": rows}))
    monkeypatch.setattr(sample_library, "FULL_LIBRARY_MOTION", library, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/library-motion")
        assert r.status_code == 200 and len(r.json()) == 3
        assert all(x["status"] == "needs_review" for x in r.json())
        assert c.get("/api/samples/library-motion/editorial/source").status_code == 404
        (library / "collage/prompts.json").unlink()
        assert c.get("/api/samples/library-motion").json() == []


def test_strong_new_picture_languages_are_used_once_then_leave_product_visible():
    from ecom_video.prompt_catalog import apply_prompts, card_record

    rows = [
        {
            "shot_recipe": "none",
            "transition": "cut",
            "reason": "",
            "motion_plan": {"repeat_limit": 4},
        }
        for _ in range(3)
    ]
    asset = {"kind": "video", "metadata": {"width": 1440, "height": 1440}}
    for card_id in ("type-mask-clean-v1", "comic-panels-soft-v1"):
        result = apply_prompts(
            rows,
            ["看清外观。", "再看表面。", "最后看整体。"],
            [4, 4, 4],
            [asset] * 3,
            {"cards": [card_record(card_id)]},
        )
        assert result[0]["shot_recipe"] != "none"
        assert result[1]["shot_recipe"] == "none" and result[2]["shot_recipe"] == "none"


def test_search_does_not_turn_unmatched_punctuation_into_all_results():
    from ecom_video.shot_library import inventory

    assert inventory("！！！")["items"] == []
    single = inventory("茶")["items"]
    from ecom_video.shot_library import detail

    assert all(
        "茶" in detail(c["id"])["body"] or "茶" in c["summary"] or "茶" in c["use"] for c in single
    )
