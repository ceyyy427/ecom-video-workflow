'use strict';
function paintShotVoice(row,shot,index) {
  if(p.settings.brief.format==='showcase') return;
  const panel=node('section',undefined,'shot-voice');panel.append(node('h4','只重做这一句配音'),node('p',p.job.script.split('\n')[index]));
  const label=node('label','这句的音色'),speaker=node('select');speaker.setAttribute('aria-label',`第${index+1}句配音音色`);
  const choices=volcVoiceStatus?.speakers || {'zh_female_vv_uranus_bigtts':'Vivi · 合成女声','zh_female_gaolengyujie_uranus_bigtts':'高冷御姐 · 合成女声'};
  for(const [id,name] of Object.entries(choices)) speaker.append(option(id,name));
  speaker.value=volcVoiceStatus?.profiles?.[p.job.storyboard.creative.style_id]?.speaker || 'zh_female_vv_uranus_bigtts';
  label.append(speaker);panel.append(label);
  const consentLabel=node('label',undefined,'check'),consent=node('input');consent.type='checkbox';
  consentLabel.append(consent,document.createTextNode('同意仅发送这一句已确认文稿到火山引擎重新合成，按我的账户计费；不会替换当前版本。'));
  panel.append(consentLabel);
  const generate=node('button','重新合成这一句并对比试听','secondary');generate.type='button';generate.disabled=true;
  const usable=()=>!active()&&!dirty()&&!p.inputs_changed&&p.alignment?.status==='confirmed';
  consent.onchange=()=>{generate.disabled=!consent.checked||!usable()||!volcVoiceStatus?.configured;};
  speaker.onchange=()=>{consent.checked=false;generate.disabled=true;};
  generate.onclick=()=>run(async()=>{
    if(!consent.checked||!usable())throw Error('请先保存修改、完成本版听核并勾选单句云发送说明。');
    const data={...voiceRevision(),...version(),speaker:speaker.value,external_consent:true};
    consent.checked=false;message(`正在合成第${index+1}句并在本机对齐，原版保留。不会自动重发云请求。`);
    adopt(await post(base()+'/voice/shots/'+shot.shot_id+'/takes',data));
    message('新句已保存，尚未替换。请对比旧新声音，满意后填写确认人并采用，再听核新版。');
  });panel.append(generate);
  if(!usable()) panel.append(node('small','先完成当前版本听核并保存编辑；制作中或项目输入已变更时不能单句换声。'));
  for(const take of (p.voice_patches||[]).filter(t=>(t.job_id===p.job.id||t.result_job_id===p.job.id)&&t.shot_id===shot.shot_id)){
    const history=node('article',undefined,'voice-take');
    history.append(node('p',`${take.result_job_id?'已采用':'待选择'} · 新镜长 ${take.duration.toFixed(2)} 秒 · ${choices[take.params.speaker]||take.params.speaker}`));
    for(const [kind,name] of [['old','旧句（安全语音区间）'],['new','新句（含自然停顿）']]){
      const wrap=node('label',name),audio=node('audio');audio.controls=true;audio.preload='none';audio.src=`/api/customer-projects/${p.id}/voice/shots/takes/${take.id}/${kind}`;wrap.append(audio);history.append(wrap);
    }
    if(take.alignment.recovery)history.append(node('p',take.alignment.recovery.warning,'customer-warning'));
    if(take.alignment.diagnostic)history.append(node('p','新句识别仍需核对：'+(take.alignment.diagnostic.transcript||'未识别到人声')+'。可以对比试听，暂不能采用。','customer-warning'));
    if(!take.result_job_id){
      const reviewerLabel=node('label','采用确认人'),reviewer=node('input');reviewer.maxLength=120;reviewerLabel.append(reviewer);
      const checkedLabel=node('label',undefined,'check'),checked=node('input');checked.type='checkbox';checkedLabel.append(checked,document.createTextNode('已对比试听，采用此句创建新版；之后仍需确认本版听核和成片审核。'));
      const use=node('button','采用此句，创建待听核新版','secondary');use.type='button';use.disabled=!usable()||!!take.alignment.diagnostic;
      use.onclick=()=>run(async()=>{
        if(!checked.checked||!reviewer.value.trim()||!usable())throw Error('请填写确认人、勾选采用说明并保存当前编辑。');
        adopt(await post(base()+'/voice/shots/takes/'+take.id+'/use',{...voiceRevision(),...version(),reviewer:reviewer.value.trim(),confirmed:true}));
        message('单句已替换到新版；其他镜头和原版保留。请听核本版字幕与声音，确认后再生成成片。');
        $('alignmentPanel').scrollIntoView({behavior:'smooth'});
      });history.append(reviewerLabel,checkedLabel,use);
    }
    panel.append(history);
  }
  panel.append(node('small','新声音会改变本镜时长及后续字幕绝对位置；其他镜头保持各自原音、时长和画面选择。目标实拍动作仍需你试听核对。'));
  row.append(panel);
}
