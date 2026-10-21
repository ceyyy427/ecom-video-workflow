import copy
import json
from pathlib import Path

from ecom_video.creative import rebase_fingerprint, recommend, validate_creative
from ecom_video.prompt_catalog import card_record


def product(tone="自然质感，清楚讲解", audience="喜欢厨房日常的年轻人"):
    return {
        "title": "鲜橙外观示例",
        "script": "先看鲜橙的颜色。\n再看果皮和切面。",
        "assets": [
            {"kind": "video", "sha256": "a" * 64, "metadata": {"width": 1080, "height": 1920}}
        ],
    }, {"format": "narrated", "category": "食品水果", "audience": audience, "tone": tone}


def test_new_recommendation_selects_three_executable_cards_and_freezes_reason():
    from ecom_video.shot_library import detail

    job, brief = product()
    result = recommend(job, brief)
    assert result["policy_version"] == 5
    cards = [o["prompt_direction"]["cards"][0] for o in result["options"]]
    assert len({c["recipe"] for c in cards}) == 3
    assert {c["recipe"] for c in cards} == {
        "product-hero-stage",
        "product-explain-relay",
        "product-brand-snap",
    }
    for option, card in zip(result["options"], cards, strict=True):
        assert option["selected_card"]["digest"] == card["digest"]
        assert card["matched_inputs"]["类别"] and card["matched_inputs"]["人群"]
        assert card["score_breakdown"] and card["product_adaptation"]
        assert detail(card["source_card_id"])["status"] == "adapted"
    second = recommend(job, brief)
    assert result == second
    altered = recommend(job, {**brief, "audience": "严谨专业测评人员", "tone": "理性专业"})
    assert result["prompt_fingerprint"] != altered["prompt_fingerprint"]


def test_legacy_direction_and_immutable_cards_survive_new_selector():
    job, brief = product()
    before = recommend(job, brief, policy=3)
    option = before["options"][0]
    creative = {
        "brief": brief,
        "fingerprint": before["fingerprint"],
        "style_id": option["id"],
        "brand": {"paper": "#ffffff", "ink": "#111111", "accent": "#123456"},
    }
    assert validate_creative(job, creative)["fingerprint"] == before["fingerprint"]
    candidate = copy.deepcopy(job)
    candidate["script"] += "看清细节。"
    assert (
        rebase_fingerprint(job, candidate, creative)
        == recommend(candidate, brief, policy=3)["fingerprint"]
    )
    for key, old in json.loads(
        Path("tests/fixtures/compatibility/product-card-original-cards.json").read_text()
    ).items():
        assert card_record(key) == old


def test_new_cards_cannot_hide_unavailable_material_or_action():
    from ecom_video.prompt_catalog import apply_prompts
    from ecom_video.shotcraft import MotionPlan, resolve_motion

    job, brief = product()
    job["assets"] = []
    assert all(o["selected_card"]["status"] == "blocked" for o in recommend(job, brief)["options"])
    job, brief = product()
    for option in recommend(job, brief)["options"]:
        card = option["selected_card"]
        row = {
            "motion_plan": MotionPlan().model_dump(),
            "reason": "",
            "transition": "cut",
            "shot_recipe": "none",
        }
        rows = apply_prompts(
            [row, row, row],
            ["颜色先看清。", "切开鲜橙。", "再看看。"],
            [4, 4, 4],
            job["assets"] * 3,
            option["prompt_direction"],
        )
        assert rows[1]["shot_recipe"] == "none" and rows[2]["shot_recipe"] == "none"
        assert (
            resolve_motion(
                {
                    "text": "颜色",
                    "headline": "颜色",
                    "frames": 120,
                    "start": 0,
                    "shot_recipe": card["recipe"],
                    "motion_plan": MotionPlan(
                        prompt_card=card["id"], windows=[{"start": 0, "end": 4}]
                    ).model_dump(),
                },
                [],
            )["recipe"]
            == "none"
        )


def test_new_real_media_layers_seek_stably_and_do_not_replace_source():
    import subprocess

    from bs4 import BeautifulSoup
    from test_live_action_render import NODE

    for recipe in ("product-hero-stage", "product-explain-relay", "product-brand-snap"):
        code = (
            NODE[: NODE.index("const Component=")]
            + r"""
const Component=load('MediaMotion').MediaMotion;
const p={src:'orange.mp4',kind:'video',frames:180,headline:'鲜橙',index:1,focus_x:.5,focus_y:.6,brand:{paper:'#fff',ink:'#111',accent:'#cc6633'},shotRecipe:RECIPE,motionPlan:{cue_frame:0,beats:[{text:'先看果皮',frame:0},{text:'再看切面',frame:48}],presentation:{zoom:1.14,travel_frames:10,shape:'rounded'}}};
const draw=at=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{p,mediaStyle:{width:'100%',height:'100%'}}));};
process.stdout.write(JSON.stringify([draw(24),draw(24),draw(179),draw(50)]));
""".replace("RECIPE", json.dumps(recipe))
        )
        result = subprocess.run(["node", "-e", code], check=True, text=True, capture_output=True)
        first, again, end, later = json.loads(result.stdout)
        assert first == again and first != end
        html = BeautifulSoup(first, "html.parser")
        assert html.select_one('[data-layer="' + recipe + '"]')
        assert all(v["src"] == "orange.mp4" for v in html.find_all("video"))
        assert len(html.find_all("video")) == 1
        if recipe == "product-explain-relay":
            assert "先看果皮" in first and "再看切面" not in first
            assert "再看切面" in later and "先看果皮" not in later


