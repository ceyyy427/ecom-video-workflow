import copy
import json
from pathlib import Path

from ecom_video.creative import recommend
from ecom_video.generation import validate_scenes


def facts():
    return [
        {"id": "a", "text": "橙色果皮。"},
        {"id": "d", "text": "切面有放射状纹理。"},
        {"id": "n", "text": "素材记录每秒六十帧。"},
        {"id": "u", "text": "刀口切下薄片。"},
    ]


def test_three_script_alternatives_keep_complete_sources_and_distinct_plans():
    from ecom_video.script_alternatives import alternatives

    p = {"title": "鲜橙", "revision": 7, "current_review_id": "r", "facts": facts()}
    out = alternatives(p, facts(), {"format": "narrated", "audience": "年轻人", "tone": "自然"})
    assert len(out["candidates"]) == 3
    assert len({str(c["payload"]) for c in out["candidates"]}) == 3
    for c in out["candidates"]:
        assert validate_scenes(c["payload"], facts()) == c["payload"]
        assert all(s["text"] in [f["text"] for f in facts()] for s in c["payload"] if s["fact_ids"])
        assert c["shot_strategies"] and c["human_confirmation_required"]
    assert p["revision"] == 7


def test_preview_is_readonly_adoption_is_pending_and_stale_basis_rejected(tmp_path):
    from test_customer import approve, client, picture, project

    c = client(tmp_path)
    p = approve(c, picture(c, project(c)))
    prod = p["product"]
    url = "/api/products/" + p["id"]
    body = {"revision": prod["revision"], "brief": {"format": "narrated", "tone": "自然"}}
    r = c.post(url + "/scripts/alternatives", json=body)
    assert r.status_code == 200, r.text
    assert c.get(url).json() == prod
    bundle = r.json()
    chosen = bundle["candidates"][1]
    result = c.post(
        url + "/scripts/alternatives/adopt",
        json={**body, "basis": bundle["basis"], "candidate_id": chosen["id"]},
    )
    assert result.status_code == 201, result.text
    new = result.json()
    assert new["status"] == "script_draft"
    assert len(new["script_approvals"]) == len(prod["script_approvals"])
    assert len(new["script_drafts"]) == len(prod["script_drafts"]) + 1
    assert (
        c.post(
            url + "/scripts/alternatives/adopt",
            json={**body, "basis": bundle["basis"], "candidate_id": chosen["id"]},
        ).status_code
        == 409
    )
    assert (
        c.post(
            url + "/scripts/alternatives/adopt",
            json={
                "revision": new["revision"],
                "brief": body["brief"],
                "basis": bundle["basis"],
                "candidate_id": chosen["id"],
            },
        ).status_code
        == 409
    )


def fixture():
    lines = [
        "先看整体，再看细节。",
        "切面有放射状纹理。",
        "素材记录每秒六十帧。",
        "回到完整画面。",
        "刀口切下薄片。",
        "橙色果皮。",
        "请结合自己的使用需求选择。",
    ]
    asset = {
        "id": "v",
        "kind": "video",
        "sha256": "a" * 64,
        "metadata": {"width": 1080, "height": 1920, "duration": 20},
    }
    job = {
        "title": "鲜橙",
        "script": "\n".join(lines),
        "assets": [asset],
        "provenance": {
            "facts": facts(),
            "scenes": [
                {"text": t, "fact_ids": ["n"] if i == 2 else []} for i, t in enumerate(lines)
            ],
        },
    }
    return job, lines, asset


def test_same_film_mixes_cards_and_verified_data_does_not_become_a_chart():
    from ecom_video.prompt_catalog import apply_prompts
    from ecom_video.shotcraft import MotionPlan

    job, lines, asset = fixture()
    r = recommend(
        job, {"format": "narrated", "category": "食品", "audience": "年轻人", "tone": "自然"}
    )
    assert r["policy_version"] == 5
    rows = [
        {
            "motion_plan": MotionPlan().model_dump(),
            "reason": "",
            "transition": "cut",
            "shot_recipe": "none",
        }
        for _ in lines
    ]
    selected = apply_prompts(
        rows,
        lines,
        [4] * len(lines),
        [asset] * len(lines),
        r["options"][0]["prompt_direction"],
        job=job,
    )
    assert selected[1]["shot_recipe"] == "product-detail-bracket"
    assert selected[2]["shot_recipe"] == "product-fact-row"
    assert selected[4]["shot_recipe"] == "none"
    assert selected[3]["transition"] == "media-pass"
    assert len({x["shot_recipe"] for x in selected}) >= 4
    assert selected[-1]["shot_recipe"] == "none"
    for key, old in json.loads(
        Path("tests/fixtures/compatibility/semantic-original-cards.json").read_text()
    ).items():
        from ecom_video.prompt_catalog import card_record

        assert card_record(key) == old


