const {test}=require('node:test');
const assert=require('node:assert/strict');
let ui={};try{ui=require('../../ecom_video/web/customer-production.js');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('intake text distinguishes working copy from unchanged original',()=>{
 assert.equal(typeof ui.intakeLines,'function');
 const input={images:1,videos:4,unknown_visuals:5,warnings:['未核对权限'],assets:[{name:'a.mp4',intake:{transcoded:true,original_rotation:90,original_bytes:134364057,working_bytes:12634026}}]};
 const old=structuredClone(input),text=ui.intakeLines(input).join('\n');
 assert.match(text,/4.*实拍/);assert.match(text,/90/);assert.match(text,/原件/);assert.match(text,/未核对权限/);assert.deepEqual(input,old);
});
test('one-shot visual change never promises the same scope for speech changes',()=>{
 assert.equal(typeof ui.editImpact,'function');
 assert.match(ui.editImpact({headline:'观察衣面'}),/其他镜头.*配音/);
 assert.match(ui.editImpact({duration:4}),/重新对齐/);
 assert.match(ui.editImpact({text:'改一句文稿'}),/重新确认/);
 assert.match(ui.editImpact({speech_rate:8}),/听核/);
});
test('proposal copy displays gaps and unknowns instead of declaring ready',()=>{
 assert.equal(typeof ui.proposalLines,'function');
 const lines=ui.proposalLines({direction:{name:'生活剪贴',voice:{name:'朋友分享',speech_rate:3}},estimated_seconds:25,timing_basis:'暂估',production_notes:{structure:'先看整体',rhythm:'留给动作'},material_fit:{gap_count:2,unknown_count:3},inventory:{warnings:['没有动作证据']}}).join('\n');
 assert.match(lines,/缺口 2/);assert.match(lines,/未知 3/);assert.match(lines,/朋友分享/);assert.match(lines,/没有动作证据/);assert.doesNotMatch(lines,/已审核|可以直接发布/);
});
test('handoff copy keeps pending gates and fixture separate from customer approval',()=>{
 assert.equal(typeof ui.handoffLines,'function');
 const lines=ui.handoffLines({export_available:true,approved_for_handoff:false,fixture:true,blockers:['成片审核待完成','工程模拟记录不算客户审批']}).join('\n');
 assert.match(lines,/待审/);assert.match(lines,/成片审核待完成/);assert.match(lines,/不算客户审批/);assert.doesNotMatch(lines,/可直接发布/);
 assert.match(ui.handoffLines({export_available:false,blockers:[]}).join('\n'),/先生成/);
});
