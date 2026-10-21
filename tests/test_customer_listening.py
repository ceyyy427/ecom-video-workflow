"""Exercise shipped customer JS listening guards; full-page coverage lives in accept_workflow_e2e."""

import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={};
const get=id=>elements[id]??={value:'',checked:false,addEventListener(){},parentElement:{append(){}}};
const requests=[];
const context={FormData:class FormData{},document:{getElementById:get,createElement:()=>({append(){}})},window:{addEventListener(){}},fetch:async(path,opts)=>{
  if(path==='/api/session') return new Promise(()=>{});
  requests.push({path,body:JSON.parse(opts.body)});
  return {ok:true,json:async()=>({id:'alignment',status:'confirmed'})};
}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
vm.runInContext(`p={id:'product',inputs_changed:false,settings:{brief:{format:'narrated'}},job:{id:'child',status:'draft'},alignment:{id:'alignment',status:'needs_review',result:{sentences:[{words:[{start:0.12,end:0.42},{start:0.5,end:0.8}]}]}}};`,context);
const run=code=>vm.runInContext(code,context);
"""


def shipped_js(body):
    if not shutil.which("node"):
        pytest.skip("Node is needed for shipped-JS guard tests")
    result = subprocess.run(
        ["node", "-e", HARNESS + body, str(Path("ecom_video/web/customer.js"))],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_listening_confirmation_needs_check_name_current_input_and_reviewable_alignment():
    shipped_js(r"""
(async()=>{
  get('voiceReviewer').value='reviewer';
  await assert.rejects(run('confirmListening()'),/逐句听核/);
  get('voiceChecked').checked=true;get('voiceReviewer').value='   ';
  await assert.rejects(run('confirmListening()'),/逐句听核/);
  get('voiceReviewer').value='reviewer';run('p.inputs_changed=true');
  await assert.rejects(run('confirmListening()'),/先保存/);
  run("p.inputs_changed=false;p.alignment.status='failed'");
  await assert.rejects(run('confirmListening()'),/等待配音/);
  run("p.alignment.status='needs_review';p.job.status='queued'");
  await assert.rejects(run('confirmListening()'),/等待配音/);
  assert.equal(requests.length,0,'no invalid confirmation may write');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_listening_confirmation_persists_edited_times_without_replanning_existing_board():
    shipped_js(r"""
(async()=>{
  get('voiceChecked').checked=true;get('voiceReviewer').value='reviewer';
  run("p.job.storyboard={shots:[{id:'old-shot'}]};p.alignment.result.sentences[0].words[1].end=0.95");
  await run('confirmListening()');
  assert.deepStrictEqual(requests,[{path:'/api/jobs/child/alignments/alignment/confirm',body:{confirmed:true,reviewer:'reviewer',result:{sentences:[{words:[{start:0.12,end:0.42},{start:0.5,end:0.95}]}]}}}]);
  assert.equal(run('p.alignment.status'),'confirmed');
  assert.equal(run('p.job.storyboard.shots[0].id'),'old-shot');
  await run('confirmListening()');assert.equal(requests.length,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
