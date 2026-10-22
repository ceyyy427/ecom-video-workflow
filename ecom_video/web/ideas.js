'use strict';
const el=id=>document.getElementById(id);
function item(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function json(url,options){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败，请检查输入后重试');return d;}
async function startIdeas(){
 const styles=await json('/api/film-styles');for(const s of styles){const n=item('option',s.name+' · '+s.category);n.value=s.id;el('ideaPreferred').append(n);}
 el('ideaForm').addEventListener('submit',async event=>{
  event.preventDefault();el('ideaSubmit').disabled=true;el('ideaState').textContent='正在本机匹配，不会合成声音或生成成片。';
  try{
   const session=await json('/api/session');
   const data={idea:el('ideaText').value,audience:el('ideaAudience').value,tone:el('ideaTone').value,mode:el('ideaMode').value,preferred:el('ideaPreferred').value||null};
   const bundle=await json('/api/film-styles/recommend',{method:'POST',headers:{'Content-Type':'application/json','X-Workflow-Token':session.token},body:JSON.stringify(data)});
   el('ideaResults').replaceChildren();
   for(const s of bundle.options){
    const panel=item('article','');panel.className='card';panel.append(item('h2',s.name),item('p',s.reason),item('p',s.preview_note));
    const details=item('details',''),summary=item('summary','查看按本主题适配的完整 Prompt'),copy=item('pre',s.adapted_prompt);details.append(summary,copy);panel.append(details);
    const link=item('a','LemoLab · 固定版本来源');link.href=s.source.url;link.target='_blank';link.rel='noopener noreferrer';panel.append(link);
    const save=item('button','下载这套待确认创作方案');save.type='button';save.onclick=()=>{
     const file={...bundle,options:[s],status:'pending_human_review',selected_style:s.id};
     const u=URL.createObjectURL(new Blob([JSON.stringify(file,null,2)],{type:'application/json'}));
     const a=document.createElement('a');a.href=u;a.download='jianxu-idea-'+s.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
    };panel.append(save);el('ideaResults').append(panel);
   }
   el('ideaState').textContent=bundle.method+' 已给出六个方向；下载选择不会记录人工审批或自动渲染。';
  }catch(e){el('ideaState').textContent=e.message;}finally{el('ideaSubmit').disabled=false;}
 });
}
startIdeas().catch(e=>{el('ideaState').textContent=e.message;});
