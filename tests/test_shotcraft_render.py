import json
import subprocess

from bs4 import BeautifulSoup
from test_live_action_render import NODE


def test_recipes_follow_voice_anchor_preserve_video_crop_and_seek_deterministically():
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('RecipeShot').RecipeShot;
const p={format:'narrated',shotRecipe:'marker-underline-title',transition:'cut',exitTransition:'cut',captions:[],src:'clip.mp4',kind:'video',frames:120,text:'先看瓶身颜色',headline:'瓶身颜色',style:'editorial',brand:{name:'示例',ink:'#252522',paper:'#eee9de',accent:'#9c7953',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,sample:false,words:[{text:'先',start:0,end:.2},{text:'看',start:.2,end:.4},{text:'瓶',start:1,end:1.2}],voiceStart:0,voiceEnd:3,index:2,count:4,role:'detail'};
const render=(at,changes={})=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{...p,...changes}));};
process.stdout.write(JSON.stringify({before:render(20),at:render(30),after:render(60),again:render(20),push:render(0,{transition:'push-stack'}),line:render(119,{exitTransition:'line-carry'}),none:render(52,{shotRecipe:'none'})}));
"""
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows["before"] == rows["again"]
    before = BeautifulSoup(rows["before"], "html.parser")
    after = BeautifulSoup(rows["after"], "html.parser")
    assert "opacity:0" in before.select_one('[data-layer="recipe-title"]')["style"]
    assert "opacity:1" in after.select_one('[data-layer="recipe-title"]')["style"]
    assert "scaleX(1)" in after.select_one('[data-layer="marker"]')["style"]
    assert "object-fit:contain" in after.video["style"]
    assert "transform" not in after.video["style"]
    assert not BeautifulSoup(rows["none"], "html.parser").select('[data-layer="marker"]')
    assert BeautifulSoup(rows["push"], "html.parser").select('[data-layer="push-stack"]')
    assert BeautifulSoup(rows["line"], "html.parser").select('[data-layer="line-carry"]')


def test_one_second_and_late_voice_anchors_render_with_real_remotion_interpolation():
    # The previous generic SSR clock clamps mathematically but doesn't validate ranges.
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
remotion.interpolate=req('remotion').interpolate;
const Component=load('RecipeShot').RecipeShot;
const base={format:'narrated',transition:'cut',exitTransition:'cut',captions:[],src:'clip.mp4',kind:'video',frames:30,text:'看瓶身',headline:'瓶身',style:'quiet',brand:{name:'示例',ink:'#123456',paper:'#ffffff',accent:'#9c7953',subtitle_size:58},motion:'static',fit:'contain',focus_x:.5,focus_y:.5,sample:false,voiceStart:0,voiceEnd:1,index:1,count:1,role:'detail'};
for(const recipe of ['none','marker-underline-title','scanline-annotate-focus','product-card-progressive-assemble','crash-zoom-punch','blur-slide']){
 for(const start of [.2,.96])for(const at of [0,15,29]){
  frame=at;
  const html=server.renderToStaticMarkup(React.createElement(Component,{...base,shotRecipe:recipe,words:[{text:'看',start:0,end:.1},{text:'瓶',start,end:1}]}));
  if(html.includes('NaN'))throw Error('invalid transform');
 }
}
process.stdout.write('valid');
"""
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "valid"


def test_focus_frame_contains_requested_media_point_in_actual_browser_layout():
    from playwright.sync_api import sync_playwright

    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
const Component=load('RecipeShot').RecipeShot;
frame=70;
const p={format:'showcase',shotRecipe:'scanline-annotate-focus',captions:[],src:'unused.png',kind:'image',frames:120,text:'瓶身',headline:'瓶身',style:'editorial',brand:{name:'示例',ink:'#123456',paper:'#ffffff',accent:'#9c7953',subtitle_size:58},motion:'static',fit:'contain',focus_x:.9,focus_y:.9,sample:false,words:[],voiceStart:0,voiceEnd:3,index:2,count:4,role:'detail'};
process.stdout.write(server.renderToStaticMarkup(React.createElement(Component,p)));
"""
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.route("**/*", lambda r: r.abort())
        page.set_content(
            "<style>body{margin:0}body>div{position:absolute;inset:0}</style>" + result.stdout
        )
        media = page.locator("img").bounding_box()
        focus = page.locator('[data-layer="focus"]').bounding_box()
        assert focus["x"] <= media["x"] + 0.9 * media["width"] <= focus["x"] + focus["width"]
        assert focus["y"] <= media["y"] + 0.9 * media["height"] <= focus["y"] + focus["height"]
        browser.close()