def test_numbers_and_sales_need_exact_current_source_quotation():
    from ecom_video.semantic_mix import strategy

    job, lines, asset = fixture()
    assert strategy(job, 2, asset)["kind"] == "data"
    assert strategy(job, 2, asset)["quoted_fact_ids"] == ["n"]
    bad = copy.deepcopy(job)
    bad["script"] = bad["script"].replace(lines[2], "销量提升百分之五十。")
    assert strategy(bad, 2, asset)["status"] == "needs_evidence"
    bad["script"] = bad["script"].replace("销量提升百分之五十。", "限时到手价39.9元。")
    assert strategy(bad, 2, asset)["kind"] == "sales"
    assert strategy(bad, 2, asset)["status"] == "needs_evidence"
    job["script"] = job["script"].replace(lines[2], "素材记录每秒六十帧，实际取决于设备。")
    assert strategy(job, 2, asset)["status"] == "needs_evidence"


def test_render_guard_rechecks_quote_and_does_not_truncate_numeric_qualifier():
    from ecom_video.semantic_mix import guard_decision

    job, lines, asset = fixture()
    decision = {"recipe": "product-fact-row", "guard_outcome": "unchanged"}
    valid = guard_decision(job, 2, decision)
    assert valid["quote"]["text"] == lines[2] and valid["quote"]["fact_ids"] == ["n"]
    bad = copy.deepcopy(job)
    bad["provenance"]["scenes"][2]["fact_ids"] = []
    assert guard_decision(bad, 2, decision)["recipe"] == "none"
    assert decision == {"recipe": "product-fact-row", "guard_outcome": "unchanged"}


def test_new_effects_keep_source_and_caption_clock_and_transition_is_media_only():
    import subprocess

    from bs4 import BeautifulSoup
    from test_live_action_render import NODE

    code = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('NarrativeShot').NarrativeShot;