def test_customer_page_uses_same_selected_card_as_planner(tmp_path):
    from test_customer import approve, client, prepare, project

    c = client(tmp_path)
    from io import BytesIO

    from PIL import Image

    p = project(c)
    buf = BytesIO()
    Image.new("RGB", (1080, 1920), "#df913b").save(buf, format="PNG")
    p = c.post(
        "/api/customer-projects/" + p["id"] + "/assets",
        data={"revision": p["revision"], "role": "product"},
        files={"file": ("商品.png", buf.getvalue(), "image/png")},
    ).json()
    p = approve(c, p)
    base = "/api/customer-projects/" + p["id"]
    settings = {
        **p["settings"],
        "brief": {
            "format": "showcase",
            "category": "食品水果",
            "audience": "喜欢厨房日常的年轻人",
            "tone": "自然质感，清楚讲解",
        },
    }
    p = c.put(base, json={"revision": p["revision"], "settings": settings}).json()
    p = prepare(c, p)
    rec = p["recommendations"]
    assert rec["policy_version"] == 5
    chosen = rec["options"][0]
    saved = c.post(
        base + "/plan",
        json={
            "revision": p["revision"],
            "job_id": p["job"]["id"],
            "board_revision": p["job"]["storyboard_revision"],
            "fingerprint": rec["fingerprint"],
            "style_id": chosen["id"],
        },
    )
    assert saved.status_code == 200, saved.text
    first = saved.json()["job"]["storyboard"]["shots"][0]
    assert first["motion_plan"]["prompt_card"] == chosen["selected_card"]["id"]
    assert first["shot_recipe"] == chosen["selected_card"]["recipe"]
    assert saved.json()["job"]["storyboard"]["creative"]["fingerprint"] == rec["fingerprint"]
    assert (
        saved.json()["recommendations"]["options"][0]["selected_card"]["id"]
        == chosen["selected_card"]["id"]
    )


def test_auto_format_never_exhausts_card_languages_on_explicit_visual_tone():
    job, brief = product("字形")
    job.update(title="高级精致珠宝年轻活动简洁运动", script="高级精致珠宝年轻活动简洁运动")
    for tone in ("字形", "分屏"):
        rec = recommend(job, {**brief, "format": "auto", "tone": tone})
        assert len({o["family"] for o in rec["options"]}) == 3
        assert len({o["selected_card"]["recipe"] for o in rec["options"]}) == 3


def test_relay_never_truncates_away_a_product_claim_qualification():
    from ecom_video.shotcraft import MotionPlan, resolve_motion

    text = "本品具有美白祛斑抗皱功效的说法并未得到证实。"
    result = resolve_motion(
        {
            "text": text,
            "headline": "本品",
            "frames": 180,
            "start": 0,
            "shot_recipe": "product-explain-relay",
            "motion_plan": MotionPlan(prompt_card="relay-soft-v1").model_dump(),
        },
        [],
    )
    assert not any(b["text"] == "本品具有美白祛斑抗皱功效" for b in result["beats"])
    assert result["recipe"] == "none" or all("未得到证实" in b["text"] for b in result["beats"])


def test_relay_keeps_qualification_after_comma_or_skips_entire_sentence():
    from ecom_video.shotcraft import MotionPlan, resolve_motion

    text = "本品有美白祛斑功效，这个说法尚未证实。"
    result = resolve_motion(
        {
            "text": text,
            "headline": "本品",
            "frames": 180,
            "start": 0,
            "shot_recipe": "product-explain-relay",
            "motion_plan": MotionPlan(prompt_card="relay-soft-v1").model_dump(),
        },
        [],
    )
    assert all("尚未证实" in b["text"] for b in result["beats"])


def test_product_card_gallery_is_complete_readonly_and_pending(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from ecom_video import sample_library
    from ecom_video.api import create_app

    library = tmp_path / "gallery"
    for style in ("evidence", "collage", "cinema"):
        folder = library / style
        folder.mkdir(parents=True)
        for name in (
            "output.mp4",
            "retake.mp4",
            "poster.jpg",
            "shotbook.json",
            "subtitles.srt",
            "narration.wav",
            "recommendations.json",
            "prompts.json",
        ):
            (folder / name).write_bytes(b"fixture")
    (library / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": s, "title": "待听审", "duration": 20.2}
                    for s in ("evidence", "collage", "cinema")
                ]
            }
        )
    )
    monkeypatch.setattr(sample_library, "PRODUCT_CARD_LIBRARY", library, raising=False)
    with TestClient(create_app(tmp_path / "runtime"), base_url="http://localhost") as c:
        r = c.get("/api/samples/product-cards")
        assert r.status_code == 200 and len(r.json()) == 3
        assert all(x["status"] == "needs_review" for x in r.json())
        assert c.get("/api/samples/product-cards/cinema/source").status_code == 404
        assert c.get("/api/samples/product-cards/cinema/parent").status_code == 404
        (library / "cinema/output.mp4").unlink()
        assert c.get("/api/samples/product-cards").json() == []
