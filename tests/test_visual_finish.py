import base64
import copy
import io
import json
import subprocess

import pytest
from bs4 import BeautifulSoup
from PIL import Image
from test_live_action_render import NODE


def props():
    text = "看清透明杯壁再决定。"
    return {
        "text": text,
        "headline": "透明杯壁",
        "style": "social",
        "frames": 120,
        "voiceStart": 0,
        "voiceEnd": 3,
        "words": [
            {"text": c, "start": i * 0.25, "end": i * 0.25 + 0.24, "anchored": True}
            for i, c in enumerate(text)
            if c.isalnum()
        ],
        "brand": {"ink": "#252522", "paper": "#eee9de", "accent": "#9c7953", "subtitle_size": 58},
        "motionPlan": {"version": 2, "visual_finish": "polished-v1"},
    }


def test_measured_title_fits_reserved_area_without_rewriting():
    from ecom_video.visual_finish import prepare_visuals

    p = props()
    p["headline"] = "德龙ECP33.21白色咖啡机细节"
    before = copy.deepcopy(p)
    result = prepare_visuals(p)["titleLayout"]
    assert result["text"] == p["headline"]
    assert "".join(result["lines"]).replace(" ", "") == p["headline"].replace(" ", "")
    assert len(result["lines"]) <= 2 and result["width"] <= 864 and result["height"] <= 224
    assert result["font_size"] >= 58
    assert p == before


def test_only_actual_anchored_phrase_gets_timed_emphasis():
    from ecom_video.visual_finish import prepare_visuals

    p = props()
    before = copy.deepcopy(p)
    result = prepare_visuals(p)["captions"][0]
    emphasis = result["emphasis"]
    assert emphasis["text"] == "透明杯壁"
    assert emphasis["start"] == p["words"][2]["start"]
    assert emphasis["end"] == p["words"][5]["end"]
    plain = Image.open(io.BytesIO(base64.b64decode(result["image"].split(",")[1])))
    marked = Image.open(io.BytesIO(base64.b64decode(emphasis["image"].split(",")[1])))
    assert plain.size == marked.size
    assert plain.tobytes() != marked.tobytes()
    assert p == before
    p["words"][3]["anchored"] = False
    assert all("emphasis" not in c for c in prepare_visuals(p)["captions"])


def test_legacy_output_and_missing_or_ambiguous_headline_do_not_fake_anchors():
    from ecom_video.subtitle_layout import prepare_captions
    from ecom_video.visual_finish import prepare_visuals

    p = props()
    p["motionPlan"].pop("visual_finish")
    assert prepare_visuals(p) == {"captions": prepare_captions(p)}
    p["motionPlan"]["visual_finish"] = "polished-v1"
    for headline in ("未经证实的性能", "看"):
        p["headline"] = headline
        assert all("emphasis" not in c for c in prepare_visuals(p)["captions"])


def test_new_customer_plans_opt_in_while_saved_plans_stay_legacy():
    from ecom_video.production_direction import choreography_for
    from ecom_video.shotcraft import MotionPlan

    assert MotionPlan.model_validate({"version": 2}).visual_finish == "legacy"
    rows = choreography_for(["看清杯壁", "放下杯子"], "social", [3, 3])
    assert all(r["motion_plan"]["visual_finish"] == "polished-v1" for r in rows)
    with pytest.raises(ValueError):
        MotionPlan(visual_finish="https://untrusted/script.js")


