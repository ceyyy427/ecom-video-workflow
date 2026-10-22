'use strict';
let localVoiceStatus=null,localVoiceProject='';
function paintLocalVoice(){
 const provider=$('voiceProvider');if(!provider)return;
 const local=provider.value==='voicestudio';
 $('cloudVoicePanel').hidden=local;$('localVoicePanel').hidden=!local;
 const basis=p?[p.id,p.product.current_draft_id,$('localVoiceEngine').value,$('localVoiceSpeed').value].join(':'):'';
 if(basis!==localVoiceProject){$('localVoiceReady').checked=false;localVoiceProject=basis;}
 $('localVoiceState').textContent=localVoiceStatus?.message||'点“检查本机服务”读取配置；未发起声音合成。';
 const blocked=!local||!p||dirty()||active()||busy||p.product.status!=='script_confirmed'||!localVoiceStatus?.ready||!$('localVoiceReady').checked;
 $('localVoicePreview').disabled=blocked;$('localVoiceGenerate').disabled=blocked;
 const take=p?.voice_takes?.find(t=>t.scope==='preview'&&t.draft_id===p.product.current_draft_id&&t.params.provider==='voicestudio'&&t.params.engine===$('localVoiceEngine').value&&t.params.speed===Number($('localVoiceSpeed').value));
 setVoiceAudio($('localVoicePlayer'),take?takeUrl(take.id):'');
}
async function loadLocalVoice(){localVoiceStatus=await api('/voice/voicestudio/status');paintLocalVoice();}
document.addEventListener('DOMContentLoaded',()=>{
 if(!$('voiceProvider'))return;
 $('voiceProvider').addEventListener('change',()=>run(async()=>{paintLocalVoice();if($('voiceProvider').value==='voicestudio')await loadLocalVoice();}));
 ['localVoiceReady','localVoiceEngine','localVoiceSpeed'].forEach(id=>$(id).addEventListener('change',paintLocalVoice));
 $('localVoiceRefresh').addEventListener('click',()=>run(loadLocalVoice));
 for(const [id,preview] of [['localVoicePreview',true],['localVoiceGenerate',false]])$(id).addEventListener('click',()=>run(async()=>{
  if(!p||dirty()||active()||!$('localVoiceReady').checked)throw Error('请保存修改、确认文稿，并核对本机模型。');
  const pid=p.id,existing=p.media.find(a=>a.role==='voice');
  const data={...voiceRevision(),engine:$('localVoiceEngine').value,speed:Number($('localVoiceSpeed').value),preview,local_engine_confirmed:true};
  if(!preview&&existing)data.replace_voice_id=existing.id;
  message('正在请求本机 VoiceStudio，首次加载模型可能较慢。结果仍需实际听核；不会转用云配音。');
  $('localVoiceReady').checked=false;
  const result=await post(`/customer-projects/${pid}/voice/voicestudio`,data);
  if(p?.id!==pid)return;adopt(result);paintLocalVoice();
  if(preview)message('本机首句试听已保存，请实际听取后再合成整稿。');
  else await prepareVoice('本机完整配音已保存，旧声音仍保留。');
 }));
 paintLocalVoice();
});
