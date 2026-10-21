"use strict";
(() => {
  let board=null, revision=0, loadedKey="", loadedJob="", changed=false, persisted=false, generation=0, caps={};
  const panel=$("storyboardPanel"), form=$("storyboardFields");
  const key=()=>job ? `${job.id}:${job.storyboard_revision}:${job.assets.map(a=>a.id).join(',')}` : '';
  const canEdit=()=>job?.status==='draft' && !!board && loadedKey===key() && !busy && !dirty;
  const option=(value,text)=>{const o=node('option',text);o.value=value;return o;};
  function field(parent,label,value,type,change,choices){
    const wrap=node('label',label), input=node(choices?'select':'input');
    input.setAttribute('aria-label',label);
    if(choices) choices.forEach(([v,t])=>input.append(option(v,t)));
    else {input.type=type||'number'; if(input.type==='number')input.step='0.0333333333';}
    input.value=value??'';
    input.onchange=()=>{change(choices?input.value:Number(input.value));changed=true;updateHint();};
    wrap.append(input);parent.append(wrap);return input;
  }
  function updateHint(){
    $("storyboardHint").textContent=changed?'分镜有未保存修改':`${persisted ? `分镜版本 ${revision}` : `默认分镜 · 生成时保存（版本 ${revision}）`} · ${board?.shots.reduce((s,x)=>s+x.duration,0).toFixed(2)||0} 秒`;
    $("saveStoryboard").disabled=!canEdit();
    form.disabled=!canEdit();
  }
  function paint(){
    form.replaceChildren();if(!board)return;
    const settings=node('div',undefined,'board-settings');form.append(settings);
    if(board.creative_required&&!board.creative){const link=node('a','镜头已保留，请重新选择创意方向 →');link.href='/studio?job='+job.id;settings.append(link);}
    if(board.creative){const link=node('a','已选 Remotion 风格：'+board.creative.style_id+' · 编辑风格与口播 →');link.href='/studio?job='+job.id;settings.append(link);}else field(settings,'成片风格',board.style,null,v=>{board.style=v;},[['premium','质感展示'],['demo','功能 / 细节演示'],['lifestyle','场景转化']]);
    const modes=[['silent','无旁白'],['uploaded','上传配音']];if(caps.local_tts)modes.push(['local','本机中文配音 · 婷婷']);
    field(settings,'旁白方式',board.narration.mode,null,v=>{
      board.narration.mode=v;if(board.creative)board.creative.alignment_id=null;board.narration.asset_id=v==='uploaded'?(job.assets.find(a=>a.kind==='audio')?.id||null):null;paint();
    },modes);
    const audios=job.assets.filter(a=>a.kind==='audio').map(a=>[a.id,a.name]);
    if(board.narration.mode==='uploaded')field(settings,'配音文件',board.narration.asset_id,null,v=>{board.narration.asset_id=v||null;if(board.creative)board.creative.alignment_id=null;},[['','请选择'],...audios]);
    if(board.narration.mode==='local') {const el=field(settings,'语速（140–280）',board.narration.rate,null,v=>board.narration.rate=v);el.min=140;el.max=280;el.step=1;}
    field(settings,'配音增益 dB',board.narration.gain_db,null,v=>board.narration.gain_db=v);
    field(settings,'背景音乐',board.music_id,null,v=>board.music_id=v||null,[['','不添加'],...audios]);
    field(settings,'音乐响度目标 dB',board.music_db,null,v=>board.music_db=v);
    const sample=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=board.sample;
    check.onchange=()=>{board.sample=check.checked;changed=true;updateHint();};sample.append(check,node('span','显示虚构商品示例标识'));settings.append(sample);
    const lines=job.script.split('\n'), visuals=job.assets.filter(a=>a.kind!=='audio');
    board.shots.forEach((shot,i)=>{
      const card=node('section',undefined,'shot-card'),head=node('div',undefined,'shot-title');
      head.append(node('strong',String(i+1).padStart(2,'0')),node('p',lines[i]));card.append(head);
      const body=node('div',undefined,'shot-body'),preview=node('div',undefined,'shot-preview'),fields=node('div',undefined,'shot-fields');
      const asset=visuals.find(a=>a.id===shot.asset_id);
      if(asset){
        const media=node(asset.kind==='video'?'video':'img');media.src=`/api/jobs/${job.id}/assets/${asset.id}`;
        if(asset.kind==='video'){
          media.controls=true;media.muted=true;media.preload='metadata';
          media.onloadedmetadata=()=>{media.currentTime=shot.source_in;};
          media.ontimeupdate=()=>{if(media.currentTime>=shot.source_in+shot.duration)media.pause();};
          media.onplay=()=>{if(media.currentTime<shot.source_in||media.currentTime>=shot.source_in+shot.duration)media.currentTime=shot.source_in;};
        } else {media.alt=asset.name;media.className='motion-'+shot.motion;}
        preview.append(media);
      }
      body.append(preview,fields);card.append(body);form.append(card);
      field(fields,`分镜 ${i+1} 素材`,shot.asset_id,null,v=>{shot.asset_id=v||null;shot.source_in=0;shot.source_framing='original';shot.motion='static';paint();},[['','请选择素材'],...visuals.map(a=>[a.id,a.name])]);
      const dur=field(fields,`分镜 ${i+1} 时长`,shot.duration,null,v=>{shot.duration=v;paint();});dur.min=1;dur.max=15;
      if(asset?.kind==='video'){
        const start=field(fields,`分镜 ${i+1} 入点`,shot.source_in,null,v=>{shot.source_in=v;paint();});start.min=0;
        field(fields,`分镜 ${i+1} 出点`,shot.source_in+shot.duration,null,v=>{shot.duration=v-shot.source_in;paint();});
        fields.append(node('small',`源素材 ${asset.metadata.duration.toFixed(2)} 秒 · 不循环补足`));
      } else field(fields,`分镜 ${i+1} 运镜`,shot.motion,null,v=>{shot.motion=v;paint();},[['static','静止'],['push','缓慢推近'],['pull','缓慢拉远'],['pan_left','向左横移'],['pan_right','向右横移']]);
      if(asset?.kind==='video') field(fields,`分镜 ${i+1} 源视频取景`,shot.source_framing||'original',null,v=>shot.source_framing=v,[['original','保留原画幅'],['square','方形取景（裁边，成片须核对动作）']]);
      field(fields,`分镜 ${i+1} 画幅`,shot.fit,null,v=>shot.fit=v,[['contain','完整显示'],['cover','填满画幅']]);
      for(const [axis,name] of [['x','水平'],['y','垂直']]){
        const input=field(fields,`分镜 ${i+1} ${name}焦点`,shot['focus_'+axis],null,v=>shot['focus_'+axis]=v);input.min=0;input.max=1;input.step=.05;
      }
    });
    updateHint();
  }
  async function load(){
    panel.hidden=!job;const current=key();if(!job){generation++;loadedKey='';board=null;changed=false;return;}
    if(current===loadedKey){updateHint();return;}
    // An asset refresh must not replace local decisions for the same script revision.
    if(board && loadedJob===job.id && revision===job.storyboard_revision && (changed || job.storyboard)){
      generation++;loadedKey=current;paint();return;
    }
    const n=++generation, id=job.id;
    try {const data=await api(`/jobs/${id}/storyboard`);if(n!==generation||id!==job?.id)return;
      board=data.board;persisted=data.saved;revision=data.revision;caps=data.capabilities;loadedKey=current;loadedJob=id;changed=false;paint();
    }catch(e){notify(e.message,true);}
  }
  async function save(){
    if(!board||dirty||loadedKey!==key())throw new Error('请先保存脚本并等待分镜载入，再编辑分镜');
    const result=await api(`/jobs/${job.id}/storyboard`,{method:'PUT',body:JSON.stringify({board,revision})});
    job=result;persisted=true;board=result.storyboard;revision=result.storyboard_revision;loadedKey=key();loadedJob=job.id;changed=false;render();paint();
  }
  window.storyboardEditor={get dirty(){return changed;},async ensureSaved(){
    await load();
    if(!board || loadedKey!==key())throw new Error('分镜尚未载入，请重试');
    if(changed || !persisted)await save();
  },invalidate(){changed=false;persisted=false;loadedKey="";board=null;generation++;},save};
  $("saveStoryboard").onclick=()=>action(async()=>{await save();notify('分镜已保存；生成将使用此版本。');});
  document.addEventListener('workflow-render',load);
  document.addEventListener('workflow-controls',updateHint);
  window.addEventListener('beforeunload',e=>{if(changed){e.preventDefault();e.returnValue='';}});
})();
