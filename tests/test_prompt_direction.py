import copy
import json
import subprocess

import pytest
from bs4 import BeautifulSoup
from test_live_action_render import NODE

from ecom_video.creative import Brief, recommend


def job():
    return {
        "id": "a" * 32,
        "title": "黑色耳机",
        "script": "先看这副黑色耳机。\n再看耳罩的纹理细节。\n双手向内转动耳罩。\n最后看完整外观。",
        "seconds": 4,
        "assets": [
            {
                "id": "video",
                "name": "耳机实拍",
                "kind": "video",
                "sha256": "b" * 64,
                "path": "video.mp4",
                "metadata": {
                    "width": 1440,
                    "height": 1440,
                    "duration": 30,
                    "customer_role": "product",
                },
            }
        ],
    }


def brief(**changes):
    return Brief(
        format="showcase",
        category="数码耳机",
        audience="年轻通勤学生",
        tone="科技、利落、有活力",
        **changes,
    )


def test_three_directions_have_distinct_executable_media_prompts_and_traceable_hits():
    source = job()
    before = copy.deepcopy(source)
    rec = recommend(source, brief())
    directions = [s["prompt_direction"] for s in rec["options"]]
    assert len({d["cards"][0]["recipe"] for d in directions}) == 3
    for direction in directions:
        assert len(direction["cards"]) == 3 and direction["version"] == "product-prompts-v1"
        for card in direction["cards"]:
            assert card["prompt"] and card["source"]["commit"] and card["source"]["license"]
            assert card["status"] == "conditional"  # focus/identity still need human checks
            assert card["matched_inputs"] and card["requirements"]
            assert len(card["digest"]) == 64
    assert rec == recommend(source, brief()) and source == before


def test_audience_tone_and_product_change_prompt_matching_not_just_display_names():
    source = job()
    first = recommend(source, brief())
    b = brief().model_dump()
    b.update(category="美妆包装", audience="重视工艺的消费者", tone="温柔、克制、安静、精致纹理")
    other = {**source, "title": "棕色瓶子", "script": "先看棕色瓶身与表面纹理。\n再看瓶口外观。"}
    changed = recommend(other, b)

    def ids(rec):
        return [s["prompt_direction"]["cards"][0]["id"] for s in rec["options"]]

    assert ids(first) != ids(changed)
    assert first["fingerprint"] != changed["fingerprint"]


def test_missing_or_low_resolution_media_never_claim_ready_or_invent_actions():
    from ecom_video.prompt_catalog import match_direction

    source = job()
    source["assets"][0]["metadata"].update(width=160, height=240)
    d = match_direction(source, brief().model_dump(), "kinetic")
    assert all(c["status"] == "blocked" and c["missing"] for c in d["cards"])
    assert all("补" in "".join(c["missing"]) for c in d["cards"])
    source["assets"] = []
    assert all(
        c["status"] == "blocked"
        for c in match_direction(source, brief().model_dump(), "social")["cards"]
    )


def test_planning_freezes_prompt_id_but_actions_and_outro_keep_continuous_footage():
    from ecom_video.customer_planner import plan_board

    source = job()
    b = brief().model_dump()
    style = recommend(source, b)["options"][0]["id"]
    settings = {"brief": b, "brand_name": "示例", "review_context": "", "sfx": False}
    board, notes = plan_board(source, settings, style)
    assert board["shots"][0]["motion_plan"]["prompt_card"]
    from ecom_video.prompt_catalog import MEDIA_RECIPES

    assert board["shots"][0]["shot_recipe"] in MEDIA_RECIPES
    assert board["shots"][2]["shot_recipe"] == board["shots"][-1]["shot_recipe"] == "none"
    assert any("Prompt" in n for n in notes)


def test_media_motion_cannot_overlap_action_and_foreign_prompt_ids_are_rejected():
    from ecom_video.shotcraft import MotionPlan, resolve_motion

    with pytest.raises(ValueError):
        MotionPlan(prompt_card="https://untrusted/executable.js")
    scene = {
        "text": "看清耳机。",
        "headline": "耳机",
        "frames": 120,
        "start": 0,
        "shot_recipe": "media-punch-in",
        "motion_plan": {
            "version": 2,
            "prompt_card": "tech-punch-v1",
            "windows": [{"start": 0, "end": 4}],
        },
    }
    before = copy.deepcopy(scene)
    assert resolve_motion(scene, [])["recipe"] == "none"
    assert scene == before


