'use strict';
function analysisPending() { return !!p?.media.some(a => ['queued','running'].includes(a.analysis?.status)); }
function analysisStamp(project) { return JSON.stringify(project?.media.map(a => [a.id,a.analysis?.id,a.analysis?.status,a.analysis?.stage])); }
async function enqueueMissingAnalysis() {
  if (!p.settings.auto_select) return;
  if ((p.settings.strict_product||p.settings.action_timing||p.settings.material_checks)&&!p.settings.product_reference_id) return;
  for (const a of p.media.filter(a=>a.kind!=='audio'&&(!a.analysis||a.analysis_stale))) await post(base()+'/assets/'+a.id+'/analysis');
  adopt(await api(base()));
}
function paintContentAnalysis(a, card) {
  if (a.kind==='audio') return;
  const area=node('div',undefined,'content-analysis'), state=a.analysis;
  const label=a.analysis_stale?'参照或设置已变化，需重新识别':!state?'尚未识别':({queued:'等待识别',running:'正在识别',ready:'已识别关键帧',partial:'已抽帧，内容识别未就绪',failed:'识别失败',cancelled:'已取消'}[state.status]||state.status);
  area.append(node('strong',label),node('p',state?.error||state?.stage||'开启自动选段后，在本机观察素材内容。'));
  if (a.analysis_stale||!state||['failed','cancelled','partial'].includes(state.status)) {
    const b=node('button',state?'重试识别':'识别此素材','secondary'); b.type='button';
    b.onclick=()=>run(async()=>{await post(base()+'/assets/'+a.id+'/analysis');adopt(await api(base()));message('已加入本机识别队列。可以继续核对资料和文稿。');});area.append(b);
  }
  if (['queued','running'].includes(state?.status)) {
    const b=node('button','取消识别','secondary');b.type='button';b.onclick=()=>run(async()=>{await api(base()+'/assets/'+a.id+'/analysis',{method:'DELETE'});adopt(await api(base()));});area.append(b);
  }
  if (['ready','partial'].includes(state?.status)) {
    const refresh=node('button','复核识别（优先复用，保留旧版）','secondary');refresh.type='button';refresh.onclick=()=>run(async()=>{await post(base()+'/assets/'+a.id+'/analysis',{refresh:true});adopt(await api(base()));message('已排队复核。先核对文件、参照、模型及帧证据，合格原始观察可复用，动作结论仍重算；旧版保留，新分镜需重新准备。');});area.append(refresh);
    const force=node('button','强制重新推理（较慢）','secondary');force.type='button';force.onclick=()=>run(async()=>{await post(base()+'/assets/'+a.id+'/analysis',{refresh:true,force_inference:true});adopt(await api(base()));message('已排队强制重新推理：跳过识别缓存，抽样与检查标准不变；旧版保留。');});area.append(force);
    const perf=state.result.performance;if(perf){const cache=perf.model_cache;area.append(node('p',`本轮 ${perf.elapsed_seconds.toFixed(2)} 秒；${cache.forced_inference?'已强制重新推理；':''}${state.result.reused_observations_from?'已校验并复用原始观察，重新计算动作；':''}精确推理缓存 ${cache.hits} 次命中、${cache.misses} 次未命中。复用不是新的模型判断，仍需看片核对。`,'muted'));const execution=perf.execution;if(execution){const process=execution.process;if(process?.backend==='scoped_ollama')area.append(node('p','本轮使用本机独立加速；结束后自动释放模型进程，逐帧检查标准保持不变。','muted'));else if(process?.fallbacks)area.append(node('p','独立加速暂不可用，本轮使用原本机服务；没有减少检查或改用小模型。','muted'));const releases=(execution.model_releases||0)+(execution.scope_releases||0);if(releases)area.append(node('p',`内存保护已自动回收 ${releases} 次模型运行缓存；素材、识别证据和检查标准保持不变。`,'muted'));if(execution.resource_fallbacks)area.append(node('p','本轮内存不足时已退回原模型放置方式；没有更换小模型或减少检查。','muted'));if(execution.release_errors)area.append(node('p','识别结果已保留，但模型缓存释放未完成。结束当前识别后，可重启本机模型服务再继续。','muted'));}}
    const details=node('details'),summary=node('summary',`查看 ${state.result.segments.length} 个候选片段`);details.append(summary);
    details.append(node('p','这是限量抽帧观察，未覆盖全部动作；识别文字不是商品事实或测试证明。'));
    for (const s of state.result.segments) {
      const clip=node('div',undefined,'content-clip');clip.append(node('strong',a.kind==='video'?`${s.start.toFixed(2)}–${s.end.toFixed(2)} 秒`:'商品图片'));
      const strip=node('div',undefined,'content-frames');s.frames.forEach((_,i)=>{const im=node('img');im.loading='lazy';im.src=`/api/customer-projects/${p.id}/assets/${a.id}/analysis/${state.id}/frames/${s.id}/${i}`;im.alt=`${a.name} · 抽帧 ${i+1}`;strip.append(im);});clip.append(strip);
      clip.append(node('p',s.observation.description),node('small',s.observation.uncertainty||'仍需核对实际画面与商品是否一致。'));
      if(s.motion_check){const m=s.motion_check;if(m.material_checks_version){const measured=m.samples.filter(x=>x.bbox);const small=measured.filter(x=>(x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1])<40000).length;clip.append(node('small',`增强抽样 ${measured.length} 帧，主体偏小 ${small} 帧；完整动作还需前后证据，非逐帧认证`));}clip.append(node('p','参照外观：'+({same:'一致（仍需人工核对）',different:'存在疑似不同款或主体离开画面的帧',uncertain:'存在无法确认的帧'}[m.identity]||m.identity)));for(const r of (m.material_checks_version?m.material_visible_ranges:m.verified_ranges)||[])clip.append(node('small',`${m.material_checks_version?'增强主体候选区间（动作仍需回看）':'外观抽样一致区间（未做增强检查）'} ${r.start.toFixed(2)}–${r.end.toFixed(2)} 秒；其他部分排除`));for(const e of m.events)clip.append(node('small',`${{pour:'可见液流',open_lid:'开盖状态变化',close_lid:'合盖状态变化'}[e.kind]} ${e.start.toFixed(2)}–${e.end.toFixed(2)} 秒（抽样证据）`));}
      if (!s.observation.usable)clip.append(node('p','画面不适合作为自动候选，可人工查看原素材。'));
      if(a.kind==='video'){const b=node('button','播放这一段','secondary');b.type='button';b.onclick=()=>{const player=card.querySelector('video');player.currentTime=s.start;player.ontimeupdate=()=>{if(player.currentTime>=s.end){player.pause();player.ontimeupdate=null;}};player.play().catch(e=>message(e.message,true));};clip.append(b);}
      details.append(clip);
    }
    area.append(details);
  }
  card.append(area);
}
function candidatePicker(row,shot,i,editable,locked) {
  const choices=[];
  const assets=editable?p.job.assets.filter(a=>a.kind!=='audio'):p.media.filter(a=>a.kind!=='audio');
  for (const a of assets) {
    const analysis=editable?a.metadata.content_analysis:(['ready','partial'].includes(a.analysis?.status)?a.analysis.result:null);
    if(!analysis)continue;
    for(const s of analysis.segments)if((s.observation.usable||(analysis.recognition==='unavailable'&&!s.quality.blank))&&(a.kind==='image'||s.end-s.start>=shot.duration-.001))choices.push({a,s});
  }
  if(!choices.length)return;
  const wrap=node('label','按识别内容换一段（仍可调整入点）'),select=node('select');select.setAttribute('aria-label',`第 ${i+1} 镜识别片段`);select.disabled=locked;select.append(option('','选择后填入这一镜，保存才会生效'));
  choices.forEach(({a,s},n)=>select.append(option(String(n),`${a.name} ${a.kind==='video'?s.start.toFixed(1)+'s':''} · ${s.motion_check?({same:'外观一致',different:'疑似不同款',uncertain:'外观不确定'}[s.motion_check.identity]+' · '):''}${s.observation.description}`)));
  select.onchange=()=>{if(select.value==='')return;const {a,s}=choices[Number(select.value)];shotEdits.set(shot.shot_id,{...(shotEdits.get(shot.shot_id)||{}),[editable?'asset_id':'media_id']:a.id,source_in:s.start,motion:a.kind==='video'?'static':'push',fit:'contain',source_framing:'original'});paintShots();message('候选片段已填入这一镜；这是人工选择，请重新核对商品款式、动作与配音后保存。');};wrap.append(select);row.append(wrap);
  const reason=p.planning_notes.find(t=>t.startsWith(`第${i+1}镜：`));if(reason)row.append(node('p','初次自动安排参考（修改后以当前镜头参数为准）：'+reason,'content-reason'));
}
