"use strict";
const el = id => document.getElementById(id);
let token, timer, maintaining = false;
async function api(path, body, form = false) {
  if (!token) {
    const r = await fetch('/api/session', {cache:'no-store'});
    if (!r.ok) throw new Error('本机服务未连接，请先启动。');
    token = (await r.json()).token;
  }
  const options = body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'X-Workflow-Token':token},body:form?body:JSON.stringify(body)};
  if (body !== undefined && !form) options.headers['Content-Type'] = 'application/json';
  const r = await fetch('/api/maintenance'+path, options);
  const data = await r.json();
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入格式无效，请检查勾选项、文件与SHA。');
  return data;
}
function text(parent, value, tag = 'p') {
  const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
}
function button(parent, title, action) {
  const node = document.createElement('button'); node.type = 'button'; node.textContent = title;
  node.addEventListener('click', async () => {
    node.disabled = true;
    try {await action();} catch (e) {el('recoveryState').textContent = e.message;}
    finally {node.disabled = false;}
  });
  parent.append(node); return node;
}
async function operation(path, body={confirmed:true}, form=false) {
  const data = await api(path,body,form);
  el('recoveryState').textContent = data.message || '已登记。';
  await refresh();
}
function card(parent) {const node=document.createElement('section');node.className='setup-card';parent.append(node);return node;}
async function refresh() {
  clearTimeout(timer); el('refreshRecovery').disabled = true;
  try {
    const data = await api('/status');
    el('currentVersion').textContent = `当前应用 ${data.application.version || '未知'} · 数据结构 ${data.schema}。数据目录：${data.data_directory}。维护目录：${data.storage_directory}。`;
    const active = data.operations.some(x => x.state === 'running'); maintaining = active;
    el('makeBackup').disabled = active || !el('backupConsent').checked;
    const backups=el('backupList');backups.replaceChildren();
    if (!data.backups.length) text(backups,'尚无已完成备份。');
    data.backups.forEach(item => {
      const node=card(backups);text(node,`${new Date(item.created_at*1000).toLocaleString()} · ${item.backup_id}`,'h3');
      text(node,`${item.files}个已登记文件 · ${(item.bytes/1024**2).toFixed(1)} MiB · 数据结构 ${item.schema}`);
      text(node,'ZIP SHA256：'+item.archive_sha256);
      button(node,'重新校验备份',async () => {const r=await api(`/backups/${item.backup_id}/verify`,{confirmed:true});el('recoveryState').textContent=`校验通过：${r.files}份登记文件，数据库与清单一致。`;});
      const link=document.createElement('a');link.href=`/api/maintenance/backups/${item.backup_id}/download`;link.textContent='下载备份 ZIP';link.className='setup-link';node.append(link);
      button(node,'恢复为新副本',()=>operation(`/backups/${item.backup_id}/restore`)).disabled=active;
    });
    function copies(id,rows,kind,title) {
      const target=el(id);target.replaceChildren();
      rows.forEach(item=>{
        const node=card(target);text(node,title,'h3');text(node,item.directory);
        text(node,`源备份 ${item.backup_id}。原目录保留；当前页面没有切换到这个副本。`);
        if (item.release) text(node,`候选应用 ${item.release.version}，尚未启动/激活。`);
        button(node,'打开副本目录',()=>api(`/open/${kind}/${item.restore_id || item.upgrade_id}`,{confirmed:true}));
      });
    }
    copies('restoreList',data.restores,'restores','恢复副本已准备，待人工启动验收');
    copies('releaseList',data.releases,'releases','新版已准备，待人工启动验收');
    const packages=el('packageList');packages.replaceChildren();
    data.packages.forEach(item=>{
      const node=card(packages);text(node,item.package_id,'h3');text(node,'已核对SHA：'+item.sha256);
      const label=document.createElement('label');label.className='check';
      const check=document.createElement('input');check.type='checkbox';label.append(check,document.createTextNode('我确认此包来源可信，升级前先备份当前数据，只准备独立新版'));node.append(label);
      const run=button(node,'先备份，再准备新版',()=>operation('/upgrades',{confirmed:true,trusted_code:true,package_id:item.package_id}));
      run.disabled=true;check.addEventListener('change',()=>{run.disabled=active || !check.checked;});
    });
    const ops=el('operationList');ops.replaceChildren();
    if (!data.operations.length) text(ops,'尚无维护操作。');
    const states={running:'进行中',complete:'已完成',failed:'失败，未启用',interrupted:'已中断，未启用'};
    data.operations.forEach(item=>{const node=card(ops);text(node,`${item.kind} · ${states[item.state] || item.state}`,'h3');text(node,item.message);if(item.backup_id)text(node,'升级前备份：'+item.backup_id);});
    if (!active && data.operations.length) {const latest=data.operations[0]; el('recoveryState').textContent=`${states[latest.state] || latest.state}：${latest.message}`;}
    if(active){el('recoveryState').textContent='维护正在进行，制作修改暂时锁定；关闭网页不会取消。';timer=setTimeout(refresh,1500);}
  } catch(e) {el('recoveryState').textContent=e.message;}
  finally {el('refreshRecovery').disabled=false;}
}
el('refreshRecovery').addEventListener('click',refresh);
el('backupConsent').addEventListener('change',()=>{el('makeBackup').disabled=maintaining || !el('backupConsent').checked;});
el('makeBackup').addEventListener('click',async()=>{
  el('makeBackup').disabled=true;
  try {await operation('/backups');}catch(e){el('recoveryState').textContent=e.message;el('makeBackup').disabled=maintaining || !el('backupConsent').checked;}
});
el('importForm').addEventListener('submit',async event=>{
  event.preventDefault();const form=new FormData();form.append('confirmed','true');form.append('file',el('backupZip').files[0]);
  try {el('recoveryState').textContent='正在导入本机备份，请保持页面打开直到上传完成…';await operation('/import',form,true);el('backupZip').value='';el('importConsent').checked=false;}catch(e){el('recoveryState').textContent=e.message;}
});
el('packageForm').addEventListener('submit',async event=>{
  event.preventDefault();const form=new FormData();form.append('confirmed','true');form.append('sha256',el('releaseSha').value.trim());form.append('file',el('releaseZip').files[0]);
  try {el('recoveryState').textContent='正在核对安装包SHA并登记；尚未执行代码或升级…';await api('/packages',form,true);await refresh();el('releaseZip').value='';el('codeConsent').checked=false;el('recoveryState').textContent='安装包SHA已核对并登记。完整发行校验在升级前备份完成后执行；请在对应卡片明确确认。';}catch(e){el('recoveryState').textContent=e.message;}
});
window.addEventListener('pagehide',()=>clearTimeout(timer));
refresh();
