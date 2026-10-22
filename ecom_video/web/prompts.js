'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
const option=(value,text)=>{const e=node('option',text);e.value=value;return e;};
const link=(text,url)=>{const a=node('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;};
const params=new URLSearchParams(location.search);
let selectedCard=null,adaptTicket=0,searchTicket=0;
async function read(url){const r=await fetch(url);if(!r.ok)throw Error(r.status===409?'分镜已变化，请从工作台重新打开。':'内容未就绪，请重新选择或检查安装包。');return r.json();}
function status(error){$('libraryStats').textContent=error.message;}
async function adapt(){
 const ticket=++adaptTicket,id=selectedCard,pid=$('libraryProject').value,shot=$('libraryShot').value;
 $('backToProject').href=pid?'/create?project='+encodeURIComponent(pid):'/create';
 const host=$('libraryAdaptation');if(!host)return;
 host.replaceChildren();
 if(!pid){host.append(node('p','选择你的商品，查看这张卡如何适配。'));return;}
 const d=await read('/api/customer-projects/'+encodeURIComponent(pid)+'/prompt-adaptation?'+new URLSearchParams({card_id:id,...(shot?{shot_id:shot}:{})}));
 if(ticket!==adaptTicket||selectedCard!==id||$('libraryProject').value!==pid)return;
 $('libraryShot').replaceChildren(...d.shots.map(s=>option(s.id,s.text)));if(d.shot_id)$('libraryShot').value=d.shot_id;
 host.append(node('h3','用于 '+d.title),node('pre',d.adapted_prompt));
 const controls=node('div');controls.className='prompt-apply';
 if(d.choices.length){const label=node('label','选择本机变体'),select=node('select');select.setAttribute('aria-label','选择本机变体');for(const c of d.choices)select.append(option(c.id,c.name));label.append(select);controls.append(label);
  const explain=node('p'),apply=node('a','带入这一镜 · 返回核对');apply.removeAttribute('target');
  const update=()=>{const c=d.choices.find(x=>x.id===select.value);explain.textContent=c.prompt;if(d.ready)apply.href='/create?'+new URLSearchParams({project:pid,job:d.job_id,revision:String(d.revision),board:String(d.board_revision),shot:d.shot_id,prompt:c.id,card:id});};select.onchange=update;update();controls.append(explain);if(d.ready)controls.append(apply);
 }
 for(const reason of d.blockers)controls.append(node('p',reason));controls.append(node('small','先带入草稿，再查看修改影响和保存。不会自动确认或渲染。'));host.append(controls);
}
async function showCard(id){
 ++adaptTicket;selectedCard=id;const c=await read('/api/prompt-library/'+encodeURIComponent(id));if(selectedCard!==id)return;
 for(const el of $('libraryResults').children)el.setAttribute('aria-current',String(el.dataset.id===id));
 const box=$('libraryDetail');box.replaceChildren(node('h2',c.summary),node('p',c.use));
 const host=node('section');host.id='libraryAdaptation';box.append(host);
 const source=node('details');source.append(node('summary','查看完整 Prompt 与来源'),node('p',c.adaptation_note),node('p',`许可 ${c.license} · 版本 ${c.commit.slice(0,12)} · ${c.id}`),link('固定版本原文',c.source_url),node('pre',c.body));
 for(const x of c.implementation_sources)source.append(node('p'),link(x.path,x.url));
 box.append(source);const samples=node('details');samples.append(node('summary',c.styles.length+' 个上游变体和样例'));for(const s of c.styles){const row=node('p',s.label+'：'+(s.description||''));row.append(link('查看样例',s.sample_url));samples.append(row);}box.append(samples);await adapt();
}
async function search(){
 const ticket=++searchTicket;
 const d=await read('/api/prompt-library?'+new URLSearchParams({q:$('libraryQuery').value,category:$('libraryCategory').value,status:$('libraryStatus').value,limit:'124'}));if(ticket!==searchTicket)return;
 $('libraryStats').textContent=`本机 ${d.stats.cards} 张卡 · ${d.stats.styles} 种变体 · 本次 ${d.total} 项`;
 if($('libraryCategory').options.length===1)for(const [id,label]of Object.entries(d.categories))$('libraryCategory').append(option(id,label.zh));
 const root=$('libraryResults');root.replaceChildren();for(const c of d.items){const card=node('article');card.className='prompt-card';card.dataset.id=c.id;card.setAttribute('aria-current',String(c.id===selectedCard));card.append(node('h2',c.summary),node('p',c.status==='adapted'?'已有本机适配':'参考待适配'));const b=node('button','查看与选择');b.type='button';b.onclick=()=>showCard(c.id).catch(status);card.append(b);root.append(card);}
}
$('librarySearch').onsubmit=e=>{e.preventDefault();search().catch(status);};
$('libraryProject').onchange=()=>{$('libraryShot').replaceChildren();adapt().catch(status);};
$('libraryShot').onchange=()=>adapt().catch(status);
void(async()=>{try{
 const projects=await read('/api/customer-projects');for(const p of projects)$('libraryProject').append(option(p.id,p.title));
 if(projects.some(p=>p.id===params.get('project')))$('libraryProject').value=params.get('project');
 if(params.get('shot')){$('libraryShot').append(option(params.get('shot'),'当前这一镜'));$('libraryShot').value=params.get('shot');}
 await search();if(params.get('card'))await showCard(params.get('card'));
}catch(e){status(e);}})();
