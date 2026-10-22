"""Pure React server rendering: no browser or Computer Use."""

import json
import subprocess

from bs4 import BeautifulSoup
from test_live_action_render import NODE


def test_client_keeps_semantic_recipes_and_both_transition_halves_without_chrome():
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('ClientShot').ClientShot;
const base={clientPresentation:true,src:'clip.mp4',kind:'video',frames:120,text:'看看口袋再看下摆',headline:'口袋',style:'editorial',brand:{name:'工程品牌',ink:'#282721',paper:'#f3efe6',accent:'#ffda73',subtitle_size:76},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,index:2,count:6,role:'detail',words:[],voiceStart:0,voiceEnd:4,captions:[],motionPlan:{version:2,amount:1,cue_frame:45,intent:'detail',strength:'balanced',guard_outcome:'unchanged',beats:[{text:'口袋',frame:45},{text:'下摆',frame:70}]}};
const render=(at,extra={})=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{...base,...extra}));};
process.stdout.write(JSON.stringify({scan:render(60,{shotRecipe:'scanline-annotate-focus'}),assemble:render(95,{shotRecipe:'product-card-progressive-assemble'}),early:render(20,{shotRecipe:'marker-underline-title'}),late:render(90,{shotRecipe:'marker-underline-title'}),plain:render(60,{shotRecipe:'none'}),wipeIn:render(0,{transition:'wipe'}),wipeOut:render(119,{exitTransition:'wipe'}),pushIn:render(0,{transition:'push-stack'}),pushOut:render(119,{exitTransition:'push-stack'}),iris:render(0,{transition:'iris'}),line:render(119,{exitTransition:'line-carry'}),pass:render(2,{transition:'media-pass'}),panels:render(60,{shotRecipe:'same-frame-panels'})}));
"""
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    rows = {k: BeautifulSoup(v, "html.parser") for k, v in json.loads(run.stdout).items()}
    assert rows["scan"].select_one('[data-layer="focus"]')
    assert [e.text for e in rows["assemble"].select('[data-layer="semantic-beat"]')] == [
        "口袋",
        "下摆",
    ]
    assert "opacity:0" in rows["early"].select_one('[data-layer="narrative-title"]')["style"]
    assert "opacity:1" in rows["late"].select_one('[data-layer="narrative-title"]')["style"]
    assert not rows["plain"].select_one('[data-layer="narrative-title"]')
    for kind in ("wipeIn", "wipeOut", "iris"):
        assert len(rows[kind].find_all("div")) > len(rows["plain"].find_all("div"))
    for kind in ("pushIn", "pushOut"):
        assert rows[kind].select_one('[data-layer="push-stack"]')
    assert rows["line"].select_one('[data-layer="line-carry"]')
    assert rows["pass"].select_one('[data-layer="media-pass"]')
    for row in rows.values():
        assert (
            "工程品牌" not in row.text and "02 / 06" not in row.text and "同帧取景" not in row.text
        )
        assert "object-fit:contain" in row.video["style"]