def test_polished_caption_is_above_transitions_and_only_highlights_at_word_time():
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('NarrativeShot').NarrativeShot;
const p={src:'clip.mp4',kind:'video',format:'narrated',frames:90,text:'透明杯壁',headline:'透明杯壁',style:'social',brand:{name:'示例',ink:'#222222',paper:'#eeeeee',accent:'#998877',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,index:1,count:2,role:'product',words:[],voiceStart:0,voiceEnd:3,shotRecipe:'none',transition:'wipe',captions:[{text:'透明杯壁',start:0,end:3,image:'plain.png',width:300,height:80,emphasis:{text:'透明杯壁',start:1,end:2,image:'marked.png'}}],titleLayout:{text:'透明杯壁',image:'title.png',width:500,height:150,font_size:100,lines:['透明杯壁']},motionPlan:{version:2,visual_finish:'polished-v1',amount:1,cue_frame:0,intent:'hook',strength:'balanced',guard_outcome:'unchanged',beats:[]}};
const render=at=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,p));};
process.stdout.write(JSON.stringify({before:render(10),during:render(40),after:render(65),again:render(40)}));
"""
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout)
    assert result["during"] == result["again"]
    for key, expected in [
        ("before", "plain.png"),
        ("during", "marked.png"),
        ("after", "plain.png"),
    ]:
        soup = BeautifulSoup(result[key], "html.parser")
        image = soup.select_one(f'img[src="{expected}"]')
        assert image is not None
        assert "z-index:30" in image.parent["style"]
        assert soup.select_one('img[src="title.png"]')
        assert "transform" not in soup.video["style"]


def test_quality_gallery_is_read_only_and_never_claims_customer_approval(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from ecom_video import sample_library
    from ecom_video.api import create_app

    library = tmp_path / "quality"
    for style in ("cinema", "social", "lab"):
        folder = library / style
        folder.mkdir(parents=True)
        (folder / "output.mp4").write_bytes(b"fixture-read-only-artifact")
    (library / "library.json").write_text(
        json.dumps(
            {
                "samples": [
                    {"style": s, "title": s, "description": "fixture", "duration": 26}
                    for s in ("cinema", "social", "lab")
                ]
            }
        )
    )
    monkeypatch.setattr(sample_library, "QUALITY_LIBRARY", library, raising=False)
    with TestClient(create_app(tmp_path / "data"), base_url="http://localhost") as client:
        rows = client.get("/api/samples/quality").json()
        assert len(rows) == 3
        assert all(
            r["status"] == "needs_review" and "listening" in r["review_required"] for r in rows
        )
        assert client.get("/api/samples/quality/cinema/video").status_code == 200
        assert client.get("/api/samples/quality/cinema/workflow.db").status_code == 404
        assert client.post("/api/samples/quality/cinema/video").status_code in (403, 405)
        assert client.get("/api/jobs").json() == []


def test_calm_titles_keep_local_serif_when_available():
    from pathlib import Path

    from ecom_video.visual_finish import prepare_visuals

    source = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    if not source.is_file():
        pytest.skip("macOS local serif fixture unavailable")
    p = props()
    p["style"] = "cinema"
    title = prepare_visuals(p)["titleLayout"]
    assert title["font_family"] == "Songti"
    assert title["height"] <= 224


@pytest.mark.parametrize(
    "style,title_top", [("quiet", 335), ("cinema", 235), ("social", 165), ("lab", 195)]
)
def test_polished_long_titles_reserve_space_for_cards_and_footage(style, title_top):
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('NarrativeShot').NarrativeShot;
const p={src:'clip.mp4',kind:'video',format:'narrated',frames:120,text:'商品细节',headline:'商品标题',style:STYLE,brand:{name:'示例',ink:'#222222',paper:'#eeeeee',accent:'#998877',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,index:1,count:2,role:'product',words:[],voiceStart:0,voiceEnd:3,shotRecipe:'product-card-progressive-assemble',transition:'none',captions:[],titleLayout:{text:'商品标题',image:'title.png',width:800,height:224,font_size:72,lines:['商品','标题']},motionPlan:{version:2,visual_finish:'polished-v1',amount:1,cue_frame:0,intent:'hook',strength:'balanced',guard_outcome:'unchanged',beats:[{frame:0,text:'细节'}]}};
frame=80;
process.stdout.write(server.renderToStaticMarkup(React.createElement(Component,p)));
""".replace("STYLE", json.dumps(style))
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    soup = BeautifulSoup(r.stdout, "html.parser")

    def top(element):
        import re

        return float(re.search(r"(?:^|;)top:([\d.]+)px", element["style"])[1])

    cards = soup.select_one('[data-layer="semantic-beat"]').parent
    assert top(cards) >= title_top + 224 + 24
    if style in ("social", "lab"):
        assert top(soup.select_one('[data-layer="continuous-footage"]')) >= top(cards) + 90


def test_punctuation_normalized_duplicate_does_not_highlight_the_wrong_occurrence():
    from ecom_video.visual_finish import prepare_visuals

    p = props()
    p["text"] = "透明杯壁，透明，杯壁。"
    p["headline"] = "透明，杯壁"
    p["words"] = [
        {"text": c, "start": i * 0.25, "end": i * 0.25 + 0.24, "anchored": True}
        for i, c in enumerate("透明杯壁透明杯壁")
    ]
    assert all("emphasis" not in c for c in prepare_visuals(p)["captions"])


def test_overlapping_normalized_phrase_is_not_an_unambiguous_anchor():
    from ecom_video.visual_finish import prepare_visuals

    p = props()
    p["text"] = "哈哈，哈。"
    p["headline"] = "哈，哈"
    p["words"] = [
        {"text": c, "start": i * 0.4, "end": i * 0.4 + 0.39, "anchored": True}
        for i, c in enumerate("哈哈哈")
    ]
    assert all("emphasis" not in c for c in prepare_visuals(p)["captions"])
