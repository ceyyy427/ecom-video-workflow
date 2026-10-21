import json
import subprocess

from bs4 import BeautifulSoup
from test_live_action_render import NODE


def test_new_direction_has_distinct_framing_live_action_and_word_timed_graphics():
    script = (
        NODE[: NODE.index("const Component=")]
        + r"""
remotion.interpolate=req('remotion').interpolate;
const Component=load('RecipeShot').RecipeShot;
const p={format:'narrated',shotRecipe:'crash-zoom-punch',transition:'cut',exitTransition:'cut',captions:[],src:'clip.mp4',kind:'video',frames:120,text:'倒入咖啡，看清杯壁。',headline:'倒入咖啡',style:'cinema',brand:{name:'示例',ink:'#252522',paper:'#eee9de',accent:'#9c7953',subtitle_size:58},motion:'static',fit:'cover',focus_x:.5,focus_y:.5,sample:false,words:[],voiceStart:0,voiceEnd:3,index:1,count:6,role:'product'};
const plan={version:2,amount:.55,cue_frame:20,intent:'hook',strength:'subtle',guard_outcome:'unchanged',beats:[{text:'倒入咖啡',frame:20},{text:'看清杯壁',frame:55}]};
const render=(at,style,extra={})=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{...p,style,motionPlan:{...plan,...extra}}));};
process.stdout.write(JSON.stringify({cinema:render(22,'cinema'),social:render(22,'social',{amount:1.3,strength:'bold'}),lab:render(22,'lab'),before:render(19,'cinema'),again:render(22,'cinema'),phase:((frame=65),server.renderToStaticMarkup(React.createElement(Component,{...p,style:'lab',shotRecipe:'product-card-progressive-assemble',motionPlan:plan})))}));
"""
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows["cinema"] == rows["again"]
    stages = [BeautifulSoup(rows[s], "html.parser") for s in ("cinema", "social", "lab")]
    boxes = [s.select_one('[data-layer="continuous-footage"]')["style"] for s in stages]
    assert len(set(boxes)) == 3
    assert all("opacity:1" in b for b in boxes)
    assert all("transform" not in s.video["style"] for s in stages)
    assert (
        "opacity:0"
        in BeautifulSoup(rows["before"], "html.parser").select_one(
            '[data-layer="narrative-title"]'
        )["style"]
    )
    assert (
        stages[0].select_one('[data-layer="narrative-title"]')["style"]
        != stages[1].select_one('[data-layer="narrative-title"]')["style"]
    )
    phases = BeautifulSoup(rows["phase"], "html.parser").select('[data-layer="semantic-beat"]')
    assert [p.get_text() for p in phases] == ["倒入咖啡", "看清杯壁"]
