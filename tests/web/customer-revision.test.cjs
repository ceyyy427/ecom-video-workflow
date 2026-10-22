const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync('ecom_video/web/customer-revision.js','utf8'),context);
test('timing and script changes disclose broad scope and never claim isolated reuse',()=>{
 const f=context.window.CustomerRevision.changeNotice;
 assert.match(f('script'),/全部.*文稿.*听核/);
 assert.match(f('voice'),/时长.*后续.*听核/);
 assert.match(f('visual'),/镜长.*保持/);
});
test('shot review summary distinguishes missing, rejected, fixture and genuine pass',()=>{
 const f=context.window.CustomerRevision.reviewSummary;
 assert.match(f({enabled:true,all_passed:false}),/待/);
 assert.match(f({enabled:true,all_passed:true,fixture:true}),/工程/);
 assert.match(f({enabled:true,all_passed:true,fixture:false}),/成片审核/);
});
test('actual save preview preserves draft transition and requires a second explicit action',async()=>{
 const source=fs.readFileSync('ecom_video/web/customer.js','utf8');
 const panels={};let payload,applied=0;
 const node=(tag,text)=>({tag,text,children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},scrollIntoView(){}});
 const ctx={window:{},structuredClone,settingsDirty:false,scriptDirty:false,mediaEdits:new Map(),shotEdits:new Map([['s',{transition:'wipe'}]]),p:{job:{status:'draft'}},version:()=>({revision:2,job_id:'j',board_revision:1}),base:()=>'/customer-projects/p',post:async(path,data)=>{payload=data;return {message:'邻镜',affected_shots:['s','s2'],requires:['审核'],warnings:[],can_apply:true,can_apply_single_shot:false}},node,$:id=>panels[id]??=(node('div')),run:fn=>fn(),applyShot:async()=>{applied++}};
 vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('async function saveShot(id)'),source.indexOf('function paintRevisionTools()')),ctx);
 await ctx.saveShot('s');
 assert.equal(payload.changes.transition,'wipe');assert.equal(applied,0);
 const button=panels.editImpact.children.find(x=>x.text==='按此范围保存修改');assert.equal(button.disabled,false);
 await button.onclick();assert.equal(applied,1);
 ctx.shotEdits.set('s',{transition:'cut'});
 await assert.rejects(button.onclick(),/已变化/);
});
