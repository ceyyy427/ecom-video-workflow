const {test}=require('node:test'),assert=require('node:assert/strict');
const state=require('../../ecom_video/web/ideas-state.js');
test('literal facts and signed measurements retain their sources; missing data stays missing',()=>{
 assert.deepEqual(state.facts('有拉链口袋｜客户资料第1页'),[{text:'有拉链口袋',source:'客户资料第1页'}]);
 assert.deepEqual(state.data('变化｜-5.2｜%｜工程示例'),[{label:'变化',value:-5.2,unit:'%',source:'工程示例'}]);
 assert.deepEqual(state.data(''),[]);
 for(const raw of ['价格 30','价格｜30｜元','标签｜NaN｜件｜来源','标签｜｜件｜来源'])assert.throws(()=>state.data(raw));
});
test('brief forwards references rather than paths or executable prompt text',()=>{
 const values={idea:'  展示口袋  ',subject:'外套',audience:'通勤',tone:'自然',mode:'footage',preferred:'blueprint',facts:'口袋有拉链｜实拍',data:''};
 const out=state.brief(values,[{origin:'upload',id:'a',path:'/private.mp4',source_in:3}]);
 assert.equal(out.idea,'展示口袋');assert.deepEqual(out.materials,[{origin:'upload',id:'a',source_in:3}]);
 assert.throws(()=>state.brief({...values,preferred:'pixel-rpg'},[]));
});
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.value='';this.textContent='';this.disabled=false;}
 append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;}
 addEventListener(name,fn){this.listeners[name]=fn;} pause(){this.paused=true;}
 querySelectorAll(tag){return this.children.flatMap(n=>[...(n.tagName===tag?[n]:[]),...n.querySelectorAll(tag)]);}
}
async function boot(){
 const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
 for(const [id,value]of Object.entries({ideaText:'桥梁怎样承重',ideaSubject:'桥梁',ideaAudience:'中学生',ideaTone:'清楚',ideaMode:'code'}))get(id).value=value;
 const options=['swiss-motion','blueprint','dataviz','paper-popup','dark-keynote','kino-montage'].map(id=>({id,name:id,native_style:'lab',script:'示例文稿',reason:'按主题解释',missing:[],source:{url:'https://example.test/source'},scenes:[{text:'一句待核对文稿',visual_reason:'场景示意'}],voice_suggestion:{tone:'自然',speed:1}}));
 const row={id:'plan1',basis:'basis1',status:'ready',completed:6,plan:{options,missing:[],brief:{},preview_seconds:7},previews:Object.fromEntries(options.map(o=>[o.id,{video:{sha256:'sha'},poster:{sha256:'sha'}}]))};
 const context={console,URLSearchParams,location:{search:''},setTimeout(){return 1;},clearTimeout(){},localStorage:{getItem(){return null;},setItem(){}},document:{getElementById:get,createElement:tag=>new Element(tag),querySelectorAll:tag=>get('ideaResults').querySelectorAll(tag)},window:{IdeaState:state},fetch:async url=>({ok:true,json:async()=>url==='/api/session'?{token:'test'}:url==='/api/film-styles'?options:url==='/api/idea-plans'?row:url.endsWith('/adopt')?{id:'new-project'}:row})};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../ecom_video/web/ideas.js'),'utf8'),context);await new Promise(r=>setImmediate(r));
 await get('ideaForm').listeners.submit({preventDefault(){}});return {get,row,context};
}
test('ready plan shows six real video controls and adoption opens a pending customer project',async()=>{
 const {get}=await boot();assert.equal(get('ideaResults').querySelectorAll('video').length,6);
 const use=get('ideaResults').querySelectorAll('button').find(n=>n.textContent==='采用这个方向');assert.ok(use);assert.equal(use.disabled,false);await use.onclick();
 assert.ok(get('ideaResults').querySelectorAll('a').some(n=>n.href==='/create?project=new-project'));
});
test('editing the brief immediately disables adoption of stale suggestions',async()=>{
 const {get}=await boot();get('ideaText').value='新主题';get('ideaForm').listeners.input();
 const buttons=get('ideaResults').querySelectorAll('button').filter(n=>n.textContent==='采用这个方向');assert.equal(buttons.length,6);assert.ok(buttons.every(n=>n.disabled));
});
