"""Category-specific matches must change real bounded presentation, not only names."""

import json
from pathlib import Path

import pytest

from ecom_video.creative import recommend
from ecom_video.prompt_catalog import card_record, match_direction
from ecom_video.shotcraft import MotionPlan, resolve_motion


def sample(title, script):
    return {
        "title": title,
        "script": script,
        "assets": [
            {"kind": "video", "sha256": "a" * 64, "metadata": {"width": 2732, "height": 1440}}
        ],
    }


@pytest.mark.parametrize(
    "title,script,category,audience,tone,wants",
    [
        (
            "棕色滴管瓶",
            "看瓶身、黑色瓶盖与瓶口。",
            "美妆包装",
            "护肤新手",
            "温柔克制",
            {"beauty-punch-v1", "bottle-dual-v1", "beauty-portal-v1"},
        ),
        (
            "曲奇饼干",
            "看饼干的表面纹理。",
            "食品零食",
            "下午茶爱好者",
            "温暖自然",
            {"food-punch-v1", "food-dual-v1", "food-portal-v1"},
        ),
        (
            "衬衫",
            "看衣领与面料、走线。",
            "服装",
            "通勤穿搭",
            "精致清楚",
            {"garment-punch-v1", "garment-dual-v1", "garment-portal-v1"},
        ),
        (
            "收纳盒",
            "看盒体与抽屉的分区。",
            "家居收纳",
            "小户型家庭",
            "安静温暖",
            {"home-punch-v1", "home-dual-v1", "home-portal-v1"},
        ),
        (
            "螺丝刀",
            "看刀头和握柄的接口。",
            "五金工具",
            "维修新手",
            "理性专业",
            {"tool-punch-v1", "tool-dual-v1", "tool-portal-v1"},
        ),
    ],
)
def test_product_specific_prompts_win_over_generic_style(
    title, script, category, audience, tone, wants
):
    source = sample(title, script)
    brief = {"format": "narrated", "category": category, "audience": audience, "tone": tone}
    cards = match_direction(source, brief, "editorial")["cards"]
    assert {c["id"] for c in cards} == wants
    assert len({c["prompt"] for c in cards}) == 3
    for c in cards:
        assert c["matched_inputs"]["商品"]
        assert c["shot_goal"] and c["voice_caption_rule"]
        # The selected card must be accepted all the way through the render contract.
        plan = MotionPlan(prompt_card=c["id"]).model_dump()
        r = resolve_motion(
            {
                "text": "观察外观",
                "headline": "外观",
                "frames": 150,
                "start": 0,
                "shot_recipe": c["recipe"],
                "motion_plan": plan,
            },
            [],
        )
        assert r["recipe"] == c["recipe"] and r["presentation"] == c["presentation"]


def test_existing_frozen_cards_keep_exact_digests_after_expansion():
    original = json.loads(Path("tests/fixtures/compatibility/prompt-direction-sources.json").read_text())
    assert len(original) == 2
    frozen = json.loads(Path("tests/fixtures/compatibility/prompt-expansion-original-cards.json").read_text())
    for key, old in frozen.items():
        assert card_record(key) == old


def test_three_directions_are_recommended_for_actual_bottle_context():
    source = sample("棕色滴管瓶", "先看棕色瓶身，再看黑色瓶盖。")
    brief = {
        "format": "narrated",
        "category": "美妆护肤包装",
        "audience": "重视精致包装的护肤消费者",
        "tone": "轻奢精致，温柔克制，留白",
    }
    rec = recommend(source, brief)
    assert len({o["prompt_direction"]["cards"][0]["recipe"] for o in rec["options"]}) == 3
    assert {o["prompt_direction"]["cards"][0]["id"] for o in rec["options"]} == {
        "beauty-punch-v1",
        "bottle-dual-v1",
        "beauty-portal-v1",
    }


def test_bottle_prompt_gallery_is_complete_unapproved_and_read_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from ecom_video import sample_library
    from ecom_video.api import create_app

    library = tmp_path / "bottle"
    names = [
        "output.mp4",
        "parent.mp4",
        "retake.mp4",
        "poster.jpg",
        "shotbook.json",
        "subtitles.srt",
        "narration.wav",
        "recommendations.json",
        "prompts.json",
    ]
    rows = []
    for style in ("editorial", "quiet", "evidence"):
        folder = library / style
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).write_bytes(b"fixture")
        rows.append(
            {"style": style, "duration": 19, "title": "包装观察", "description": "仍待听审"}
        )
    (library / "library.json").write_text(json.dumps({"samples": rows}))
    monkeypatch.setattr(sample_library, "PROMPT_CATEGORY_LIBRARY", library, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        r = c.get("/api/samples/prompt-categories")
        assert r.status_code == 200
        assert len(r.json()) == 3 and all(x["status"] == "needs_review" for x in r.json())
        assert c.get("/api/samples/prompt-categories/editorial/video").content == b"fixture"
        assert c.get("/api/samples/prompt-categories/editorial/source").status_code == 404
        assert c.post("/api/samples/prompt-categories/editorial/video").status_code == 405
        (library / "quiet/prompts.json").unlink()
        assert c.get("/api/samples/prompt-categories").json() == []


def test_single_shot_demo_changes_executable_presentation_not_only_id():
    from ecom_video.prompt_catalog import CARDS
    from scripts.build_prompt_samples import variant_for

    for card_id, card in CARDS.items():
        variant = CARDS[variant_for(card_id)]
        assert variant["recipe"] == card["recipe"]
        assert variant["presentation"] != card["presentation"]
