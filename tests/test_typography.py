import copy

import pytest
from test_visual_finish import props


def test_keyword_is_grounded_and_old_models_remain_optional():
    from ecom_video.delivery_revision import canonical
    from ecom_video.storyboard import Shot
    from ecom_video.typography import Typography, validate_typography

    assert Shot().typography is None
    with pytest.raises(ValueError):
        Typography(mode="remote")
    with pytest.raises(ValueError, match="本镜字卡"):
        validate_typography({"mode": "impact", "keyword": "防水"}, "透明杯壁", "看清透明杯壁。")
    with pytest.raises(ValueError, match="本镜文稿"):
        validate_typography({"mode": "impact", "keyword": "防水"}, "防水", "看清透明杯壁。")
    job = {"assets": [], "storyboard": {"shots": [{"headline": "杯壁"}]}}
    old = canonical(job)
    job["storyboard"]["shots"][0]["typography"] = None
    assert canonical(job) == old


def test_measured_typography_uses_verified_anchors_and_does_not_mutate():
    from ecom_video.typography import prepare_typography

    p = props()
    p["typography"] = {"mode": "impact", "keyword": "杯壁"}
    before = copy.deepcopy(p)
    result = prepare_typography(p, {})
    assert "".join(s["text"] for s in result["segments"]) == p["headline"]
    assert result["basis"] == "anchored_words"
    assert result["start"] == 0.5
    assert next(s for s in result["segments"] if s["keyword"])["start"] == 1.0
    assert max(s["width"] for s in result["segments"]) <= 856
    assert p == before
    p["words"][4]["anchored"] = False
    result = prepare_typography(p, {})
    assert result["basis"] == "sentence_fallback" and result["static"]
    assert result["start"] == p["voiceStart"]


def test_complete_actions_disable_text_motion_without_changing_windows():
    from ecom_video.typography import prepare_typography

    p = props()
    p["typography"] = {"mode": "reveal", "keyword": "杯壁"}
    shot = {
        "motion_plan": {
            "protect_action": True,
            "windows": [{"start": 0, "end": 2, "basis": "manual"}],
        }
    }
    before = copy.deepcopy(shot)
    result = prepare_typography(p, shot)
    assert result["static"] and result["guard"] == "action_protected"
    assert shot == before
    p.pop("typography")
    assert prepare_typography(p, shot) is None


def test_showcase_uses_declared_editorial_time_not_faked_word_anchors():
    from ecom_video.typography import prepare_typography

    p = props()
    p.update(format="showcase", words=[], typography={"mode": "reveal", "keyword": ""})
    d = prepare_typography(p, {})
    assert d["basis"] == "silent_editorial" and not d["static"]
    assert d["segments"][0]["start"] < d["segments"][1]["start"]


def test_existing_draft_save_accepts_type_and_rejects_unconfirmed_new_claims(tmp_path):
    from test_customer import approve, client, picture, plan, prepare, project

    c = client(tmp_path / "runtime")
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    job = p["job"]
    b = copy.deepcopy(job["storyboard"])
    b["shots"][0].update(
        headline=job["script"].splitlines()[0][:4], typography={"mode": "contrast", "keyword": ""}
    )
    payload = {"revision": job["storyboard_revision"], "board": b}
    r = c.put("/api/jobs/" + job["id"] + "/storyboard", json=payload)
    assert r.status_code == 200, r.text
    b["shots"][0]["typography"]["keyword"] = "从未证实"
    payload["revision"] = r.json()["storyboard_revision"]
    assert c.put("/api/jobs/" + job["id"] + "/storyboard", json=payload).status_code == 422


def test_rendered_shot_can_remove_type_and_impact_matches_actual_revision(tmp_path):
    from test_customer import approve, client, lock_and_revision, picture, plan, prepare, project

    c = client(tmp_path / "runtime")
    p = plan(c, prepare(c, approve(c, picture(c, project(c)))))
    base = "/api/customer-projects/" + p["id"]
    board = copy.deepcopy(p["job"]["storyboard"])
    for i, s in enumerate(board["shots"]):
        s["headline"] = p["job"]["script"].splitlines()[i][:4]
        s["typography"] = {"mode": "impact", "keyword": ""}
    c.put(
        "/api/jobs/" + p["job"]["id"] + "/storyboard",
        json={"revision": p["job"]["storyboard_revision"], "board": board},
    ).raise_for_status()
    p = c.get(base).json()
    body = lock_and_revision(c, p)
    body["changes"] = {"typography": None}
    impact = c.post(
        base + "/edit-impact", json={k: v for k, v in body.items() if k != "request_id"}
    )
    assert impact.status_code == 200, impact.text
    assert impact.json()["affected_shots"] == [body["shot_id"]]
    child = c.post(base + "/revise-shot", json=body)
    assert child.status_code == 201, child.text
    new = child.json()["job"]
    assert (
        next(s for s in new["storyboard"]["shots"] if s["shot_id"] == body["shot_id"])["typography"]
        is None
    )
    assert new["reviews"] == [] and new["parent_id"] == p["job"]["id"]
    diff = c.get(
        base + "/version-comparison", params={"before": p["job"]["id"], "after": new["id"]}
    ).json()
    assert diff["changed_shots"] == [body["shot_id"]] and not diff["audio_changed"]