const base={src:'orange.mp4',kind:'video',frames:150,text:'素材每秒六十帧。',headline:'六十帧',index:2,count:7,focus_x:.5,focus_y:.6,brand:{paper:'#fff',ink:'#111',accent:'#cf7711',subtitle_size:56},style:'evidence',motion:'static',fit:'contain',format:'narrated',transition:'media-pass',captions:[{start:0,end:5,text:'完整字幕'}],motionPlan:{version:2,amount:1,cue_frame:0,beats:[],quote:{text:'素材每秒六十帧。',fact_ids:['n']},presentation:{zoom:1,travel_frames:18,shape:'rounded'}}};
const draw=(recipe,at)=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{...base,shotRecipe:recipe}));};
process.stdout.write(JSON.stringify([draw('product-detail-bracket',8),draw('product-fact-row',8),draw('product-fact-row',8)]));
"""
    )
    r = subprocess.run(["node", "-e", code], text=True, capture_output=True, check=True)
    bracket, row, again = json.loads(r.stdout)
    assert row == again
    for markup, recipe in [(bracket, "product-detail-bracket"), (row, "product-fact-row")]:
        html = BeautifulSoup(markup, "html.parser")
        assert html.select_one('[data-layer="' + recipe + '"]')
        assert len(html.find_all("video")) == 1
        assert html.select_one('[data-layer="media-pass"]')
        assert "素材每秒六十帧。" in row


def test_mixed_cards_never_override_legacy_action_intent_or_handling_words():
    from ecom_video.prompt_catalog import apply_prompts
    from ecom_video.shotcraft import MotionPlan

    for text in ("把橙片放入杯中。", "取出橙片。", "把两边靠拢。", "收起商品。", "向杯中滴入。"):
        job, _, asset = fixture()
        lines = ["先看整体。", text, "请结合自己的使用需求选择。"]
        job["script"] = "\n".join(lines)
        r = recommend(job, {"format": "narrated", "tone": "自然"})
        rows = [
            {
                "motion_plan": MotionPlan(intent="action" if i == 1 else "auto").model_dump(),
                "reason": "",
                "transition": "cut",
                "shot_recipe": "none",
            }
            for i in range(3)
        ]
        out = apply_prompts(
            rows, lines, [4] * 3, [asset] * 3, r["options"][0]["prompt_direction"], job=job
        )
        assert out[1]["shot_recipe"] == "none" and out[1]["transition"] == "cut"


def test_manual_card_cannot_bypass_sales_source_or_emphasize_price_without_qualifier():
    from ecom_video.semantic_mix import guard_decision

    job, lines, asset = fixture()
    line = "到手价39元，仅适用于首次购买用户。"
    job["script"] = line
    job["provenance"] = {"facts": [], "scenes": [{"text": line, "fact_ids": []}]}
    for recipe in (
        "product-fact-row",
        "product-explain-relay",
        "product-detail-bracket",
        "media-punch-in",
    ):
        d = guard_decision(job, 0, {"recipe": recipe, "guard_outcome": "unchanged"})
        assert d["recipe"] == "none" and d["suppress_headline"]
    job["provenance"] = {
        "facts": [{"id": "price", "text": line}],
        "scenes": [{"text": line, "fact_ids": ["price"]}],
    }
    d = guard_decision(job, 0, {"recipe": "product-fact-row", "guard_outcome": "unchanged"})
    assert d["quote"]["text"] == line and d["suppress_headline"]


def test_scene_handoff_never_covers_previous_legacy_action():
    from ecom_video.production_direction import choreography_for
    from ecom_video.prompt_catalog import apply_prompts
    from ecom_video.shotcraft import effective_transitions

    job, _, asset = fixture()
    for text in ("把杯子放回原处。", "倒一杯。"):
        lines = ["先看整体，再看细节。", text, "回到完整画面。", "请结合自己的使用需求选择。"]
        job["script"] = "\n".join(lines)
        d = recommend(job, {"format": "narrated", "tone": "自然"})["options"][0]
        rows = choreography_for(lines, d["id"], [4] * 4)
        out = apply_prompts(rows, lines, [4] * 4, [asset] * 4, d["prompt_direction"], job=job)
        assert out[2]["transition"] == "cut"
        assert effective_transitions([{**x, "frames": 120} for x in out])[2] == "cut"


def test_action_with_spec_or_sale_still_needs_source_and_no_truncated_headline():
    from ecom_video.semantic_mix import guard_decision, strategy

    for line in ("开盖后保温12小时，仅限实验室条件。", "打开包装后限时39元，仅限新用户。"):
        job = {"script": line}
        assert strategy(job, 0, {"kind": "video"})["status"] == "needs_evidence"
        d = guard_decision(
            job, 0, {"recipe": "product-explain-relay", "guard_outcome": "unchanged"}
        )
        assert d["recipe"] == "none" and d["suppress_headline"]


def test_literal_product_picture_is_image_not_a_measurement():
    from ecom_video.semantic_mix import strategy

    job = {"script": "这是一帧商品图，保留了切面的样子。"}
    assert strategy(job, 0, {"kind": "image"})["kind"] == "image"
    assert not strategy(job, 0, {"kind": "image"})["requires_quotation"]


def test_image_words_never_exempt_measurements_or_growth_claims():
    from ecom_video.semantic_mix import guard_decision, strategy

    for line in (
        "图片显示销量增长百分之五十，仅为示意。",
        "照片显示每杯五百毫升，仅限图示。",
        "一帧商品图展示增长百分之五十。",
    ):
        job = {"script": line}
        assert strategy(job, 0, {"kind": "image"})["requires_quotation"]
        assert guard_decision(job, 0, {"recipe": "product-explain-relay"})["recipe"] == "none"


def test_mixed_gallery_requires_complete_artifacts_and_preserves_pending_review(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ecom_video import sample_library

    library = tmp_path / "gallery"
    monkeypatch.setattr(sample_library, "SEMANTIC_LIBRARY", library)
    app = FastAPI()
    app.include_router(sample_library.semantic_mix_router())
    c = TestClient(app)
    assert c.get("/api/samples/semantic-mix").json() == []
    for style in ("evidence", "collage", "editorial"):
        folder = library / style
        folder.mkdir(parents=True)
        for name in (
            "output.mp4",
            "retake.mp4",
            "detail-retake.mp4",
            "poster.jpg",
            "shotbook.json",
            "subtitles.srt",
            "narration.wav",
            "recommendations.json",
            "prompts.json",
            "alternatives.json",
        ):
            (folder / name).write_bytes(b"fixture")
    (library / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": s, "duration": 27.4} for s in ("evidence", "collage", "editorial")
                ]
            }
        )
    )
    rows = c.get("/api/samples/semantic-mix").json()
    assert len(rows) == 3 and all(r["status"] == "needs_review" for r in rows)
    assert all(len(r["review_required"]) == 5 for r in rows)
    assert (
        c.get(
            "/api/samples/semantic-mix/editorial/detail-retake", headers={"Range": "bytes=0-2"}
        ).status_code
        == 206
    )
    assert c.get("/api/samples/semantic-mix/editorial/source").status_code == 404
    (library / "editorial/alternatives.json").unlink()
    assert c.get("/api/samples/semantic-mix").json() == []


def test_sensitive_long_quote_and_missing_picture_are_explicit():
    from ecom_video.semantic_mix import strategy

    line = "到手价39元，仅适用于" + "满足完整适用条件" * 8 + "的首次购买用户。"
    job = {
        "script": line,
        "provenance": {
            "facts": [{"id": "f", "text": line}],
            "scenes": [{"text": line, "fact_ids": ["f"]}],
        },
    }
    assert strategy(job, 0, {"kind": "video"})["status"] == "needs_short_quote"
    assert strategy({"script": "这是一张商品图。"}, 0, {"kind": "video"})["status"] == "needs_image"
