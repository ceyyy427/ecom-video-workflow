'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
const link=(text,url)=>{const a=node('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;};
async function showCard(id){
 const r=await fetch('/api/prompt-library/'+encodeURIComponent(id));if(!r.ok)throw Error('参考卡不可用，请检查安装包');const c=await r.json(),box=$('libraryDetail');box.hidden=false;box.replaceChildren(node('h2',c.id),node('p',c.adaptation_note),node('p',c.summary),node('p','用途：'+c.use),node('p','时长/能量：'+c.duration+' / '+c.energy),node('p',c.evidence_boundary),node('p','许可 '+c.license+' · 固定版本 '+c.commit.slice(0,12)+' · 正文SHA '+c.body_sha256));
 box.append(link('固定版本原文',c.source_url));const prompt=node('details');prompt.append(node('summary','完整镜头卡：意图、参数、实现与已知问题'),node('pre',c.body));box.append(prompt);
 const code=node('details');code.append(node('summary','对应示例代码（只读来源，不执行）'));for(const x of c.implementation_sources)code.append(node('p'),link(x.path,x.url));box.append(code);
 const samples=node('details');samples.append(node('summary',c.styles.length+' 个风格变体与样例链接'));for(const s of c.styles){const row=node('p',s.label+'：'+(s.description||''));row.append(document.createTextNode(' '),link('打开上游样例',s.sample_url));samples.append(row);}box.append(samples);
 if(c.executable_prompt_ids.length)box.append(node('p','商品制作逐镜可选：'+c.executable_prompt_ids.join('、')));
}
async function search(){
 const params=new URLSearchParams({q:$('libraryQuery').value,category:$('libraryCategory').value,status:$('libraryStatus').value,limit:'124'}),r=await fetch('/api/prompt-library?'+params);if(!r.ok)throw Error('参考库未就绪或校验失败，请核对安装包');const d=await r.json();
 $('libraryStats').textContent=`本机已收录 ${d.stats.cards} 卡 / ${d.stats.styles} 风格变体 / ${d.stats.samples} 样例索引 · 本次 ${d.total} 项 · 固定版本 ${d.commit.slice(0,12)}。${d.coverage}`;
 if($('libraryCategory').options.length===1)for(const [id,label]of Object.entries(d.categories)){const o=node('option',label.zh);o.value=id;$('libraryCategory').append(o);}
 const root=$('libraryResults');root.replaceChildren();if(!d.items.length)root.append(node('p','没有命中；可换成镜头方法词，例如“整体、局部、旁白、遮罩、文字”。不会用无关模板凑结果。'));
 for(const c of d.items){const card=node('article');card.className='panel';card.append(node('h2',c.id),node('p',c.summary),node('small',c.adaptation_note));const b=node('button','查看完整Prompt、参数与来源');b.type='button';b.onclick=()=>showCard(c.id).catch(e=>{$('libraryStats').textContent=e.message;});card.append(b);root.append(card);}
}
$('librarySearch').onsubmit=e=>{e.preventDefault();search().catch(x=>{$('libraryStats').textContent=x.message;});};
void(async()=>{try{await search();const card=new URLSearchParams(location.search).get('card');if(card)await showCard(card);}catch(e){$('libraryStats').textContent=e.message;}})();
