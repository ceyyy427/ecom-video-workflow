// Node VM / DOM stand-ins only. No browser rendering or production API calls.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let ui = {};
try { ui = require('../../ecom_video/web/workbench-navigation.js'); }
catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
const first = 'a'.repeat(32), second = 'b'.repeat(32);
function dom() {
  const links = [
    {href:'/studio', hidden:false, hasAttribute:()=>false},
    {href:'/studio', hidden:true, hasAttribute:name=>name==='data-task-required'},
  ];
  const listeners = {};
  return {links, listeners, querySelectorAll:()=>links, addEventListener:(event,fn)=>listeners[event]=fn};
}
function update(doc, id) {
  assert.equal(typeof ui.update, 'function', 'Current-task navigation adapter is missing');
  ui.update(doc, id);
}
test('unsaved/new task does not offer a misleading current-task link', () => {
  const d=dom();update(d,null);
  assert.equal(d.links[0].href,'/studio');assert.equal(d.links[0].hidden,false);
  assert.equal(d.links[1].href,'/studio');assert.equal(d.links[1].hidden,true);
});
test('saved task links go to the same task in the studio', () => {
  const d=dom();update(d,first);
  for(const link of d.links){assert.equal(link.href,'/studio?job='+first);assert.equal(link.hidden,false);}
});
test('switching and cloning task updates links and clearing task removes old context', () => {
  const d=dom();update(d,first);update(d,second);
  assert.equal(d.links[1].href,'/studio?job='+second);
  update(d,null);assert.equal(d.links[1].href,'/studio');assert.equal(d.links[1].hidden,true);
});
test('invalid identifiers cannot introduce an external navigation URL', () => {
  for(const value of ['https://example.com','../other','" onclick="x',{},undefined]){
    const d=dom();update(d,value);assert.equal(d.links[0].href,'/studio');assert.equal(d.links[1].hidden,true);
  }
});
test('mount listens to the existing presentation event without changing state or form data', () => {
  assert.equal(typeof ui.mount,'function','Navigation mounting is missing');
  const d=dom(), state={job:null,confirmed:false,heard:false}, before=structuredClone(state);
  ui.mount(d,()=>state.job?.id);
  assert.deepEqual(state,before);
  state.job={id:first};d.listeners['workflow-render']();
  assert.equal(d.links[1].href,'/studio?job='+first);
  assert.equal(state.confirmed,false);assert.equal(state.heard,false);
});
test('browser entry reads current classic-script job, not stale URL or storage', () => {
  const filename='ecom_video/web/workbench-navigation.js';
  assert.equal(fs.existsSync(filename),true,'Navigation script is missing');
  const d=dom(), context=vm.createContext({document:d});
  vm.runInContext('let job = null;',context);
  vm.runInContext(fs.readFileSync(filename,'utf8'),context);
  vm.runInContext(`job={id:'${first}'};`,context);d.listeners['workflow-render']();
  assert.equal(d.links[0].href,'/studio?job='+first);
  vm.runInContext('job=null;',context);d.listeners['workflow-render']();
  assert.equal(d.links[0].href,'/studio');assert.equal(d.links[1].hidden,true);
});
