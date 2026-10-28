'use strict';
const el=id=>document.getElementById(id),state=window.IdeaState;
let currentPlan=null,dirty=false,timer=null,token='',materials=[],projectMedia=[],productProject=null,inputVersion=0;
function item(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function json(url,options){const r=await fetch(url,options),d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'输入不完整或格式不对，请检查事实、数值和素材来源');return d;}
async function post(url,data){if(!token)token=(await json('/api/session')).token;return json(url,{method:'POST',headers:{'Content-Type':'application/json','X-Workflow-Token':token},body:JSON.stringify(data)});}
function values(){return {idea:el('ideaText').value,subject:el('ideaSubject').value,audience:el('ideaAudience').value,tone:el('ideaTone').value,mode:el('ideaMode').value,preferred:el('ideaPreferred').value,facts:el('ideaFacts').value,data:el('ideaData').value,platform:el('ideaPlatform')?.value||'',objective:el('ideaObjective')?.value||'product_showcase',duration:el('ideaDuration')?.value||'24'};}
function stale(){inputVersion++;dirty=true;if(currentPlan){for(const b of el('ideaResults').querySelectorAll('button'))b.disabled=true;el('ideaState').textContent='内容已修改。请重新生成预览后再采用，旧方案仍保留。';}}
function paintUploads(){el('ideaUploads').replaceChildren();materials.forEach((a,index)=>{const row=item('div',a.name+' · '+(a.kind==='video'?'实拍':'图片'));const offset=item('input','');offset.type='number';offset.min='0';offset.max='600';offset.step='0.1';offset.value=a.source_in||0;offset.disabled=a.kind!=='video';offset.setAttribute?.('aria-label',a.name+'的入点（秒）');offset.onchange=()=>{a.source_in=Number(offset.value);stale();};row.append(offset);const remove=item('button','移除');remove.type='button';remove.className='secondary';remove.onclick=()=>{materials.splice(index,1);paintUploads();stale();};row.append(remove);el('ideaUploads').append(row);});}
function paint(row){
 currentPlan=row;el('ideaResults').replaceChildren();
 el('ideaPositioning').hidden=!row.plan.positioning;el('ideaPositioning').textContent=row.plan.positioning?'这次先讲：'+(row.plan.positioning.core_selling_point?.text||'商品依据待补充')+' · 依据仍需在制作时人工核对。':'';
 const publication=el('ideaPublication');publication.hidden=!row.plan.publication_copy;publication.replaceChildren();if(row.plan.publication_copy){const c=row.plan.publication_copy;publication.append(item('summary',(c.platform==='douyin'?'抖音':'小红书')+'发布文案草稿'),item('p',c.titles.join(' / ')),item('pre',c.body),item('p','#'+c.tags.join(' #')),item('small','仅为文案与封面建议，尚未发布。完整来源保留在下载方案中。'));}
 for(const option of row.plan.options){
  const card=item('article','');card.className='card';card.append(item('h2',option.name),item('p',option.reason));
  const ready=row.previews[option.id],base='/api/idea-plans/'+row.id;
  if(ready){const video=item('video','');video.controls=true;video.preload='none';video.playsInline=true;video.poster=base+'/previews/'+option.id+'/poster';video.src=base+'/previews/'+option.id+'/video';video.addEventListener('play',()=>{for(const other of document.querySelectorAll('video'))if(other!==video)other.pause();});card.append(video);card.append(item('small','7秒静音动态预览 · 待人工选择'));}
  else card.append(item('div',row.status==='rendering'?'本机正在生成画面…':'等待生成预览'));
  const details=item('details','');details.append(item('summary','查看文稿、编排与依据'),item('pre',option.script));
  for(const s of option.scenes)details.append(item('p',s.visual_reason));
  details.append(item('p','声音建议：'+option.voice_suggestion.tone+' · 建议语速 '+option.voice_suggestion.speed+'倍；实际配音仍须试听。'));
  const link=item('a','固定版本参考来源');link.href=option.source.url;link.target='_blank';link.rel='noopener noreferrer';details.append(link);const download=item('button','下载这份方案');download.type='button';download.className='secondary';download.onclick=()=>{const file={...row,selected_option:option.id,approval_note:'下载仅供核对，不代表人工审批'};const url=URL.createObjectURL(new Blob([JSON.stringify(file,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='jianxu-plan-'+row.id+'-'+option.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};details.append(download);card.append(details);
  if(option.feasibility==='needs_materials')card.append(item('p','该方向缺完整画面：'+option.gaps.join('；')));
  const choose=item('button','采用这个方向');choose.type='button';choose.disabled=dirty||row.status!=='ready'||!!row.repair_needed||option.feasibility==='needs_materials';choose.onclick=async()=>{
   choose.disabled=true;try{const p=await post(base+'/adopt',{basis:row.basis,option_id:option.id});const go=item('a','进入客户工作台，核对事实与文稿');go.href='/create?project='+encodeURIComponent(p.id);card.append(go);el('ideaState').textContent='已创建待确认项目。保留所选文稿、镜头配方与素材；尚未确认任何事实、听核或成片。';}catch(e){el('ideaState').textContent=e.message;choose.disabled=dirty;}
  };card.append(choose);el('ideaResults').append(card);
 }
 const status={draft:'方案已就绪，尚未排队',queued:'已排队；一键启动中的后台工作进程会逐个渲染',rendering:'正在本机渲染',ready:'六个预览已完成，比较后选择一个方向',cancelled:'本次预览已取消，已完成项保留',failed:'有方向未完成，可手动重试'};
 if(!dirty)el('ideaState').textContent=(status[row.status]||row.status)+'（'+row.completed+'/6）。'+(row.error?' '+row.error:'')+(row.repair_needed?' 预览文件缺失或变化，可重试未完成方向。':'')+' '+row.plan.missing.join('；');
 el('ideaCancel').hidden=!['queued','rendering'].includes(row.status);el('ideaRetry').hidden=!row.repair_needed&&!['cancelled','failed'].includes(row.status);
}
function poll(){clearTimeout(timer);if(!currentPlan||!['queued','rendering'].includes(currentPlan.status))return;const id=currentPlan.id;timer=setTimeout(async()=>{try{const row=await json('/api/idea-plans/'+id);if(currentPlan?.id===id){paint(row);poll();}}catch(e){el('ideaState').textContent=e.message+' 刷新页面可恢复查看。';}},2500);}
async function uploadPending(){
 const files=Array.from(el('ideaFiles').files||[]);if(!files.length)return;
 if(materials.length+files.length>8)throw Error('先选最多8份素材，避免预览时重复装入大文件');
 if(!el('ideaUsage').checked||!el('ideaSource').value.trim())throw Error('上传前请填写来源并核对使用范围');
 if(!token)token=(await json('/api/session')).token;
 for(const file of files){const data=new FormData();data.append('file',file);data.append('source_note',el('ideaSource').value.trim());data.append('usage_confirmed','true');const a=await json('/api/idea-uploads',{method:'POST',headers:{'X-Workflow-Token':token},body:data});materials.push(a);paintUploads();}
 el('ideaFiles').value='';
}
async function startIdeas(){
 const bootVersion=inputVersion;el('ideaForm').addEventListener('input',stale);el('ideaForm').addEventListener('change',stale);
 const styles=await json('/api/film-styles');for(const s of [...styles].sort((a,b)=>Number(state.executable.includes(b.id))-Number(state.executable.includes(a.id)))){const n=item('option',s.name+(state.executable.includes(s.id)?' · 可动态预览':' · 仅参考'));n.value=s.id;el('ideaPreferred').append(n);}
 el('ideaForm').addEventListener('submit',async event=>{
  event.preventDefault();el('ideaSubmit').disabled=true;el('ideaState').textContent='正在准备本机预览；不会生成声音或自动批准成片。';
  try{await uploadPending();const submittedVersion=inputVersion,v=values();if(el('ideaUseProduct')?.checked&&(!v.platform||!productProject))throw Error('请先选择国内平台与已有项目，载入当前已确认事实');const body=v.platform?state.domestic(v,materials,el('ideaUseProduct')?.checked?productProject:null):state.brief(v,materials),row=await post(v.platform?'/api/operations/plans':'/api/idea-plans',body);dirty=inputVersion!==submittedVersion;paint(row);if(dirty){el('ideaState').textContent='生成方案期间输入已修改，请按当前内容重新生成后再采用。';return;}localStorage.setItem('jianxu-idea-plan',row.id);const queued=row.status==='ready'?row:await post('/api/idea-plans/'+row.id+'/previews',{basis:row.basis});paint(queued);poll();}
  catch(e){el('ideaState').textContent=e.message;}finally{el('ideaSubmit').disabled=false;}
 });
 el('ideaCancel').onclick=async()=>{try{const row=await json('/api/idea-plans/'+currentPlan.id+'/previews',{method:'DELETE',headers:{'X-Workflow-Token':token||(token=(await json('/api/session')).token)}});paint(row);poll();}catch(e){el('ideaState').textContent=e.message;}};
 el('ideaRetry').onclick=async()=>{try{if(dirty)throw Error('输入已变，请重新生成方案');paint(await post('/api/idea-plans/'+currentPlan.id+'/previews',{basis:currentPlan.basis}));poll();}catch(e){el('ideaState').textContent=e.message;}};
 el('ideaReference').onclick=async()=>{try{const v=values(),result=await post('/api/film-styles/recommend',{idea:v.idea,audience:v.audience,tone:v.tone,mode:v.mode,preferred:v.preferred||null});clearTimeout(timer);currentPlan=null;el('ideaCancel').hidden=true;el('ideaRetry').hidden=true;el('ideaResults').replaceChildren();for(const s of result.options){const card=item('article','');card.append(item('h2',s.name),item('p',s.reason),item('pre',s.adapted_prompt));el('ideaResults').append(card);}el('ideaState').textContent='参考资料，不代表可执行模板；要进入制作请生成六个动态预览。';}catch(e){el('ideaState').textContent=e.message;}};
 el('ideaProject').onchange=async()=>{try{el('ideaProjectAsset').replaceChildren(item('option','选择素材'));projectMedia=[];productProject=null;el('ideaUseProduct').checked=false;const id=el('ideaProject').value;if(id){const p=await json('/api/customer-projects/'+id);if(el('ideaProject').value!==id)return;productProject=p;projectMedia=p.media.filter(a=>a.kind!=='audio');for(const a of projectMedia){const op=item('option',a.name);op.value=a.id;el('ideaProjectAsset').append(op);}}}catch(e){el('ideaState').textContent=e.message;}};
 el('ideaAddAsset').onclick=()=>{try{if(!el('ideaUsage').checked)throw Error('请先核对已有素材的使用范围');const a=projectMedia.find(a=>a.id===el('ideaProjectAsset').value);if(!a)throw Error('请先选一份项目素材');if(materials.length>=8)throw Error('最多选择8份素材');if(materials.some(m=>m.id===a.id))throw Error('这份素材已加入，可直接调整入点');materials.push({origin:'customer',project_id:el('ideaProject').value,id:a.id,name:a.name,kind:a.kind,source_in:a.source_in});paintUploads();stale();}catch(e){el('ideaState').textContent=e.message;}};
 const sourceProject=new URLSearchParams(location.search).get('sourceProject');
 const id=sourceProject?null:(new URLSearchParams(location.search).get('plan')||localStorage.getItem('jianxu-idea-plan'));
 if(id){try{const row=await json('/api/idea-plans/'+encodeURIComponent(id));if(inputVersion!==bootVersion){el('ideaState').textContent='你已开始填写新内容，历史方案未覆盖当前输入。';return;}const b=row.plan.brief;el('ideaPlatform').value=row.plan.suite_brief?.platform||'';el('ideaObjective').value=row.plan.suite_brief?.objective||'product_showcase';el('ideaDuration').value=String(row.plan.suite_brief?.duration_s||24);for(const [id,key]of [['ideaText','idea'],['ideaSubject','subject'],['ideaAudience','audience'],['ideaTone','tone'],['ideaMode','mode'],['ideaPreferred','preferred']])el(id).value=b[key]||'';el('ideaFacts').value=b.facts.map(f=>f.text+'｜'+f.source).join('\n');el('ideaData').value=b.data.map(d=>[d.label,d.value,d.unit,d.source].join('｜')).join('\n');materials=row.plan.materials.map(a=>({origin:a.origin,id:a.id,project_id:a.project_id,name:a.name,kind:a.kind,source_in:a.source_in}));paintUploads();paint(row);poll();}catch(e){el('ideaState').textContent='历史方案无法载入：'+e.message;}}
 try{for(const p of await json('/api/customer-projects')){const op=item('option',p.title);op.value=p.id;el('ideaProject').append(op);}}catch{ /* Existing material selection remains optional. */ }
 if(sourceProject&&[...el('ideaProject').options].some(o=>o.value===sourceProject)){el('ideaProject').value=sourceProject;await el('ideaProject').onchange();if(productProject){const p=productProject;el('ideaText').value=p.product.title;el('ideaSubject').value=p.product.title.length<=60?p.product.title:'';el('ideaAudience').value=p.settings.brief.audience||'';el('ideaTone').value=p.settings.brief.tone||'';el('ideaMode').value='footage';el('ideaState').textContent='已打开当前商品资料；请核对事实引用、素材使用范围并选择画面，再生成新预览。';}}
}
startIdeas().catch(e=>{el('ideaState').textContent=e.message;});
