const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];}append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=xs;}}
test('joint proposal preview is a user action with video, and adoption uses bound server IDs',async()=>{
 const els={},requests=[];
 const c={id:'overview',name:'商品展示',payload:[{text:'原文',fact_ids:['f']}],visual_plan:[{kind:'detail',card:{name:'细节卡'},reason:'细节讲解',fallback:'原画'}],direction:{voice:{}},voice:{name:'自然',speech_rate:0},narrative:'整体到细节',source_facts:[{id:'f',text:'原文'}]};
 const bundle={version:'joint-creative-v1',basis:'b'.repeat(64),revision:8,customer_revision:3,candidates:[c],method:'联合方案'};
 c.visual_plan[0].missing=['需要正面细节'];c.shot_strategies=[{material:{status:'unknown',message:'主体待核对',candidates:[{asset_id:'a',name:'近景.mp4',source_in:2,source_end:5}]}}];
 c.material_fit={gap_count:1,unknown_count:1,missing:[{line:1,message:'缺少对应开盖镜头'}]};
 const p={id:'p',revision:3,product:{revision:8},settings:{}};
 const context={p,scriptAlternatives:bundle,busy:false,dirty:()=>false,active:()=>false,$:id=>els[id]||=(new Element()),node:(t,x)=>new Element(t,x),run:async fn=>fn(),message(){},base:()=>'/customer-projects/p',post:async(path,body)=>{requests.push({path,body});return path.endsWith('/preview')?{url:'/preview.mp4',note:'无声待核对'}:p;},adopt(){}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('ecom_video/web/customer-creative.js','utf8'),context);
 context.paintCreativeBundle(bundle);
 function all(e){return [e,...e.children.flatMap(all)];}
 let elements=all(els.scriptAlternatives);
 const display=elements.map(e=>e.textContent||'').join(' ');
 assert.match(display,/需要正面细节/);assert.match(display,/主体待核对/);assert.match(display,/近景.mp4/);assert.match(display,/2.*5/);assert.match(display,/缺少对应开盖镜头/);
 assert.equal(requests.length,0,'no synthesis or adoption on display');
 await elements.find(e=>e.tag==='button'&&e.textContent.includes('动态预览')).onclick();
 elements=all(els.scriptAlternatives);
 const video=elements.find(e=>e.tag==='video');assert.equal(video.src,'/preview.mp4');assert.equal(video.muted,true);assert.equal(video.autoplay,undefined);
 await elements.find(e=>e.tag==='button'&&e.textContent.includes('采用')).onclick();
 assert.equal(requests[1].body.basis,bundle.basis);assert.equal(requests[1].body.candidate_id,'overview');assert.equal(requests[1].body.product_revision,8);
 assert.equal(requests[1].path,'/customer-projects/p/creative-proposals/adopt');
});
