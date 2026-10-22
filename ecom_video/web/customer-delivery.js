/* Versioned decisions inside the existing workbench. Never auto-confirm reviews. */
function readCuts(rows) {
  return rows.map(r => {
    const cut={asset_id:r.asset_id,source_in:Number(r.source_in),source_duration:Number(r.source_duration),duration:Number(r.duration),reason:r.reason||'',complete_action:null};
    if(!cut.asset_id || ![cut.source_in,cut.source_duration,cut.duration].every(Number.isFinite) || cut.source_in<0 || cut.source_duration<.2 || cut.duration<.2)throw Error('实拍分段请填写素材、有效入点及至少0.2秒时长');
    if(r.action_name) {
      const start=Number(r.action_start),end=Number(r.action_end);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start)throw Error('完整动作起止须为源视频中的有效秒数');
      cut.complete_action={name:r.action_name,start,end};
    }
    return cut;
  });
}
function paintDeliverySettings() {
  $('deliveryMode').checked=!!p.settings.delivery_version;
  $('identitySku').value=p.settings.identity_lock?.sku||'';
  $('identityColor').value=p.settings.identity_lock?.color||'';
}
function deliverySettings() {
  const sku=$('identitySku').value.trim(),color=$('identityColor').value.trim();
  if((sku||color)&&(!$('deliveryMode').checked||!sku||!color))throw Error('限定单色时，请启用交付编排并同时填写款式和配色');
  return {delivery_version:$('deliveryMode').checked?1:null,identity_lock:sku&&color?{sku,color}:null};
}
function identityEditor(card,a) {
  if(a.kind==='audio'||!p.settings.delivery_version)return;
  const box=node('details'), grid=node('div',undefined,'customer-grid');box.append(node('summary','人工核对本素材款式与配色（不是视觉鉴定）'));
  for(const [key,label,value] of [['sku','款式 / SKU',a.metadata.identity?.sku||p.settings.identity_lock?.sku||''],['color','本素材配色',a.metadata.identity?.color||''],['reviewer','核对人','']]) {
    const wrap=node('label',label),input=node('input');input.value=value;input.maxLength=key==='color'?40:80;input.dataset.identity=key;
    input.oninput=()=>mediaEdits.set(a.id,{...(mediaEdits.get(a.id)||{}),identity_dirty:true});wrap.append(input);grid.append(wrap);
  }
  const label=node('label','已实际核对本份素材的款式及配色'),check=node('input');check.type='checkbox';check.dataset.identity='confirmed';label.prepend(check);grid.append(label);box.append(grid);card.append(box);
}
function readIdentity(card) {
  const get=k=>card.querySelector('[data-identity="'+k+'"]');
  if(!get('confirmed')?.checked)return null;
  const value={sku:get('sku').value.trim(),color:get('color').value.trim(),reviewer:get('reviewer').value.trim(),confirmed:true};
  if(!value.sku||!value.color||!value.reviewer)throw Error('请填写本素材款式、配色和实际核对人');
  return value;
}
function cutEditor(form,current,shot,index,mark) {
  if(!p.settings.delivery_version)return;
  const box=node('details');box.append(node('summary','同一句的实拍分段与完整动作'));
  const cuts=current.source_cuts||[], videos=p.job.assets.filter(a=>a.kind==='video');
  let rows=cuts.map(c=>({...c,action_name:c.complete_action?.name||'',action_start:c.complete_action?.start??0,action_end:c.complete_action?.end??0}));
  const list=node('div');
  function save() {const value=rows.length?readCuts(rows):null;mark('source_cuts',value);if(value){mark('asset_id',value[0].asset_id);mark('source_in',value[0].source_in);}}
  function paint() {
    list.replaceChildren();
    rows.forEach((cut,k)=>{
      const grid=node('div',undefined,'customer-grid');grid.append(node('p',`分段 ${k+1}`));
      const source=videos.find(a=>a.id===cut.asset_id);
      if(source){const preview=node('video');preview.controls=true;preview.muted=true;preview.preload='metadata';preview.src=`/api/jobs/${p.job.id}/assets/${source.id}`;preview.onloadedmetadata=()=>{preview.currentTime=Number(cut.source_in);};grid.append(preview);}
      for(const [key,label,type] of [['asset_id','实拍素材','select'],['source_in','源片入点秒','number'],['source_duration','使用源片秒数','number'],['duration','成片显示秒数','number'],['reason','这段解释什么','text'],['action_name','完整动作名称（可留空）','text'],['action_start','完整动作源片开始秒','number'],['action_end','完整动作源片结束秒','number']]) {
        const wrap=node('label',label),input=node(type==='select'?'select':'input');
        if(type==='select')input.replaceChildren(...videos.map(a=>option(a.id,a.name)));else {input.type=type;if(type==='number')input.step='any';input.maxLength=200;}
        input.value=cut[key];input.onchange=()=>{try{cut[key]=input.value;save();input.setCustomValidity('');if(key==='asset_id')paint();}catch(e){input.setCustomValidity(e.message);input.reportValidity();message(e.message,true);}};wrap.append(input);grid.append(wrap);
      }
      const remove=node('button','移除此分段','secondary');remove.type='button';remove.onclick=()=>{rows.splice(k,1);save();paint();};grid.append(remove);list.append(grid);
    });
  }
  const add=node('button','增加同句实拍段','secondary');add.type='button';add.disabled=!videos.length;
  add.onclick=()=>{if(rows.length>=4){message('每句最多4段实拍',true);return;}if(!rows.length)rows.push({asset_id:current.asset_id,source_in:current.source_in,source_duration:shot.duration,duration:shot.duration,reason:'',action_name:'',action_start:0,action_end:0});else rows.push({asset_id:videos[0].id,source_in:0,source_duration:.5,duration:.5,reason:'',action_name:'',action_start:0,action_end:0});save();paint();message('请调整各段，使显示时长总和等于本镜 '+shot.duration.toFixed(2)+' 秒；完整动作必须原速。');};
  box.append(node('p','源片时间与成片时间分开记录。总时长须覆盖本镜；完整动作起止按源视频填写，不能截断或变速。'),list,add);paint();form.append(box);
}
function paintDeliveryReviews() {
  if(!p)return;
  const state=p.delivery_reviews||{},enabled=!!state.enabled;
  for(const stage of ['direction','storyboard']) {
    const box=$('delivery-'+stage);box.hidden=!enabled;
    const binding=state[stage+'_basis']||'',viewBinding=binding+':'+selected;
    if(box.dataset.basis!==viewBinding){box.querySelector('input[type="checkbox"]').checked=false;box.dataset.basis=viewBinding;}
    $('delivery-'+stage+'-state').textContent=state[stage]?`已记录：${state[stage].reviewer}；仅适用于绑定版本。`:stage==='direction'?'选定方向后明确确认；声音试听与最终分镜仍分别核对。':'分镜生成不等于已确认；请播放选段并核对字幕、动作和风格，再确认本版。';
    $('delivery-'+stage+'-confirm').disabled=busy||dirty()||!binding||!selected||(stage==='storyboard'&&p.job?.status!=='draft');
  }
}
async function confirmDelivery(stage) {
  const box=$('delivery-'+stage),reviewer=box.querySelector('input[type="text"]').value.trim();
  if(dirty()||!box.querySelector('input[type="checkbox"]').checked||!reviewer)throw Error('请保存修改、实际核对本版，并填写确认人及勾选确认');
  adopt(await post(base()+'/style-reviews',{revision:p.revision,stage,style_id:selected,basis:p.delivery_reviews[stage+'_basis'],reviewer,confirmed:true}));
  message(stage==='direction'?'创意方向已记录；听核后可准备分镜。':'最终分镜风格已记录；生成后仍须人工审核成片。');
}
if(typeof module==='object'&&module.exports)module.exports={readCuts};
