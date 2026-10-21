'use strict';
const $=id=>document.getElementById(id),make=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
let alignEpoch=0,previews={},token='',job=null,board=null,revision=0,recs=null,selected='',alignment=null,poll=null,dirty=false,busy=false;
async function api(path,options={}){const r=await fetch('/api'+path,{...options,headers:{'X-Workflow-Token':token,'Content-Type':'application/json',...options.headers}});const data=await r.json();if(!r.ok)throw Error(data.detail||'请求失败');return data;}
function message(t){$('message').textContent=t;}
async function act(fn){if(busy)return;busy=true;$('editor').disabled=true;try{await fn();}catch(e){message(e.message);}finally{busy=false;$('editor').disabled=job?.status!=='draft';}}
function option(value,label){const n=make('option',label);n.value=value;return n;}
function brand(){return {name:$('brandName').value,ink:$('ink').value,paper:$('paper').value,accent:$('accent').value,subtitle_size:Number($('subtitleSize').value)};}
function paintOptions(){
 $('options').replaceChildren();
 for(const s of recs.options){const card=make('button');card.type='button';card.className='direction';card.setAttribute('aria-pressed',String(selected===s.id));card.dataset.style=s.id;
 const swatch=make('div',s.name);swatch.className='swatch';swatch.style.background=s.colors[0];swatch.style.color=s.colors[1];
 if(previews[s.id]){const im=make('img');im.src=previews[s.id];im.alt=s.name+' · 使用本任务商品素材的实际风格帧';im.className='styleframe';card.append(im);}else card.append(swatch);card.append(make('strong',s.name),make('p',s.description),make('small',s.reason));if(s.missing.length)card.append(make('p',s.missing.join('；')));
 card.onclick=()=>{selected=s.id;['paper','ink','accent'].forEach((id,i)=>$(id).value=s.colors[i]);dirty=true;paintOptions();};$('options').append(card);}
 $('method').textContent=recs.method;
}
function paintShots(){
 $('shots').replaceChildren();board.shots.forEach((shot,i)=>{shot.shot_id ||= 'shot-'+String(i+1).padStart(3,'0');const row=make('div'),input=make('input'),role=make('select');input.maxLength=8;input.placeholder='短标题（从本句摘取，≤8字）';input.value=shot.headline||'';input.setAttribute('aria-label',`第 ${i+1} 镜动态字卡`);input.oninput=()=>{shot.headline=input.value;dirty=true;};for(const [v,t] of [['product','商品主画面'],['detail','细节'],['lifestyle','生活场景'],['evidence','证据截图']])role.append(option(v,t));role.value=shot.role||'product';role.onchange=()=>{shot.role=role.value;note.hidden=role.value!=='evidence';dirty=true;};const treatment=make('select'),transition=make('select'),note=make('input');
 for(const [v,t] of [['auto','自动安排镜头'],['hero','开场露出'],['macro','细节聚焦'],['split','双窗观察'],['context','场景展开'],['footage','实拍全画幅'],['end','收尾停留']])treatment.append(option(v,t));treatment.value=shot.treatment||'auto';treatment.setAttribute('aria-label',`第 ${i+1} 镜镜头编排`);treatment.onchange=()=>{shot.treatment=treatment.value;dirty=true;};
 for(const [v,t] of [['cut','直接切接'],['wipe','遮罩擦拭'],['iris','开幕露出']])transition.append(option(v,t));transition.value=shot.transition||'cut';transition.setAttribute('aria-label',`第 ${i+1} 镜转场`);transition.onchange=()=>{shot.transition=transition.value;dirty=true;};
 note.hidden=role.value!=='evidence';note.placeholder='测试/证据来源（测评证据镜头必填）';note.maxLength=500;note.value=shot.evidence_note||'';note.setAttribute('aria-label',`第 ${i+1} 镜证据来源`);note.oninput=()=>{shot.evidence_note=note.value;dirty=true;};row.append(treatment,transition,note);
 row.append(make('strong',String(i+1).padStart(2,'0')),make('p',job.script.split('\n')[i]),input,role);$('shots').append(row);});
}
async function load(id){
 ++alignEpoch;clearTimeout(poll);alignment=null;resetHearing();recs=null;previews={};selected='';dirty=false;
 job=await api('/jobs/'+id);const r=await api(`/jobs/${id}/storyboard`);board=r.board;revision=r.revision;
 history.replaceState(null,'','/studio?job='+id);$('jobSelect').value=id;$('jobLink').href=$('renderLink').href='/?job='+id;
 $('locked').textContent=job.status==='draft'?'编辑草稿；保存后回分镜页面生成。':'此版本已锁定。请回制作任务复制为新草稿后修改。';$('editor').disabled=job.status!=='draft';
 $('options').replaceChildren();$('words').replaceChildren();$('confirmation').hidden=true;$('alignStatus').textContent='请选择配音并运行本机对齐；无配音可直接保存。';
 const c=board.creative||board.previous_creative;$('format').value=c?(c.brief?.format||'auto'):'narrated';$('reviewContext').value=c?.review_context||'';formatHint();for(const id of ['category','audience','tone'])$(id).value=c?.brief[id]||'';
 const b=c?.brand||{name:'',paper:'#f3efe6',ink:'#282721',accent:'#876f50',subtitle_size:64};$('brandName').value=b.name;for(const k of ['paper','ink','accent'])$(k).value=b[k];$('subtitleSize').value=b.subtitle_size;$('sfx').checked=!!c?.sfx;
 $('voice').replaceChildren(option('','请选择成品配音'),...job.assets.filter(a=>a.kind==='audio').map(a=>option(a.id,a.name)));$('voice').value=board.narration.mode==='uploaded'?board.narration.asset_id:'';setAudio();paintShots();
 if(c){recs=await api(`/jobs/${id}/creative/recommend`,{method:'POST',body:JSON.stringify(c.brief)});selected=board.creative&&c.fingerprint===recs.fingerprint?c.style_id:'';paintOptions();if(!selected)message('商品或素材已变化，请重新生成预览并选择方向；品牌和镜头已保留。');if(board.creative&&c.alignment_id){alignment=await api(`/jobs/${id}/alignments/${c.alignment_id}`);paintAlignment();}}
}
function resetHearing(){$('heard').checked=false;$('reviewer').value='';$('stopAlign').hidden=true;}
function setAudio(){$('audio').src=$('voice').value?`/api/jobs/${job.id}/assets/${$('voice').value}`:'';}
function paintAlignment(){
 $('stopAlign').hidden=alignment.status!=='running';
 $('alignStatus').textContent=alignment.status==='running'?'本机正在识别与对齐…':alignment.status==='failed'?'对齐失败：'+alignment.error:alignment.status==='confirmed'?'已听核确认；时间已可用于分镜。':'待听核：黄色为插值或低匹配句，点击句子播放对应配音。';
 $('words').replaceChildren();$('confirmation').hidden=alignment.status!=='needs_review';
 for(const s of alignment.result?.sentences||[]){const section=make('div');section.className='alignment-sentence';const listen=make('button',`${s.text} · 锚点覆盖 ${Math.round(s.match*100)}%`);listen.type='button';listen.onclick=()=>{$('audio').currentTime=s.start;$('audio').play();};section.append(listen);const row=make('div');row.className='word-row';
 for(const w of s.words){const label=make('label',w.text+(w.anchored?'':' · 插值'));label.className='word'+(!w.anchored||!s.ok?' uncertain':'');for(const k of ['start','end']){const input=make('input');input.type='number';input.step='.01';input.min='0';input.value=w[k];input.setAttribute('aria-label',w.text+' '+k);input.disabled=alignment.status!=='needs_review';input.onchange=()=>{w[k]=Number(input.value);dirty=true;};label.append(input);}row.append(label);}section.append(row);$('words').append(section);}
}
$('recommend').onclick=()=>act(async()=>{recs=await api(`/jobs/${job.id}/creative/recommend`,{method:'POST',body:JSON.stringify({format:$('format').value,category:$('category').value,audience:$('audience').value,tone:$('tone').value})});selected='';previews={};dirty=true;paintOptions();message('三个方向已生成，正在用你的素材渲染风格预览…');previews=await api(`/jobs/${job.id}/creative/previews`,{method:'POST',body:JSON.stringify(recs.brief)});paintOptions();message('已生成三个实际风格帧，请点击选择一个。');});
$('voice').onchange=()=>{++alignEpoch;clearTimeout(poll);alignment=null;resetHearing();setAudio();$('words').replaceChildren();$('confirmation').hidden=true;$('alignStatus').textContent='配音已切换，请重新运行对齐。';dirty=true;};
$('align').onclick=()=>act(async()=>{if(!$('voice').value)throw Error('先选择成品配音');resetHearing();alignment=await api(`/jobs/${job.id}/alignments`,{method:'POST',body:JSON.stringify({asset_id:$('voice').value})});paintAlignment();const jid=job.id,aid=alignment.id,epoch=++alignEpoch,voiceId=$('voice').value;const tick=async()=>{try{const r=await api(`/jobs/${jid}/alignments/${aid}`);if(job.id!==jid||epoch!==alignEpoch||$('voice').value!==voiceId)return;alignment=r;paintAlignment();if(r.status==='running')poll=setTimeout(tick,1500);}catch(e){message(e.message);}};poll=setTimeout(tick,1500);});
$('stopAlign').onclick=()=>act(async()=>{if(!alignment)return;++alignEpoch;clearTimeout(poll);alignment=await api(`/jobs/${job.id}/alignments/${alignment.id}`,{method:'DELETE'});paintAlignment();});
$('confirm').onclick=()=>act(async()=>{if(alignment?.result?.audio_sha256!==job.assets.find(a=>a.id===$('voice').value)?.sha256)throw Error('当前播放配音与对齐结果不同，请重新对齐');if(!$('heard').checked||!$('reviewer').value.trim())throw Error('请填写听核人并确认已检查时间');alignment=await api(`/jobs/${job.id}/alignments/${alignment.id}/confirm`,{method:'POST',body:JSON.stringify({confirmed:true,reviewer:$('reviewer').value.trim(),result:{sentences:alignment.result.sentences.map(s=>({words:s.words.map(w=>({start:w.start,end:w.end}))}))}})});const r=await api(`/jobs/${job.id}/creative/apply-alignment/${alignment.id}`,{method:'POST'});board.shots.forEach((s,i)=>s.duration=r.board.shots[i].duration);board.narration=r.board.narration;dirty=true;paintAlignment();message('已应用语义拍时间。请保存方向；视频选段仍须覆盖每镜时长。');});
$('save').onclick=()=>act(async()=>{
 if(!recs||!selected)throw Error('请生成三个方向并选定一个');
 if(['format','category','audience','tone'].some(k=>$(k).value!==recs.brief[k]))throw Error('简报已修改，请重新推荐');
 if($('voice').value && (alignment?.status!=='confirmed'))throw Error('上传配音必须先完成对齐并听核确认');
 if($('voice').value){board.narration.mode='uploaded';board.narration.asset_id=$('voice').value;}
 else if(board.narration.mode==='uploaded'){board.narration.mode='silent';board.narration.asset_id=null;}
 board.previous_creative=null;board.creative_required=true;board.creative={brief:recs.brief,fingerprint:recs.fingerprint,style_id:selected,brand:brand(),alignment_id:$('voice').value?alignment?.id||null:null,sfx:$('sfx').checked,review_context:$('reviewContext').value};board.style=recs.options.find(s=>s.id===selected).family;
 const result=await api(`/jobs/${job.id}/creative`,{method:'PUT',body:JSON.stringify({board,revision})});revision=result.storyboard_revision;job=result;dirty=false;message('方向与镜头已保存。回分镜页检查素材、入点与运镜，再生成成片。');
});
function formatHint(){$('voice').disabled=$('align').disabled=$('format').value==='showcase';const text={auto:'旧版任务保留原风格；选择其他片种可使用新的镜头编排。',showcase:'用音乐、镜头和短字卡展示商品；选择此片种会关闭口播。',recommendation:'用真实场景与已确认事实种草；不自动编造亲身体验。',review:'测评需要测试条件说明、真实视频证据镜头和逐镜来源；仍须人工审核。',narrated:'成品配音驱动字卡和分镜；没有音频可在分镜页选择本机配音。'};$('formatHint').textContent=text[$('format').value];}
$('format').onchange=()=>{selected='';previews={};if($('format').value==='showcase'){++alignEpoch;clearTimeout(poll);alignment=null;resetHearing();$('voice').value='';setAudio();$('words').replaceChildren();$('confirmation').hidden=true;board.narration.mode='silent';board.narration.asset_id=null;}if(recs)paintOptions();formatHint();dirty=true;};
$('jobSelect').onchange=()=>{const id=$('jobSelect').value;if(dirty&&!confirm('有未保存修改，切换将放弃这些修改。')){$('jobSelect').value=job.id;return;}act(()=>load(id));};
$('editor').addEventListener('input',()=>dirty=true);
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
(async()=>{try{token=(await api('/session')).token;const jobs=await api('/jobs');const list=Array.isArray(jobs)?jobs:jobs.jobs;$('jobSelect').replaceChildren(...list.map(j=>option(j.id,j.title+' · '+j.status)));const id=new URLSearchParams(location.search).get('job')||list[0]?.id;if(id)await load(id);else{$('editor').disabled=true;message('先在制作任务中创建脚本并上传商品素材。');}}catch(e){message(e.message);}})();
