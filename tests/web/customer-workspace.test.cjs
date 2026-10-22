// Node-only DOM stand-ins: these do not verify browser rendering or layout.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let ui = {};
try { ui = require('../../ecom_video/web/customer-workspace.js'); }
catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }

function summarize(state) {
  assert.equal(typeof ui.summarize, 'function', 'Read-only workspace summary is missing');
  return ui.summarize(state);
}
function project() {
  return {id:'project-a', revision:4, product:{title:'客户杯子', current_review_id:null,
    current_draft_id:'draft-1', sources:[], script_approvals:[]}, media:[],
    settings:{brief:{format:'narrated'}}, recommendations:null, job:null, alignment:null};
}

test('planned delivery board stays pending until final human style confirmation',()=>{
 const p=project();p.job={id:'new',status:'draft',storyboard:{shots:[],creative:{style_id:'cinema'}},artifacts:[]};
 p.delivery_reviews={enabled:true,direction:{reviewer:'editor'},storyboard:null};
 let result=summarize({project:p,selected:'cinema'});
 assert.equal(result.checks[2].state,'pending');
 p.delivery_reviews.storyboard={reviewer:'editor'};
 result=summarize({project:p,selected:'cinema'});
 assert.equal(result.checks[2].state,'done');
});

test('empty state does not invent a saved project or media', () => {
  const r = summarize({});
  assert.equal(r.title, '新建商品项目');
  assert.equal(r.preview, null);
  assert.equal(r.next.href, '#projectControls');
  assert.equal(r.checks.every(c => c.state === 'pending'), true);
});
test('needs_review stays pending even when a video artifact exists', () => {
  const p=project();p.job={id:'job-a',status:'needs_review',artifacts:[{kind:'video'}]};
  const r=summarize({project:p, mode:'film'});
  assert.equal(r.checks[4].state, 'pending');
  assert.match(r.checks[4].text, /待人工审片/);
  assert.equal(r.preview.src, '/api/jobs/job-a/artifacts/video');
});
test('old ready film is not presented as approval of changed inputs', () => {
  const p=project();p.inputs_changed=true;
  p.job={id:'old-job',status:'ready',artifacts:[{kind:'video'}]};
  const r=summarize({project:p, mode:'film'});
  assert.equal(r.checks[4].state, 'pending');
  assert.match(r.checks[4].text, /旧版/);
  assert.match(r.preview.label, /旧版/);
});
test('dirty local input and matching current script approval are distinct', () => {
  const p=project();p.product.current_review_id='facts-1';
  p.product.script_approvals=[{draft_id:'old-draft'}];
  const frozen=structuredClone(p);
  const r=summarize({project:p, dirty:true});
  assert.match(r.save, /未保存/);
  assert.equal(r.checks[0].state, 'done');
  assert.equal(r.checks[1].state, 'pending');
  assert.deepEqual(p,frozen);
});
test('showcase needs no voice but still needs human film review', () => {
  const p=project();p.settings.brief.format='showcase';
  const r=summarize({project:p});
  assert.equal(r.checks[3].state, 'neutral');
  assert.match(r.checks[3].text,/无需配音/);
  assert.equal(r.checks[4].state,'pending');
});
test('unsaved edits cannot be labeled as an approved current script', () => {
  const p=project();p.product.script_approvals=[{draft_id:'draft-1'}];
  const r=summarize({project:p,dirty:true});
  assert.equal(r.checks[1].state,'pending');
  assert.match(r.checks[1].text,/未保存/);
});
test('next step points to the unsaved editor instead of a blocked hearing action', () => {
  const p=project();p.product.current_review_id='facts-1';p.product.sources=[{id:'source-a'}];
  p.product.script_approvals=[{draft_id:'draft-1'}];
  p.recommendations={options:[{id:'quiet',name:'克制质感'}]};
  const r=summarize({project:p,selected:'quiet',dirty:true,editStep:'step2'});
  assert.equal(r.next.href,'#step2');
  assert.match(r.next.text,/保存/);
  assert.equal(summarize({project:p,dirty:true,editStep:'step4'}).next.href,'#step4');
});
test('selected direction is not called a saved or confirmed direction', () => {
  const p=project();p.recommendations={options:[{id:'quiet',name:'克制质感'}]};
  const r=summarize({project:p,selected:'quiet',previews:{quiet:'/api/local-frame'},mode:'direction'});
  assert.equal(r.checks[2].state,'pending');
  assert.match(r.checks[2].text,/待保存/);
  assert.equal(r.preview.src,'/api/local-frame');
  assert.equal(r.preview.kind,'image');
});

