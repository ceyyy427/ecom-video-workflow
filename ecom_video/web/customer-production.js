/* Pure presentation helpers; no network, mutation or automatic approvals. */
(function(root){
 'use strict';
 const mib=n=>(Number(n||0)/1048576).toFixed(1)+' MiB';
 function intakeLines(report){
  if(!report)return [];
  const lines=[`${report.videos} 份实拍视频 · ${report.images} 份图片 · 内容未知 ${report.unknown_visuals} 份`,...(report.warnings||[])];
  for(const a of report.assets||[]){const i=a.intake;if(i)lines.push(`${a.name}：${i.transcoded?'已生成工作副本':'无需转码'}；原件 ${mib(i.original_bytes)} → 工作文件 ${mib(i.working_bytes)}；原始旋转 ${i.original_rotation}°。原件保留。`);}
  return lines;
 }
 function proposalLines(c){
  const d=c.direction||{},n=c.production_notes||{},f=c.material_fit||{},v=d.voice;
  return [d.name?'建议方向：'+d.name:'',v?`配音：${v.name} · 语速 ${v.speech_rate}`:'',n.structure||'',n.rhythm||'',
   `预计 ${c.estimated_seconds||'?'} 秒；${c.timing_basis||'配音后重检'}`,
   `现有素材：缺口 ${f.gap_count||0} 句 · 未知 ${f.unknown_count||0} 句；候选仍须逐镜回看`,...(c.inventory?.warnings||[])].filter(Boolean);
 }
 function editImpact(changes){
  if(['text','script','duration','speech_rate','speaker','voice'].some(k=>Object.hasOwn(changes||{},k)))return '文稿、配音或时长变化需要重新确认和听核，再重新对齐字幕及节奏；后续镜头起点也可能变化，旧版保留。';
  return '只修改本镜画面或字卡，其他镜头参数和配音保持；复用以实际缓存记录为准。旧版保留，新版仍待人工审片。相邻转场改变时将暂停并提示。';
 }
 function handoffLines(s){
  if(!s?.export_available)return ['先生成成片，再准备当前版本的审核/交付包。'];
  return [s.approved_for_handoff?'当前版本已记录各项人工确认，可准备交付包。':'当前版本仅可导出待审包，不能当作客户签收。',...(s.blockers||[]),'包含成片、可用字幕/配音、文稿、分镜与来源/审核记录；原片和可编辑项目请另外备份。'];
 }
 const api={intakeLines,proposalLines,editImpact,handoffLines};
 if(typeof module==='object'&&module.exports)module.exports=api;
 else root.CustomerProduction=api;
})(typeof window!=='undefined'?window:globalThis);
