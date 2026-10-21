"""Render the shipped TSX with real React SSR and a controlled Remotion frame clock."""

import json
import shutil
import subprocess

import pytest
from bs4 import BeautifulSoup

NODE = r"""
const fs=require('fs'),path=require('path'),Module=require('module'),{createRequire}=require('module');
const req=createRequire(path.resolve('render/remotion/package.json'));
const ts=req('typescript'),React=req('react'),server=req('react-dom/server');
let frame=0;
const remotion={useCurrentFrame:()=>frame,staticFile:s=>s,AbsoluteFill:({children,...p})=>React.createElement('div',p,children),Video:p=>React.createElement('video',p),Img:p=>React.createElement('img',p),interpolate:(v,a,b)=>b[0]+(b[1]-b[0])*Math.max(0,Math.min(1,(v-a[0])/(a[1]-a[0]))),Easing:{bezier:()=>x=>x}};
const cache={};
function load(name){
 const file=path.resolve('render/remotion/src',name+'.tsx');if(cache[file])return cache[file].exports;
 const mod=new Module(file);cache[file]=mod;
 mod.require=id=>id==='remotion'?remotion:id.startsWith('./')?load(id.slice(2)):req(id);
 const compiled=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
 mod._compile(compiled,file);return mod.exports;
}
const Component=load('directions').DirectionShot;
const props={format:'narrated',treatment:'footage',transition:'cut',exitTransition:'cut',captions:[],src:'clip.mp4',kind:'video',frames:90,text:'拿起杯子喝一口',headline:'喝一口',style:'cinema',brand:{name:'客户品牌',ink:'#252522',paper:'#eee9de',accent:'#9c7953',subtitle_size:58},motion:'static',fit:'cover',focus_x:.5,focus_y:.5,sample:false,words:[],voiceStart:.2,voiceEnd:2.5,index:2,count:2,role:'product'};
const render=(at,changes)=>{frame=at;return server.renderToStaticMarkup(React.createElement(Component,{...props,...changes}));};
process.stdout.write(JSON.stringify({normal:render(70,{}),preview:render(70,{preview:true}),aiImage:render(45,{sample:true,kind:'image',style:'lab'}),irisStart:render(0,{transition:'iris'}),irisMiddle:render(45,{transition:'iris'}),irisEnd:render(89,{exitTransition:'iris'})}));
"""


@pytest.fixture(scope="module")
def frames():
    if not shutil.which("node"):
        pytest.skip("Node required")
    r = subprocess.run(["node", "-e", NODE], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_preview_label_does_not_leak_into_customer_footage(frames):
    assert "实拍创意示例" not in frames["normal"]
    assert "实拍创意示例" in frames["preview"]


def iris_heights(html):
    result = []
    for element in BeautifulSoup(html, "html.parser").find_all("div"):
        styles = dict(
            part.split(":", 1) for part in element.get("style", "").split(";") if ":" in part
        )
        if (
            styles.get("width") == "1080px"
            and "height" in styles
            and ("bottom" in styles or "top" in styles)
        ):
            result.append(float(styles["height"].replace("px", "")))
    return result


def test_supported_iris_covers_edges_and_reveals_middle_of_footage(frames):
    assert iris_heights(frames["irisStart"]) == [960, 960]
    assert iris_heights(frames["irisMiddle"]) == [0, 0]
    assert iris_heights(frames["irisEnd"]) == [960, 960]


def test_image_observation_does_not_claim_live_action(frames):
    assert "AI示例画面" in frames["aiImage"]
    assert "外观观察 / 实拍" not in frames["aiImage"]
