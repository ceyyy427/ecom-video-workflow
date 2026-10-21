"""Execute the shipped JS in Node with a minimal DOM and controlled response order."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed for the shipped-JS race test")
def test_history_only_latest_open_can_render_and_choose_export():
    script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const elements={};
function element(){return {value:'',hidden:true,options:[],children:[],textContent:'',append(...n){this.children.push(...n);this.options.push(...n);},replaceChildren(...n){this.children=n;this.firstChild=n[0];this.options=n;},addEventListener(){},set className(v){},get firstChild(){return this.children[0]},set firstChild(v){},disabled:false};}
const get=id=>elements[id]??=element();get('account').value='account';
const waits={};let initial=true;
const empty={account:{id:'account',name:'fixture'},start_date:'2026-10-01',end_date:'2026-10-01',status:'empty',algorithm_version:'v1',batch_seq_upper_bound:0,metric_contract:{},missing_dates:[],aggregation_allowed:true,totals:{},observed_totals:{},ratios:{},batches:[],material_daily:[],materials:[]};
const data=id=>({review_id:id,snapshot_hash:'hash-'+id,actor:'fixture',created_at:1,snapshot:empty});
const context={document:{getElementById:get,createElement:element,createTextNode:text=>({textContent:text})},crypto:{randomUUID:()=> 'fixture'},setInterval(){},fetch:async path=>{let body;if(path.endsWith('/session'))body={token:'fixture'};else if(path.endsWith('/capabilities'))body={enabled:true};else if(path.includes('?account_id='))body=[];else body=await new Promise(resolve=>waits[path.split('/').pop()]=resolve);return {ok:true,json:async()=>body};}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
async function tick(){await new Promise(resolve=>setImmediate(resolve));}
(async()=>{await tick();get('frozenHistory').value='old';const old=get('frozenHistory').onchange();get('frozenHistory').value='new';const newer=get('frozenHistory').onchange();waits.new(data('new'));await tick();waits.old(data('old'));await tick();assert.equal(get('frozenHistory').value,'new');assert.equal(get('frozenDownload').href,'/api/reviews/snapshots/new/export');assert.ok(get('frozenHash').textContent.includes('hash-new'));assert.ok(!get('frozenHash').textContent.includes('hash-old'));})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, str(Path("ecom_video/web/reviews.js"))],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
