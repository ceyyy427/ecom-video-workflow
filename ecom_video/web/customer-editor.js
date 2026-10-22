/* Editing surface: one source of time, explicit saves, no approval writes.
   Taste Skill framed-sheet composition; existing customer APIs remain authoritative. */
(function(){
'use strict';
const clamp=(n,a,b)=>Math.max(a,Math.min(b,Number(n)||0));
function frameAt(data,time){
 const shots=data.shots||[];if(!shots.length)return null;
 const t=clamp(time,0,data.duration),shot=shots.find(s=>t>=s.start&&t<s.start+s.duration)||shots.at(-1);
 let local=clamp(t-shot.start,0,shot.duration),asset=shot.asset_id,source=shot.source_in+local;
 if(shot.source_cuts?.length){let at=0;const cuts=shot.source_cuts;const cut=cuts.find(c=>{const yes=local<at+c.duration;if(!yes)at+=c.duration;return yes;})||cuts.at(-1);if(at>=shot.duration)at=shot.duration-cut.duration;asset=cut.asset_id;source=cut.source_in+clamp(local-at,0,cut.duration)*(cut.source_duration/cut.duration);}
 return {shot_id:shot.shot_id,asset_id:asset,source_time:source,caption:(data.captions||[]).filter(c=>t>=c.start&&t<c.end).map(c=>c.text).join('\n')};
}
function trimRange(shot,sourceDuration,status){
 if(!shot||shot.source_cuts?.length||shot.motion_plan?.windows?.some(w=>w.basis!=='voice_hint')||['queued','validating','rendering','auditing'].includes(status)||!Number.isFinite(sourceDuration)||sourceDuration<shot.duration)return {enabled:false};
 return {enabled:true,min:0,max:Math.max(0,sourceDuration-shot.duration)};
}
function compactShot(form){
 const doc=form.ownerDocument,grid=form.querySelector('.customer-grid');if(!grid||form.querySelector('.cut-advanced'))return;
 const detail=doc.createElement('details');detail.className='cut-advanced';
 const summary=doc.createElement('summary');summary.textContent='精细调整 · 动效、取景与动作保护';detail.append(summary);
 const advanced=doc.createElement('div');advanced.className='customer-grid';
 for(const label of Array.from(grid.children)){
  const control=label.querySelector('input,select'),name=control?.getAttribute('aria-label')||'';
  if(/动效配方|商品画面 Prompt|图像精修|动效强度|动效偏移|动作避让|保护区间|源视频取景|水平焦点|垂直焦点|运镜|编排|转场/.test(name)||name.startsWith('画面小字')&&!control.value)advanced.append(label);
 }
 if(!advanced.children.length)return;detail.append(advanced);detail.addEventListener('invalid',()=>{detail.open=true;},true);grid.after(detail);
}
function mount(doc,io){
 const $=id=>doc.getElementById(id),el=(tag,text,cls)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let state={},original={shots:[],duration:0,captions:[]},data=original,key='',request=0,selected=null,step=null,time=0,sourceMode=false,previewAsset=null;
 const surface=el('div',undefined,'cut-surface');surface.id='cutSurface';
 const library=el('section',undefined,'cut-library'),stage=el('section',undefined,'cut-stage'),inspector=el('section',undefined,'cut-inspector');
 library.append(el('h3','项目素材'));const items=el('div');library.append(items);
 stage.append(el('h3','画面预览'));const video=el('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.id='cutPreview';
 const image=el('img');image.alt='当前商品素材';image.hidden=true;const screen=el('div',undefined,'cut-screen');screen.append(video,image);stage.append(screen);
 const caption=el('p','','cut-caption'),notice=el('p','','cut-notice');stage.append(caption,notice);
 const mode=el('button','查看源片'),clock=el('output','00:00.00'),toolbar=el('div',undefined,'cut-toolbar');mode.type='button';toolbar.append(mode,clock);stage.append(toolbar);
 inspector.append(el('h3','当前镜头'));inspector.append($('shotList'));surface.append(library,stage,inspector);
 $('step4').insertBefore(surface,$('render'));
 const settings=doc.createElement('details');settings.className='cut-settings';const settingsTitle=el('summary','更多制作设置');settings.append(settingsTitle);
 const optional=['motionRepeatLimit','deliveryMode'];for(const id of optional){const label=$(id)?.closest('label');if(label){const parent=label.parentNode;if(!settings.parentNode)parent.after(settings);settings.append(label);if(parent.tagName==='DETAILS'&&!parent.querySelector('input,select,textarea,button,a'))parent.hidden=true;}}

 const timeline=el('section',undefined,'cut-timeline');timeline.setAttribute('aria-label','剪辑时间轴');
 const head=el('div',undefined,'cut-toolbar');head.append(el('h3','视频 · 声音 · 字幕'));const hint=el('span','拖动播放头定位；修改后先预告再保存');head.append(hint);timeline.append(head);
 const seek=el('input');seek.type='range';seek.min='0';seek.max='0';seek.step=String(1/30);seek.setAttribute('aria-label','时间轴播放头');timeline.append(seek);
 const tracks=el('div');timeline.append(tracks);surface.after(timeline);
 const trimLabel=el('label','调整源片入点（保持本镜时长）'),trim=el('input'),trimText=el('small');trim.type='range';trim.step=String(1/30);trimLabel.append(trim,trimText);inspector.insertBefore(trimLabel,$('shotList'));
 const more=el('details',undefined,'cut-projects'),summary=el('summary','切换项目 / 新建商品');more.append(summary);$('projectControls').before(more);more.append($('projectControls'));
 const full=el('button','展开全部步骤','cut-all');full.type='button';$('workspaceSteps').append(full);let all=false;
 function chooseStep(value){step=value;doc.body.classList.toggle('cut-editing',value==='step4'&&!all);for(let i=1;i<=4;i++)$('step'+i).hidden=!all&&value!=='step'+i;for(const a of doc.querySelectorAll('.workspace-steps a'))a.setAttribute('aria-current',a.getAttribute('href')==='#'+value?'step':'false');}
 for(const a of doc.querySelectorAll('.workspace-steps a'))a.addEventListener('click',()=>{all=false;full.textContent='展开全部步骤';chooseStep(a.getAttribute('href').slice(1));});
 $('workspaceNext').addEventListener('click',()=>{const id=$('workspaceNext').getAttribute('href').slice(1);if(id.startsWith('step'))chooseStep(id);else more.open=true;});
 full.onclick=()=>{all=!all;full.textContent=all?'回到专注模式':'展开全部步骤';chooseStep(step||'step1');};
 // Secondary reports keep their existing IDs, controls, state and handlers.
 for(const [id,label] of [['combinedAudit','综合审核报告'],['revisionTools','逐镜审核与版本比较'],['versions','历史版本与恢复']]){const node=$(id),details=el('details',undefined,'workspace-help cut-secondary');node.before(details);details.append(el('summary',label),node);}
 function rows(){const children=Array.from($('shotList').children);for(const n of children)n.hidden=!!selected&&n.dataset.shotId!==selected;}
 function choose(id){selected=id;rows();const s=data.shots.find(s=>s.shot_id===id),a=state.project?.job?.assets?.find(a=>a.id===s?.asset_id);const range=trimRange(s,Number(a?.metadata?.duration),state.project?.job?.status);trim.disabled=!range.enabled||!!state.busy;trim.min=String(range.min||0);trim.max=String(range.max||0);trim.value=String(s?.source_in||0);trimText.textContent=range.enabled?'拖动即预览原片；尚未保存，不改变配音或字幕。':'多段或受保护动作请在本镜分段编辑器调整；不会快捷裁断完整动作。';for(const b of tracks.querySelectorAll('[data-shot]'))b.setAttribute('aria-pressed',String(b.dataset.shot===id));}
 function putSource(a,at=0){if(!a)return;const src=`/api/jobs/${encodeURIComponent(state.project.job.id)}/assets/${encodeURIComponent(a.id)}`;const player=a.kind==='image'?image:video;image.hidden=a.kind!=='image';video.hidden=a.kind==='image';if(player.getAttribute('src')!==src){video.pause();player.setAttribute('src',src);if(a.kind==='video')video.onloadedmetadata=()=>{video.currentTime=at;};}else if(a.kind==='video')video.currentTime=at;}
 function position(value,fromPlayer=false){time=clamp(value,0,data.duration);seek.value=String(time);clock.textContent=`${time.toFixed(2)} / ${data.duration.toFixed(2)} 秒`;const f=frameAt(data,time);caption.textContent=f?.caption||'';if(!f){video.pause();video.removeAttribute('src');image.removeAttribute('src');video.hidden=true;image.hidden=true;notice.textContent='先准备分镜，时间轴将使用本项目的真实镜头与音轨。';return;}if(selected!==f.shot_id)choose(f.shot_id);
 const hasFilm=state.project?.job?.artifacts?.some(a=>a.kind==='video');
 if(sourceMode||!hasFilm){video.muted=true;putSource(state.project.job.assets.find(a=>a.id===(previewAsset||f.asset_id)),f.source_time);notice.textContent='源片定位预览 · 不含最终运镜、字卡或混音；生成成片后切回完整预览。';}
 else{image.hidden=true;video.hidden=false;video.muted=false;const src=`/api/jobs/${encodeURIComponent(state.project.job.id)}/artifacts/video`;if(video.getAttribute('src')!==src){video.pause();video.setAttribute('src',src);video.onloadedmetadata=()=>{video.currentTime=time;};}else if(!fromPlayer)video.currentTime=time;notice.textContent=state.dirty?'已有成片 · 当前修改尚未保存/渲染':'本版完整成片 · 生成成功不等于人工审核通过';}
 mode.textContent=sourceMode?'切回成片':'查看源片';
 }
 function draw(){items.replaceChildren();const p=state.project;for(const a of p?.job?.assets||[]){if(a.kind==='audio')continue;const b=el('button',a.name,'cut-asset');b.type='button';b.onclick=()=>{sourceMode=true;previewAsset=a.id;putSource(a,0);caption.textContent='';notice.textContent='素材原片 · 仅浏览，不替换当前镜头。';mode.textContent='切回成片';};items.append(b);}if(!items.children.length)items.append(el('p','上传素材后显示。'));
 tracks.replaceChildren();const track=(title,entries,cls)=>{const row=el('div',undefined,'cut-track'),label=el('span',title),lane=el('div',undefined,'cut-lane');row.append(label,lane);for(const entry of entries){const b=el('button',entry.text,cls);b.type='button';b.style.left=`${100*entry.start/(data.duration||1)}%`;b.style.width=`${100*entry.duration/(data.duration||1)}%`;b.title=entry.text;if(entry.shot_id)b.dataset.shot=entry.shot_id;b.onclick=()=>{previewAsset=null;position(entry.start);};lane.append(b);}if(!entries.length)lane.append(el('small',title==='字幕'?'成片生成后显示真实字幕，不估算填充':'本版未配置'));tracks.append(row);};
 track('画面',data.shots.map((s,i)=>({...s,text:`${i+1} · ${s.headline||'实拍'}`})),'cut-video');
 const voice=data.audio?.narration;track('配音',voice?.asset_id?[{start:0,duration:data.duration,text:'整稿配音 · 听核保留'}]:[],'cut-audio');
 track('音乐',data.audio?.music_id?[{start:0,duration:data.duration,text:'背景音乐'}]:[],'cut-music');
 track('字幕',(data.captions||[]).map(c=>({...c,duration:c.end-c.start})),'cut-subtitle');
 seek.max=String(data.duration||0);seek.disabled=!data.shots.length;choose(data.shots.some(s=>s.shot_id===selected)?selected:data.shots[0]?.shot_id);position(time);
 }
 seek.oninput=()=>{video.pause();previewAsset=null;position(seek.value);};mode.onclick=()=>{sourceMode=!sourceMode;previewAsset=null;position(time);};
 video.addEventListener('timeupdate',()=>{if(!sourceMode&&state.project?.job?.artifacts?.some(a=>a.kind==='video'))position(video.currentTime,true);});
 video.addEventListener('play',()=>{$('film').pause();$('workspacePreview').pause();$('voicePlayer').pause();});
 for(const id of ['film','workspacePreview','voicePlayer'])$(id).addEventListener('play',()=>video.pause());
 trim.oninput=()=>{const s=data.shots.find(s=>s.shot_id===selected);if(!s||trim.disabled)return;sourceMode=true;previewAsset=null;video.pause();putSource(state.project.job.assets.find(a=>a.id===s.asset_id),Number(trim.value));trimText.textContent=`入点 ${Number(trim.value).toFixed(2)} 秒 · 未保存`;notice.textContent='源片入点草稿 · 镜长不变；保存前仍须核对影响范围。';io.edit(s.shot_id,Number(trim.value));};
 async function update(next){const previous=state.project?.id;state=next;data={...original,shots:original.shots.map(s=>({...s,...next.pendingShots?.[s.shot_id]}))};if(previous!==next.project?.id){step=null;time=0;selected=null;sourceMode=false;previewAsset=null;more.open=!next.project;original={shots:[],duration:0,captions:[]};data=original;video.pause();video.onloadedmetadata=null;video.removeAttribute('src');image.removeAttribute('src');draw();}
 if(!step)chooseStep(next.project?.job?.storyboard?'step4':!next.project?.product?.current_review_id?'step1':!next.project?.product?.script_approvals?.some(a=>a.draft_id===next.project.product.current_draft_id)?'step2':'step3');
 const p=next.project;const k=JSON.stringify([p?.id,p?.job?.id,p?.job?.storyboard_revision,p?.job?.artifacts]);if(k===key){rows();trim.disabled=!!next.busy||!trimRange(data.shots.find(s=>s.shot_id===selected),Number(p?.job?.assets?.find(a=>a.id===data.shots.find(s=>s.shot_id===selected)?.asset_id)?.metadata?.duration),p?.job?.status).enabled;return;}
 key=k;const ticket=++request;try{const result=p?await io.load(p.id):{shots:[],duration:0,captions:[]};if(ticket!==request)return;original=result;data={...result,shots:result.shots.map(s=>({...s,...state.pendingShots?.[s.shot_id]}))};draw();}catch(e){if(ticket!==request)return;key='';data={shots:[],duration:0,captions:[]};draw();notice.textContent='时间轴未载入：'+e.message;}
 }
 return {update,refreshShots:rows,compactShot};
}
if(typeof module!=='undefined'&&module.exports)module.exports={frameAt,trimRange,mount,compactShot};
if(typeof document!=='undefined'){
 window.CustomerEditor=mount(document,{load:pid=>api('/customer-projects/'+pid+'/timeline'),edit:(id,value)=>{shotEdits.set(id,{...(shotEdits.get(id)||{}),source_in:value});paintShots();paintWorkspace();}});
 if(typeof paintWorkspace==='function')paintWorkspace();
}
})();
