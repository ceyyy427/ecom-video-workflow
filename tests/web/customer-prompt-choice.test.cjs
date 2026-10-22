const {test}=require('node:test'),assert=require('node:assert/strict');
const {pending}=require('../../ecom_video/web/customer-prompt-choice.js');
const p={id:'p',revision:2,job:{id:'j',storyboard_revision:3,storyboard:{shots:[{shot_id:'s',motion_plan:{windows:[{start:1,end:2,basis:'manual'}]}}]}}};
const query=()=>new URLSearchParams({project:'p',job:'j',revision:'2',board:'3',shot:'s',prompt:'hero-soft-v1'});
const a={ready:true,project_id:'p',job_id:'j',revision:2,board_revision:3,shot_id:'s',choices:[{id:'hero-soft-v1',recipe:'product-hero-stage'}]};
test('manual library choice only produces a draft and preserves action windows',()=>{
 const before=JSON.stringify(p),result=pending(query(),p,a);
 assert.equal(result.changes.shot_recipe,'product-hero-stage');
 assert.deepEqual(result.changes.motion_plan.windows,p.job.storyboard.shots[0].motion_plan.windows);
 assert.equal(JSON.stringify(p),before);
 assert.deepEqual(Object.keys(result.changes).sort(),['motion_plan','shot_recipe']);
});
test('reject stale, wrong project, wrong shot, unadapted or unready choices',()=>{
 for(const key of ['project','job','revision','board','shot','prompt']){const q=query();q.set(key,'wrong');assert.throws(()=>pending(q,p,a));}
 assert.throws(()=>pending(query(),p,{...a,ready:false}));
 assert.throws(()=>pending(query(),p,{...a,revision:1}));
});

test('real boot keeps prompt parameters when loadProject normalizes the URL',async()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const source=fs.readFileSync(require('node:path').resolve(__dirname,'../../ecom_video/web/customer.js'),'utf8');
 const initial=source.slice(source.indexOf('(async () => { try {'),source.indexOf("$('generateDirected').onclick"));
 const stage=source.slice(source.indexOf('async function stageLibraryChoice('));
 const ctx={URLSearchParams,location:{search:'?'+query()+'&card=spotlight-hero-card'},localStorage:{getItem:()=>null},token:'',p:null,shotEdits:new Map(),loadVolcVoiceStatus:async()=>{},listProjects:async()=>{},run:async fn=>fn(),controls(){},dirty:()=>false,base:()=>'/customer-projects/p',paintShots(){},paintWorkspace(){},message(text,error){if(error)throw Error(text);},window:{CustomerPromptChoice:require('../../ecom_video/web/customer-prompt-choice.js')}};
 ctx.loadProject=async()=>{ctx.p=p;ctx.location.search='?project=p';};
 ctx.api=async url=>url==='/session'?{token:'test-token'}:a;
 vm.createContext(ctx);vm.runInContext(stage+'\n'+initial,ctx);
 await new Promise(r=>setImmediate(r));
 assert.equal(ctx.shotEdits.size,1);
 assert.equal(ctx.shotEdits.get('s').motion_plan.prompt_card,'hero-soft-v1');
 assert.equal(ctx.location.search,'?project=p');
});
