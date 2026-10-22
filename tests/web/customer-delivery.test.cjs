const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../ecom_video/web/customer.js'),'utf8');
class Element {
 constructor(){this.children=[];this.dataset={};this.check={checked:false};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(){}
 querySelector(){return this.check;}
}
function context(p){
 const els={};
 return {p,$:id=>els[id]||=(new Element()),window:{},selected:'',previews:{},settingsDirty:false,
 node:(tag,text)=>{const e=new Element();e.textContent=text;return e;},
 active:()=>false,dirty:()=>false,busy:false,paintPromptMatches(){},paintWorkspace(){},paintVolcVoice(){},localStorage:{setItem(){}}};
}
test('actual direction click enables confirmation and clears an obsolete check',()=>{
 const ctx=context({id:'fixture',settings:{brief:{format:'showcase'}},recommendations:{options:['a','b','c'].map(id=>({id,name:id}))},delivery_reviews:{enabled:true,direction_basis:'facts-sha'}});
 vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(require.resolve('../../ecom_video/web/customer-delivery.js'),'utf8'),ctx);
 vm.runInContext(source.slice(source.indexOf('function paintDirections()'),source.indexOf('async function showPreviews()')),ctx);
 ctx.paintDirections();ctx.paintDeliveryReviews();
 assert.equal(ctx.$('delivery-direction-confirm').disabled,true);
 ctx.$('delivery-direction').check.checked=true;
 ctx.$('directions').children[0].children[0].onclick();
 assert.equal(ctx.selected,'a');
 assert.equal(ctx.$('delivery-direction-confirm').disabled,false);
 assert.equal(ctx.$('delivery-direction').check.checked,false);
});
test('explicit source cuts disable duplicate primary source controls, legacy stays editable',()=>{
 const cut={asset_id:'a',source_in:0,source_duration:2,duration:2};
 const shot={shot_id:'s',asset_id:'a',source_in:0,duration:2,headline:'',source_cuts:[cut]};
 const ctx=context({settings:{delivery_version:1},job:{id:'j',status:'draft',script:'原稿',assets:[{id:'a',kind:'video',name:'a.mp4',metadata:{}}],storyboard:{shots:[shot]}}});
 const fields=[];
 Object.assign(ctx,{shotEdits:new Map(),field:(row,label)=>{const e=new Element();fields.push({label,e});return e;},option:()=>new Element(),cutEditor(){},candidatePicker(){},paintShotVoice(){}});
 vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function paintShots()'),source.indexOf('async function applyShot(')),ctx);
 ctx.paintShots();
 for(const label of ['第 1 镜画面','第 1 镜素材入点'])assert.equal(fields.find(f=>f.label===label).e.disabled,true,label);
 shot.source_cuts=null;fields.length=0;ctx.paintShots();
 assert.equal(!!fields.find(f=>f.label==='第 1 镜素材入点').e.disabled,false);
});
test('cut input keeps independent source and screen lengths and full action coordinates',()=>{
  const ui=require('../../ecom_video/web/customer-delivery.js');
  const input=[{asset_id:'a',source_in:'1.3',source_duration:'8.5',duration:'8.5',reason:'泼水原速',action_name:'泼水',action_start:'1.3',action_end:'9.8'}];
  const before=structuredClone(input), result=ui.readCuts(input);
  assert.equal(result[0].source_in,1.3);
  assert.deepEqual(result[0].complete_action,{name:'泼水',start:1.3,end:9.8});
  assert.deepEqual(input,before);
  assert.throws(()=>ui.readCuts([{...input[0],duration:'NaN'}]));
});
