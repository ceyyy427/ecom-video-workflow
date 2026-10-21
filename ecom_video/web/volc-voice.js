'use strict';
let volcVoiceStatus = null, volcVoiceBasis = '', volcVoiceSelection = '';
function voiceSelectionKey() { return p ? [p.id, p.direction_basis, selected].join(':') : ''; }
function takeUrl(id) { return `/api/customer-projects/${p.id}/voice/takes/${id}`; }
function setVoiceAudio(player, url) {
  if (!url) { player.hidden = true; player.pause(); player.removeAttribute('src'); return; }
  player.hidden = false;
  if (player.getAttribute('src') !== url) { player.pause(); player.src = url; }
}
function paintVolcVoice() {
  const state = $('volcVoiceState'), button = $('volcVoiceGenerate'), select = $('volcVoiceSpeaker');
  if (!state || !button || !select) return;
  if (!select.options.length && volcVoiceStatus) {
    Object.entries(volcVoiceStatus.speakers).forEach(([id, label]) => select.append(option(id, label)));
  }
  const profile = volcVoiceStatus?.profiles?.[selected], selection = voiceSelectionKey();
  if (selection !== volcVoiceSelection && profile) {
    let saved = ''; try { saved = localStorage.getItem('ecom.voice.' + selection) || ''; } catch (_) {}
    select.value = Object.hasOwn(volcVoiceStatus.speakers, saved) ? saved : profile.speaker;
    volcVoiceSelection = selection;
  }
  const basis = [selection, p?.product.current_draft_id, select.value].join(':');
  if (basis !== volcVoiceBasis) { $('volcVoiceConsent').checked = false; volcVoiceBasis = basis; }
  const existing = p?.media.find(a => a.role === 'voice'), approved = p?.product.status === 'script_confirmed';
  $('volcVoiceProfile').textContent = profile ? `${profile.name} · 语速 ${profile.speech_rate > 0 ? '+' : ''}${profile.speech_rate}（相对默认）｜${profile.direction}` : '先选视频风格，再自动匹配语气、语速和默认音色。';
  state.textContent = !volcVoiceStatus ? '正在读取本机配置…' : !volcVoiceStatus.configured ? volcVoiceStatus.message : !approved ? '先核对并确认文稿。' : !profile ? '请选择上方一个视频方向。' : '本机密钥已配置。试听与整稿合成均由你点击后发起，音色权限以实际请求为准。';
  const blocked = !p || !approved || active() || dirty();
  const cloudBlocked = busy || blocked || !profile || !volcVoiceStatus?.configured || !$('volcVoiceConsent').checked;
  $('volcVoicePreview').disabled = cloudBlocked;
  button.disabled = cloudBlocked;
  button.textContent = existing ? '换声并保留旧声音' : '合成整稿配音';
  const takes = p?.voice_takes || [], matching = takes.find(t => t.scope === 'preview' && t.draft_id === p.product.current_draft_id && t.params.style_id === selected && t.params.speaker === select.value && t.params.profile_version === volcVoiceStatus?.profile_version);
  setVoiceAudio($('volcVoicePreviewPlayer'), matching ? takeUrl(matching.id) : '');
  $('volcVoicePreviewText').textContent = matching ? '首句试听（不会用于成片）：' + matching.params.preview_text : '先试听已确认文稿的第一句，满意后再合成整稿。相同参数的试听会复用本机缓存。';
  const history = $('volcVoiceHistory');
  // Keep players mounted while polling, so a playing history item is not interrupted.
  const stamp = JSON.stringify([p?.id, takes.map(t=>t.id), existing?.id, blocked, busy]);
  if (history.dataset.stamp !== stamp) {
    history.dataset.stamp = stamp; history.replaceChildren();
    for (const t of takes) {
      const row = node('article', undefined, 'voice-take');
      const params = t.params, name = volcVoiceStatus?.speakers?.[params.speaker] || '上传声音';
      const activeTake = existing && (existing.metadata.voice_source?.take_id || existing.id) === t.id;
      row.append(node('p', `${t.scope === 'preview' ? '首句试听' : params.provider === 'assembled' ? '完整声音（包含单句换声）' : '完整声音'} · ${name}${params.provider === 'assembled' ? '（换声句）' : ''} · ${volcVoiceStatus?.profiles?.[params.style_id]?.name || '原声音'} · ${Number(t.duration).toFixed(1)}秒${activeTake ? ' · 当前采用' : ''}`));
      const audio = node('audio'); audio.controls = true; audio.preload = 'none'; audio.src = takeUrl(t.id); row.append(audio);
      if (t.scope === 'full') {
        const use = node('button', activeTake ? '当前声音' : '采用此完整声音', 'secondary'); use.type = 'button';
        use.disabled = busy || blocked || !!activeTake;
        use.onclick = () => run(async () => {
          const result = await post(base() + '/voice/takes/' + t.id + '/use', voiceRevision());
          adopt(result); await prepareVoice('历史声音已恢复，没有新的云请求。');
        }); row.append(use);
      }
      history.append(row);
    }
  }
}
function voiceRevision() { return { revision:p.revision, product_revision:p.product.revision, draft_id:p.product.current_draft_id }; }
async function prepareVoice(prefix) {
  if (p.preparation_blockers.length) { message(prefix + ' 请先完成：' + p.preparation_blockers.join('；')); return; }
  try { await prepareFlow(); message(prefix + ' 已准备新制作版本并请求本机对齐；完成后须重新逐句听核。'); }
  catch (e) { message(prefix + ' 声音已保存，本机准备尚未完成：' + e.message, true); }
}
async function loadVolcVoiceStatus() {
  try { volcVoiceStatus = await api('/voice/volcengine/status'); }
  catch (_) { volcVoiceStatus = { configured:false, speakers:{}, message:'配音配置状态读取失败，请刷新重试。' }; }
  // A refreshed server profile must also refresh the visible history labels.
  $('volcVoiceHistory').dataset.stamp = '';
  paintVolcVoice();
}
document.addEventListener('DOMContentLoaded', () => {
  if (!$('volcVoiceGenerate')) return;
  $('volcVoiceConsent').addEventListener('change', paintVolcVoice);
  $('volcVoiceSpeaker').addEventListener('change', () => {
    try { localStorage.setItem('ecom.voice.' + voiceSelectionKey(), $('volcVoiceSpeaker').value); } catch (_) {}
    paintVolcVoice();
  });
  $('volcVoiceRefresh').addEventListener('click', () => run(loadVolcVoiceStatus));
  for (const [id, preview] of [['volcVoicePreview',true], ['volcVoiceGenerate',false]]) {
    $(id).addEventListener('click', () => run(async () => {
      if (!p || dirty() || active() || !selected || !$('volcVoiceConsent').checked) throw Error('请保存修改、选定风格并勾选云端合成说明。');
      const projectId = p.id, existing = p.media.find(a=>a.role==='voice');
      const data = {...voiceRevision(), speaker:$('volcVoiceSpeaker').value, style_id:selected, direction_basis:p.direction_basis, external_consent:true};
      if (!preview && existing) data.replace_voice_id = existing.id;
      message(preview ? '正在准备首句试听；相同参数优先复用本机缓存。' : '正在合成完整配音，旧声音会保留；请求不会自动重试。');
      $('volcVoiceConsent').checked = false;
      const result = await post(`/customer-projects/${projectId}/voice/${preview ? 'preview' : 'volcengine'}`, data);
      if (p?.id !== projectId) return;
      adopt(result);
      if (preview) message('首句试听已保存。请点播放器试听；满意后勾选说明，合成整稿。');
      else await prepareVoice('完整配音已保存，旧声音仍可从历史记录恢复。');
    }));
  }
  document.addEventListener('play', event => {
    if (!(event.target instanceof HTMLMediaElement)) return;
    document.querySelectorAll('audio,video').forEach(player=>{ if(player!==event.target) player.pause(); });
  }, true);
});
