/* Real DOM event test without a browser or layout engine. Test-only LinkeDOM path is external. */
const {parseHTML}=require(process.env.LINKEDOM_MODULE||'linkedom');
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),path=require('path');
const base=path.resolve(__dirname,'..'),{document}=parseHTML(fs.readFileSync(base+'/ecom_video/web/prompts.html','utf8'));
// LinkeDOM deliberately does not implement native select.value writes; emulate only that control behavior.
const nativeSelect=s=>{Object.defineProperty(s,'value',{get(){return this._value??this.options[0]?.value??'';},set(v){this._value=v;},configurable:true});return s;};
for(const s of document.querySelectorAll('select'))nativeSelect(s);
const create=document.createElement.bind(document);document.createElement=tag=>tag==='select'?nativeSelect(create(tag)):create(tag);
const card={id:'text-as-mask',summary:'字形商品开场',use:'摘句与商品',license:'Apache-2.0',commit:'a'.repeat(40),status:'adapted',adaptation_note:'有限适配',source_url:'https://example.com/pinned',body:'<script>never execute</script>',implementation_sources:[],styles:[]};
const data={project_id:'p',title:'本地示例杯',revision:2,job_id:'j',board_revision:3,shot_id:'s',shots:[{id:'s',text:'轻装出发'}],text:'轻装出发',adapted_prompt:'本地示例杯 / 周末人群 / 轻装出发',ready:true,blockers:[],choices:[{id:'type-mask-clean-v1',name:'精致字形',recipe:'product-type-mask',prompt:'原稿摘句，沿用实拍'}]};
const requests=[];let delayed;
const ctx={document,URLSearchParams,location:{search:'?project=p&shot=s&card=text-as-mask'},fetch:async url=>{requests.push(url);if(url==='/api/customer-projects')return {ok:true,json:async()=>[{id:'p',title:'本地示例杯'}]};if(url.includes('prompt-adaptation')){if(delayed)return delayed;return {ok:true,json:async()=>data};}if(url.includes('/api/prompt-library?'))return {ok:true,json:async()=>({stats:{cards:124,styles:150},total:1,categories:{opening:{zh:'开场'}},items:[card]})};return {ok:true,json:async()=>card};},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(base+'/ecom_video/web/prompts.js','utf8'),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 for(let i=0;i<8;i++)await tick();
 assert.match(document.getElementById('libraryAdaptation').textContent,/本地示例杯/);
 assert.ok(requests.some(url=>url.includes('prompt-adaptation')&&url.includes('shot_id=s')),'URL shot must replace empty placeholder before adaptation');
 const apply=document.querySelector('.prompt-apply>a');assert.ok(apply);assert.match(apply.href,/prompt=type-mask-clean-v1/);assert.match(apply.href,/revision=2/);
 assert.equal(document.querySelectorAll('script').length,1);assert.match(document.querySelector('pre').textContent,/本地示例杯/);
 document.getElementById('libraryProject').value='';document.getElementById('libraryProject').onchange();await tick();
 assert.equal(document.querySelector('.prompt-apply>a'),null);assert.equal(document.getElementById('backToProject').href,'/create');
 assert.ok(requests.every(x=>typeof x==='string'));assert.ok(!requests.some(x=>/submit|review|revise|confirm/.test(x)));
 document.getElementById('libraryProject').value='p';let resolve;delayed=new Promise(r=>resolve=r);const work=ctx.adapt();await tick();document.getElementById('libraryProject').value='';await ctx.adapt();resolve({ok:true,json:async()=>data});await work;
 assert.equal(document.querySelector('.prompt-apply>a'),null,'stale project response cannot re-enable application');
 console.log('PASS real HTML + script: project/shot binding, literal Prompt text, selection link, clearing and stale response, no writes; no browser/layout performed');
})().catch(e=>{console.error(e);process.exitCode=1;});