@pytest.mark.parametrize(
    "recipe,layer",
    [
        ("media-punch-in", "media-punch"),
        ("detail-dual-window", "detail-dual"),
        ("product-shape-reveal", "shape-reveal"),
    ],
)
def test_real_media_changes_and_shared_frame_clock_are_seek_safe(recipe, layer):
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('NarrativeShot').NarrativeShot;
const p={src:'same-trimmed-video.mp4',kind:'video',format:'narrated',frames:120,text:'看清耳机',headline:'耳机',style:'social',brand:{name:'示例',ink:'#222222',paper:'#eeeeee',accent:'#998877',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,index:1,count:3,words:[],voiceStart:0,voiceEnd:4,shotRecipe:RECIPE,transition:'cut',captions:[{text:'看清耳机',start:0,end:4}],motionPlan:{version:2,visual_finish:'polished-v1',amount:1,cue_frame:0,intent:'hook',strength:'balanced',guard_outcome:'unchanged',beats:[],presentation:{zoom:1.18,travel_frames:12,shape:'circle'}}};
const render=at=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,p));};
process.stdout.write(JSON.stringify({start:render(0),middle:render(25),again:render(25)}));
""".replace("RECIPE", json.dumps(recipe))
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout)
    assert result["middle"] == result["again"] and result["start"] != result["middle"]
    soup = BeautifulSoup(result["middle"], "html.parser")
    assert soup.select_one(f'[data-layer="{layer}"]') is not None
    assert soup.select_one('[data-layer="continuous-footage"]') is not None
    assert all(v["src"] == "same-trimmed-video.mp4" for v in soup.find_all("video"))
    if recipe == "detail-dual-window":
        assert len(soup.find_all("video")) == 2
    assert "看清耳机" in soup.get_text()


def test_dual_exit_is_inside_action_guard_not_just_its_entry():
    from ecom_video.shotcraft import resolve_motion

    scene = {
        "text": "看清细节",
        "headline": "看清",
        "frames": 120,
        "start": 0,
        "shot_recipe": "detail-dual-window",
        "motion_plan": {
            "version": 2,
            "prompt_card": "precision-dual-v1",
            "windows": [{"start": 3.6, "end": 4}],
        },
    }
    assert resolve_motion(scene, [])["recipe"] == "none"


def test_shape_is_unmasked_before_deferred_cue_and_after_reveal_even_at_corner_focus():
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('MediaMotion').MediaMotion;
const p={src:'clip.mp4',kind:'video',frames:150,focus_x:0,focus_y:0,brand:{paper:'#fff',ink:'#111',accent:'#ccc'},shotRecipe:'product-shape-reveal',motionPlan:{cue_frame:34,presentation:{zoom:1,travel_frames:26,shape:'circle'}}};
const render=at=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{p,mediaStyle:{width:'100%',height:'100%'}}));};
process.stdout.write(JSON.stringify([render(15),render(100)]));
"""
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    for html in json.loads(r.stdout):
        assert "clip-path" not in html and "opacity:0.28" not in html
        assert len(BeautifulSoup(html, "html.parser").find_all("video")) == 1


def test_clearing_pending_prompt_really_removes_its_media_recipe():
    import re
    from pathlib import Path

    source = Path("ecom_video/web/customer.js").read_text()
    match = re.search(r"function promptRecipe\([\s\S]+?\n}", source)
    assert match, "UI must resolve the latest pending choice, not its initial paint"
    script = (
        match.group()
        + "\nprocess.stdout.write(JSON.stringify([promptRecipe('none','media-punch-in',null),promptRecipe('blur-slide',undefined,null),promptRecipe('none',undefined,{recipe:'detail-dual-window'})]));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["none", "blur-slide", "detail-dual-window"]


def test_prompt_recommendation_api_and_gallery_remain_local_read_only(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ecom_video import sample_library
    from ecom_video.api import create_app
    from ecom_video.db import Store

    root = tmp_path / "runtime"
    store = Store(root / "workflow.db")
    source = store.create_job("耳机", "看清黑色耳机。", 3)
    with TestClient(create_app(root), base_url="http://localhost") as c:
        c.headers["X-Workflow-Token"] = c.get("/api/session").json()["token"]
        r = c.post(f"/api/jobs/{source['id']}/creative/recommend", json=brief().model_dump())
        assert r.status_code == 200
        assert len(r.json()["options"]) == 3
        assert all(
            s["prompt_direction"]["cards"][0]["status"] == "blocked" for s in r.json()["options"]
        )
        assert c.get("/api/jobs/" + source["id"]).json()["storyboard"] is None
    library = tmp_path / "examples"
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
    styles = ["social", "kinetic", "evidence"]
    for style in styles:
        folder = library / style
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).write_bytes(b"fixture")
    (library / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": s, "title": s, "description": "待听审", "duration": 23.1}
                    for s in styles
                ]
            }
        )
    )
    monkeypatch.setattr(sample_library, "PROMPT_LIBRARY", library, raising=False)
    app = FastAPI()
    app.include_router(sample_library.prompt_router())
    with TestClient(app) as c:
        rows = c.get("/api/samples/prompts").json()
        assert len(rows) == 3
        assert all(r["status"] == "needs_review" for r in rows)
        assert c.get("/api/samples/prompts/social/prompts").content == b"fixture"
        assert c.get("/api/samples/prompts/social/source").status_code == 404
        assert c.post("/api/samples/prompts/social/video").status_code == 405
        (library / "evidence/prompts.json").unlink()
        assert c.get("/api/samples/prompts").json() == []


def test_explicit_bottle_context_beats_generic_lifestyle_preferences_for_detail_card():
    from ecom_video.prompt_catalog import match_direction

    source = job()
    source.update(title="棕色滴管瓶", script="观察瓶身纹理和瓶口")
    b = brief().model_dump()
    b.update(audience="年轻学生和通勤人群", tone="亲切生活分享，轻松自然，温暖", format="narrated")
    d = match_direction(source, b, "evidence")
    assert d["cards"][0]["id"] == "bottle-dual-v1"


def test_visual_direction_is_not_replaced_by_identical_dual_windows_after_every_hook():
    from ecom_video.production_direction import choreography_for
    from ecom_video.prompt_catalog import apply_prompts

    source = job()
    rec = recommend(source, brief(), policy=4)
    lines = source["script"].splitlines()
    seen = set()
    for s in rec["options"]:
        rows = apply_prompts(
            choreography_for(lines, s["id"], [4] * 4),
            lines,
            [4] * 4,
            [source["assets"][0]] * 4,
            s["prompt_direction"],
        )
        seen.add(rows[1]["shot_recipe"])
        assert rows[1]["shot_recipe"] == s["prompt_direction"]["cards"][0]["recipe"]
    assert len(seen) == 3