def test_long_contrast_stays_in_measured_header_without_covering_card_media():
    from ecom_video.typography import prepare_typography

    p = props()
    p.update(
        shotRecipe="none",
        text="看清透明杯壁再看",
        headline="看清透明杯壁再看",
        typography={"mode": "contrast", "keyword": "杯"},
    )
    d = prepare_typography(p, {})
    assert d["height"] <= 224 and d["width"] <= 880
    assert d["top"] + d["height"] <= 389  # image/card media begins at410px or later
    assert "".join(s["text"] for s in d["segments"]) == p["headline"]


def test_new_titles_preserve_media_mask_and_suppress_only_title_layer():
    import subprocess
    from pathlib import Path

    from test_live_action_render import NODE

    code = (
        NODE[: NODE.index("const Component=")]
        + r"""
let root;
remotion.Composition=p=>{root=p.component;return null;};
remotion.registerRoot=c=>{root=c().props.component;};remotion.useVideoConfig=()=>({fps:30});remotion.spring=()=>1;
load('index');
const p={src:'clip.mp4',kind:'video',frames:90,text:'看清透明杯壁',headline:'透明杯壁',style:'social',format:'narrated',brand:{name:'示例',ink:'#222222',paper:'#eeeeee',accent:'#998877',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,index:1,count:2,role:'product',words:[],voiceStart:0,voiceEnd:3,captions:[],shotRecipe:'product-type-mask',transition:'cut',typography:{top:165,scale:1,height:100,width:300,mode:'impact',keyword:'杯壁',start:0,end:3,static:false,basis:'anchored_words',segments:[{text:'透明杯壁',image:'type.png',width:300,height:100,start:0,keyword:true}]},motionPlan:{version:2,amount:1,cue_frame:0,intent:'hook',strength:'balanced',guard_outcome:'unchanged',beats:[],visual_finish:'polished-v1',presentation:{zoom:28,travel_frames:30,shape:'rounded'}}};
frame=10;process.stdout.write(server.renderToStaticMarkup(React.createElement(root,p)));
"""
    )
    r = subprocess.run(
        ["node", "-e", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r.returncode == 0, r.stderr
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(r.stdout, "html.parser")
    assert soup.find("clippath").find("text").text == "透明杯壁"
    assert "visibility:hidden" in soup.select_one('[data-layer="narrative-title"]').get("style")
    assert soup.find("img", src="type.png")


def test_rebase_new_script_clears_obsolete_keyword_but_keeps_valid_type():
    import json

    from ecom_video.storyboard import rebase_board

    b = {
        "shots": [{"headline": "外观", "typography": {"mode": "impact", "keyword": "外观"}}],
        "creative": None,
    }
    old = {"script": "看外观", "storyboard": json.dumps(b)}
    assert rebase_board(old, "看口袋", 3, [])["shots"][0]["typography"] is None
    assert (
        rebase_board(old, "再看外观", 3, [])["shots"][0]["typography"]
        == b["shots"][0]["typography"]
    )


@pytest.mark.parametrize(
    "style,treatment,recipe,top,bottom",
    [
        ("evidence", "auto", None, 165, 315),
        ("collage", "auto", None, 165, 355),
        ("social", "hero", None, 280, 504),
        ("lab", "macro", None, 230, 405),
        ("social", "footage", None, 165, 389),
        ("social", "hero", "none", 165, 389),
    ],
)
def test_type_band_matches_legacy_and_direction_labels(style, treatment, recipe, top, bottom):
    from ecom_video.typography import prepare_typography

    p = props()
    p.update(
        style=style,
        treatment=treatment,
        shotRecipe=recipe,
        headline="看清透明杯壁再看",
        text="看清透明杯壁再看",
        typography={"mode": "contrast", "keyword": "杯"},
    )
    d = prepare_typography(p, {})
    assert d["top"] == top and d["top"] + d["height"] <= bottom + 0.001