class Element {
  constructor(){this.attrs={};this.hidden=false;this.dataset={};this.listeners={};this.srcWrites=0;this.pauses=0;this.children=[];}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='src')this.srcWrites++;}
  getAttribute(k){return this.attrs[k] ?? null;}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,fn){this.listeners[k]=fn;}
  pause(){this.pauses++;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
}
function dom() {
  const elements=new Map();
  const links=Array.from({length:4},(_,i)=>{const e=new Element();e.setAttribute('href','#step'+(i+1));return e;});
  const modes=['material','direction','film'].map(v=>{const e=new Element();e.dataset.previewMode=v;return e;});
  return {elements,links,modes,
    getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
    querySelectorAll(selector){return selector==='[data-preview-mode]'?modes:links;}};
}
function mount(document) {
  assert.equal(typeof ui.mount,'function','Workspace mounting is missing');
  return ui.mount(document,{});
}
test('polling identical media does not reset an actively playing preview', () => {
  const d=dom(),workspace=mount(d),p=project();
  p.job={id:'job-a',status:'needs_review',artifacts:[{kind:'video'}]};
  workspace.update({project:p});
  const video=d.getElementById('workspacePreview');
  assert.equal(video.getAttribute('src'),'/api/jobs/job-a/artifacts/video');
  const before=[video.srcWrites,video.pauses];
  workspace.update({project:p});
  assert.deepEqual([video.srcWrites,video.pauses],before);
});
test('changing project removes old preview even when next project has no media', () => {
  const d=dom(),workspace=mount(d),p=project();
  p.media=[{id:'asset-a',name:'杯子图',kind:'image'}];workspace.update({project:p});
  assert.equal(d.getElementById('workspaceImage').hidden,false);
  const next=project();next.id='project-b';workspace.update({project:next});
  assert.equal(d.getElementById('workspaceImage').hidden,true);
  assert.equal(d.getElementById('workspaceImage').getAttribute('src'),null);
  assert.equal(d.getElementById('workspaceEmpty').hidden,false);
});
test('preview and navigation only render text; no business request or confirmation', () => {
  const d=dom();d.getElementById('work').hidden=true;d.getElementById('work').setAttribute('disabled','');
  const workspace=mount(d),p=project();
  p.product.title='<img src=x onerror=alert(1)>';
  workspace.update({project:p});
  assert.equal(d.getElementById('workspaceProjectTitle').textContent,p.product.title);
  assert.equal(d.getElementById('factsChecked').attrs.checked,undefined);
  assert.equal(d.getElementById('work').hidden,true);
  assert.equal(d.getElementById('work').getAttribute('disabled'),''); // mount never changes business gates
  assert.equal(d.links[0].getAttribute('href'),'#step1');
});

test('new draft in same project clears the previous film instead of keeping stale playback', () => {
  const d=dom(),workspace=mount(d),p=project();
  p.job={id:'job-a',status:'needs_review',artifacts:[{kind:'video'}]};workspace.update({project:p});
  p.job={id:'job-b',status:'draft',artifacts:[]};workspace.update({project:p});
  assert.equal(d.getElementById('workspacePreview').hidden,true);
  assert.equal(d.getElementById('workspacePreview').getAttribute('src'),null);
});

test('actual three-direction renderer keeps warnings visible and details outside selection buttons', () => {
  const d=dom(),p=project();
  p.recommendations={version:2,options:['a','b','c'].map(id=>({id,name:id,description:'真实说明',reason:'适合当前人群',missing:['还缺实拍动作']}))};
  const source=fs.readFileSync(path.join(__dirname,'../../ecom_video/web/customer.js'),'utf8');
  const functionSource=source.slice(source.indexOf('function paintDirections()'),source.indexOf('async function showPreviews()'));
  const context={p,selected:'',previews:{},settingsDirty:false,$:id=>d.getElementById(id),
    node:(tag,text,cls)=>{const e=new Element();e.tagName=tag;e.textContent=text;e.className=cls;return e;},
    active:()=>false,paintPromptMatches:()=>{},paintWorkspace:()=>{},paintVolcVoice:()=>{},paintDeliveryReviews:()=>{},localStorage:{setItem:()=>{}}};
  vm.runInNewContext(functionSource,context);context.paintDirections();
  assert.equal(d.getElementById('directions').children.length,3);
  for(const option of d.getElementById('directions').children){
    const [button,details]=option.children;
    assert.equal(button.tagName,'button');assert.equal(details.tagName,'details');
    assert.equal(button.children.some(e=>e.tagName==='details'),false);
    assert.equal(button.children.some(e=>e.textContent==='还缺实拍动作'),true,'Critical missing material must not only appear in collapsed details');
  }
  d.getElementById('directions').children[1].children[0].onclick();
  assert.equal(context.selected,'b');
  assert.equal(d.getElementById('directions').children[1].children[0].getAttribute('aria-pressed'),'true');
});

test('actual paste handler refreshes summary when no native input event fires', () => {
  const d=dom(),p=project(),observed=[];
  p.product.fact_reviews=[];p.product.facts=[];p.product.script_approvals=[{draft_id:'draft-1'}];
  d.getElementById('scriptPaste').value='新的一句口播';d.getElementById('scriptChecked').checked=true;
  const source=fs.readFileSync(path.join(__dirname,'../../ecom_video/web/customer.js'),'utf8');
  const renderer=source.slice(source.indexOf('function renderScenes()'),source.indexOf('function paintDirections()'));
  const paste=source.slice(source.indexOf("$('applyScript').onclick ="),source.indexOf("$('approveScript').onclick ="));
  const context={p,scenes:[],scriptDirty:false,$:id=>d.getElementById(id),currentDraft:()=>null,message:()=>{},
    node:(tag,text)=>{const e=new Element();e.tagName=tag;e.textContent=text;return e;},
    paintWorkspace:()=>observed.push(summarize({project:p,dirty:context.scriptDirty,editStep:'step2'}))};
  vm.runInNewContext(renderer+paste,context);d.getElementById('applyScript').onclick();
  assert.equal(context.scriptDirty,true);assert.equal(d.getElementById('scriptChecked').checked,false);
  assert.equal(observed.length,1,'Programmatic script edits must refresh the read-only summary');
  assert.equal(observed[0].checks[1].state,'pending');
  assert.equal(p.product.script_approvals.length,1,'Presentation never rewrites approval history');
});
