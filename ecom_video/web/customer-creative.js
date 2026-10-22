/* Joint proposals are candidates, never approvals. Existing page layout is retained. */
function paintCreativeBundle(result) {
 const pid=p.id,box=$('scriptAlternatives');
 box.replaceChildren(node('p',result.method));
 const request=c=>({revision:result.customer_revision,product_revision:result.revision,basis:result.basis,candidate_id:c.id});
 const guard=()=>{
  if(dirty()||active()||p.id!==pid||scriptAlternatives!==result||p.revision!==result.customer_revision||p.product.revision!==result.revision)throw Error('商品、素材或稿件已变化，请保存后重新比较联合方案');
 };
 for(const c of result.candidates){
  const panel=node('details');panel.append(node('summary',c.name+' · '+c.payload.length+'句 · 待人工确认'));
  panel.append(node('p','叙事：'+c.narrative),node('p',`声音：${c.voice.name} · 建议语速 ${c.voice.speech_rate}；采用后在配音面板试听，可换音色。`),node('p',c.copy_policy||''));
  const list=node('ol');
  c.payload.forEach((s,i)=>{
   const v=c.visual_plan[i],li=node('li',s.text);
   li.append(node('small',`画面：${v.card?.name||'连续实拍 / 留看'}；${v.reason}；${v.fallback}`));
   for(const missing of v.missing||[])li.append(node('small',missing,'customer-warning'));
   const material=c.shot_strategies?.[i]?.material;
   if(material){
    li.append(node('small','素材检查：'+material.message,'customer-warning'));
    for(const a of material.candidates||[])li.append(node('small',`待回看候选：${a.name} · ${a.source_in}–${a.source_end}秒；${a.observation||'内容仍须核对'}`));
   }
   for(const id of s.fact_ids){const fact=c.source_facts.find(f=>f.id===id);li.append(node('small','完整依据：'+(fact?.text||id)));}
   const source=v.card?.source;if(source?.url){const link=node('a','镜头卡来源');link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';li.append(link);}
   list.append(li);
  });panel.append(list);
  if(c.material_fit)panel.append(node('p',`现有素材：缺口 ${c.material_fit.gap_count}句，未知 ${c.material_fit.unknown_count}句。未知不算通过，动态预览也不证明选段正确。`));
  for(const m of c.material_fit?.missing||[])panel.append(node('small',`第${m.line}句：${m.message}`,'customer-warning'));
  panel.append(node('p',`暂估 ${c.estimated_seconds||'?'}秒；配音后按实测镜长重检。`));
  const media=node('div'),preview=node('button','生成6秒无声动态预览','secondary');preview.type='button';
  preview.onclick=()=>run(async()=>{
   guard();message('正在生成开头及一处说明的动态示意；不会合成配音或记录任何人工确认。');
   const out=await post('/customer-projects/'+pid+'/creative-proposals/preview',request(c));
   if(p.id!==pid||scriptAlternatives!==result)return;
   const video=node('video');video.controls=true;video.muted=true;video.playsInline=true;video.preload='metadata';video.src=out.url;
   media.replaceChildren(video,node('small',out.note));message('无声预览已就绪；镜头内容、配音节奏仍需后续选段与听核。');
  });
  const use=node('button','采用这套方案，创建待确认稿');use.type='button';
  use.onclick=()=>run(async()=>{
   guard();const next=await post('/customer-projects/'+pid+'/creative-proposals/adopt',request(c));
   scriptAlternatives=null;box.replaceChildren();adopt(next);
   message('方案已保存为待确认稿。请核对事实与文稿，再确认方向、试听配音并听核；旧版保留。');
  });
  panel.append(preview,media,use);box.append(panel);
 }
}

function paintCreativePlan() {
 const target=$('creativePlanState');if(!target||!p)return;
 const plan=p.creative_plan;
 target.textContent=plan?`当前稿来源：${plan.name}；建议 ${plan.direction.name} / ${plan.voice.name}。方案与本稿绑定，生成分镜及听审仍须另行确认。`:'当前稿没有绑定联合方案；可比较三套方案，或继续使用已有人工稿。';
}
