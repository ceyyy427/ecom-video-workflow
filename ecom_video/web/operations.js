/* Existing local session boundary; no external requests, secrets in storage, or auto approvals. */
(()=>{
  const S=window.OperationsState,$=id=>document.getElementById(id),node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  let token='',project=null,projectEpoch=0,flight=false,cap=null,cache={},lastResultId=null;
  const platform=[['douyin','抖音'],['xiaohongshu','小红书']],field=(name,label,type='text',extra={})=>({name,label,type,...extra});
  function option(value,text){const e=node('option',text);e.value=value;return e;}
  function selectOptions(el,rows){const prior=[...el.selectedOptions].map(o=>o.value);el.replaceChildren(option('',el.required?'请选择':'暂不引用'));for(const [value,text]of rows)el.append(option(value,text));for(const o of el.options)o.selected=prior.includes(o.value);if(!el.multiple&&!el.value)el.value='';}
  function control(f){const label=node('label',f.label);let e;
    if(f.type==='select'){e=node('select');for(const [value,text]of f.options||[])e.append(option(value,text));if(f.kind)e.dataset.recordKind=f.kind;}
    else if(f.type==='textarea'){e=node('textarea');e.rows=f.rows||3;}
    else{e=node('input');e.type=f.type;}
    e.name=f.name;e.required=f.required!==false;if(f.max)e.maxLength=f.max;if(f.placeholder)e.placeholder=f.placeholder;if(f.multiple){e.multiple=true;e.size=3;}if(f.type==='file')e.accept='.csv,text/csv';if(f.type==='password'){e.autocomplete='new-password';}
    if(f.type==='checkbox'){label.className='check';label.replaceChildren(e,document.createTextNode(f.label));}else label.append(e);return label;
  }
  function form(parent,id,title,note,fields,action,details){const f=node('form');f.id=id;f.className='panel';if(title)f.append(node('h3',title));if(note)f.append(node('p',note));const grid=node('div');grid.className='customer-grid';for(const v of fields)grid.append(control(v));f.append(grid);const b=node('button',action);b.type='submit';f.append(b);
    if(details){const d=node('details');d.append(node('summary','格式与使用说明'),node('pre',details));f.append(d);}parent.append(f);return f;}
  const rec=(name,label,kind,extra={})=>field(name,label,'select',{kind,...extra}),file=field('file','选择UTF-8 CSV','file'),yes=label=>field('confirmed',label,'checkbox');
  function build(){const tabs=document.querySelector('.ops-tabs');for(const [i,m]of S.modules.entries()){const tab=node('button',m.name);tab.id='tab-'+m.id;tab.type='button';tab.role='tab';tab.dataset.module=m.id;tab.setAttribute('aria-controls','module-'+m.id);tab.setAttribute('aria-selected',i===0?'true':'false');tab.tabIndex=i===0?0:-1;tabs.append(tab);const panel=node('section');panel.className='ops-module';panel.id='module-'+m.id;panel.role='tabpanel';panel.setAttribute('aria-labelledby',tab.id);panel.hidden=i!==0;panel.append(node('h2',m.title),node('p',m.note));$('opsModules').append(panel);tab.onclick=()=>showModule(m.id);tab.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?6:(i+(e.key==='ArrowRight'?1:6))%7;showModule(S.modules[n].id);$('tab-'+S.modules[n].id).focus();}};}
    form($('module-market'),'marketForm','','',[field('platform','来源平台','select',{options:platform}),file,field('declared_scope','授权及覆盖范围','textarea',{max:1000})],'分析这份样本','sku,product_name,price,currency,sampled_at,source\nA01,软壳衣,399,CNY,2026-10-28,客户授权导出第2行\n价格未知留空，其余列完整；不同币种分别统计。');
    form($('module-strategy'),'strategyForm','','',[field('audience','面向谁','text',{max:120,placeholder:'例如：通勤和周末轻户外人群'}),field('tone','希望的气质','text',{max:120,placeholder:'例如：自然、利落、少一点推销感'}),rec('research_id','参考市场样本','research',{required:false})],'生成定位草稿');
    const margin=node('details');margin.className='panel';margin.append(node('summary','需要试算售价贡献时再填写'));$('module-strategy').append(margin);
    form(margin,'marginForm','','所有金额须用同一币种；未涉及的费用也请明确填0。费率用小数，如0.05。',[...Object.entries({sale_price:'售价',cost:'商品成本',shipping:'物流费用',payment_fee:'支付费用',other_cost:'其他费用',platform_rate:'平台费率',currency:'统一币种（如CNY）'}).map(([n,l])=>field(n,l,'text',{required:false})),...Object.entries({rate_effective_from:'费率生效日',rate_effective_until:'费率截止日',as_of:'本次计算日'}).map(([n,l])=>field(n,l,'date',{required:false}))],'计算已填费用');
    const ideas=node('a','进入创意实验室');ideas.id='opsIdeas';ideas.className='ops-primary';ideas.href='/ideas';$('module-content').append(ideas);
    form($('module-content'),'matrixForm','','只整理主题、版本和素材要求，不自动排期发布。',[field('plan_id','已有国内六方向','select')],'整理内容矩阵');
    form($('module-images'),'imageForm','','',[rec('strategy_id','本商品定位草稿','strategy'),field('asset_id','封面素材','select',{required:false})],'生成待审封面');
    const create=node('a','继续制作、逐镜修改或审核成片');create.id='opsProduction';create.href='/create';$('module-video').append(create);
    form($('module-video'),'packForm','','已有字幕、封面随视频打包。待审片会明确标记待审。',[field('job_id','成片版本','select'),field('platform','交接平台','select',{options:platform}),field('title','待核对标题','text',{max:100}),field('text','待核对正文','textarea',{required:false,max:3000})],'生成本地交接包');
    form($('module-video'),'registrationForm','客户已发布：登记对应关系','只登记对应关系，不执行发布，也不替代成片审核。',[rec('pack_id','交接包','publication_pack'),rec('account_id','账户','connection'),field('content_id','原始作品ID','text',{max:256}),field('reviewer','核对人','text',{max:120}),yes('我已核对账户、作品ID与成片版本的对应关系')],'登记对应关系');
    form($('module-review'),'sourceForm','保存授权来源副本','未知留空，0代表零；不要使用Excel科学计数后的作品ID。',[rec('account_id','账户','connection'),file,field('declaration','使用范围','text',{max:1000})],'保存来源副本','content_id,metric_date,views,likes,comments,shares\n作品原始ID,2026-10-28,1000,0,,5');
    form($('module-review'),'observationForm','说明指标口径','北京时间用于国内报表；累计量不当作日增量。',[rec('source_id','来源副本','source'),field('counting','计数方式','select',{options:[['daily','平台已提供每日次数'],['cumulative','某时刻累计量']]}),field('observed_at','观测时间（北京时间）','datetime-local'),field('definitions','指标口径，每行“列名｜平台原始说明”','textarea',{placeholder:'views｜报表中的视频播放次数\nlikes｜报表中的点赞次数'})],'校验并导入观测');
    form($('module-review'),'freezeForm','','选择口径相同的批次；不同口径分别冻结。',[rec('batch_ids','观测批次（可多选）','observation_batch',{multiple:true})],'冻结复盘快照');
    const ad=node('a','千川等广告报表：进入原广告数据复盘');ad.href='/distribution';$('module-review').append(ad);
    form($('module-comments'),'commentsForm','','昵称不保留，常见电话和邮箱会遮盖；仍需人工检查隐私和分类。',[rec('account_id','评论所属账户','connection'),file,field('declaration','处理授权说明','text',{max:1000})],'导入并整理候选问题','content_id,text\n作品原始ID,这个口袋多大？');
    form($('module-comments'),'hypothesisForm','','',[rec('snapshot_id','冻结复盘','observation_snapshot'),field('parent_job_id','父成片','select'),rec('insights_id','评论候选（可选）','comment_insights',{required:false})],'准备三个创意假设');
    const select=form($('module-comments'),'selectionForm','选择下一版要验证的改动','新项目继承可用画面和参考稿，不继承任何制作审批。',[rec('hypothesis_id','假设提案','hypothesis'),field('reviewer','选择人','text',{max:120}),yes('我选择这一项作为下一版假设，事实、文稿、风格和听审继续单独确认')],'创建待确认的下一版');const candidates=node('div');candidates.id='opsCandidates';select.insertBefore(candidates,select.querySelector('button'));
    form($('module-comments'),'compareForm','','需登记真正属于下一版项目的成片；不匹配的账户、口径或期间会标为不可比。',[rec('iteration_id','已选择的迭代','iteration'),rec('later_snapshot_id','下一轮冻结快照','observation_snapshot')],'对照两轮观测');
    form($('opsConnectionForms'),'accountForm','','手动登记是客户声明，不等于平台已验证账户所有权。',[field('platform','平台','select',{options:platform}),field('name','账户显示名称','text',{max:120}),field('subject','客户声明的账户标识','text',{max:256})],'登记报表账户');
    form($('opsOAuthForms'),'oauthConfigForm','','',[field('client_key','Client Key','text',{max:128}),field('client_secret','Client Secret','password'),field('callback','控制台允许的本机回调')],'保存到系统钥匙串');
    $('oauthConfigForm').elements.callback.value=location.origin+'/api/operations/connectors/douyin/callback';
    form($('opsOAuthForms'),'oauthStartForm','','',[field('config_id','已保存应用','select'),yes('应用已获批，我要授权本人公开作品的只读数据')],'准备平台授权链接');
    form($('opsOAuthForms'),'officialReadForm','','',[rec('account_id','已授权的本人账户','connection'),field('content_ids','已登记作品ID，每行一个（最多10个）','textarea'),yes('只读取这些本人作品的累计观测')],'读取并冻结来源');
    form($('opsOAuthForms'),'disconnectForm','','只移除本安装的凭据。平台授权可另在抖音管理中撤销。',[rec('account_id','要断开的官方账户','connection')],'移除本机连接凭据');
  }
  function showModule(id){for(const m of S.modules){const active=m.id===id;$('module-'+m.id).hidden=!active;$('tab-'+m.id).setAttribute('aria-selected',String(active));$('tab-'+m.id).tabIndex=active?0:-1;}history.replaceState(null,'','#'+id);}
  async function request(path,body){const options=body?{method:'POST',headers:{'X-Workflow-Token':token},body}:{};if(body&&!(body instanceof FormData)){options.body=JSON.stringify(body);options.headers['Content-Type']='application/json';}const r=await fetch('/api'+path,options),data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'本机请求未完成，请核对输入和当前版本');return data;}
  const post=(path,body)=>request('/operations'+path,body);
  function values(f){const v=Object.fromEntries(new FormData(f));for(const n of ['research_id','asset_id','insights_id'])if(n in v&&!v[n])v[n]=null;if(f.elements.confirmed)v.confirmed=f.elements.confirmed.checked;return v;}
  function title(row){const p=row.payload||{};return p.title||p.name||p.positioning?.subject||((S.labels[row.kind]||row.kind)+' · '+row.id.slice(-6));}
  function link(parent,label,href){const a=node('a',label);a.href=href;parent.append(a);return a;}
  function table(parent,rows){const t=node('table'),head=node('tr');head.append(node('th','项目'),node('th','数值／状态'));t.append(head);for(const [k,v]of rows){const tr=node('tr');tr.append(node('td',k),node('td',S.metric(v)));t.append(tr);}parent.append(t);}
  function card(row){const a=node('article');a.className='ops-result';a.append(node('h3',title(row)),node('p',S.summary(row)));const p=row.payload||{};
    if(p.positioning){a.append(node('p','人群：'+p.positioning.audience+'；气质：'+p.positioning.tone));if(p.positioning.core_selling_point)a.append(node('p','核心原文：'+p.positioning.core_selling_point.text));for(const gap of p.positioning.gaps||[])a.append(node('p','待补：'+gap));}
    if(p.price_groups)table(a,Object.entries(p.price_groups).map(([c,v])=>[c+' · 样本中位价',v.median]));
    if(p.totals)table(a,Object.entries(p.totals));if(p.not_daily_reason)a.append(node('p',p.not_daily_reason));
    if(p.groups)table(a,p.groups.map(g=>[g.name,g.count]));
    if(p.candidates)for(const c of p.candidates)a.append(node('p',c.title+'：'+c.change));
    if(p.reasons?.length)a.append(node('p','不可比原因：'+p.reasons.join('、')));if(p.delta)table(a,Object.entries(p.delta).map(([k,v])=>[k+' · 后期减前期',v]));
    if(p.project_id)link(a,'进入待确认下一版','/create?project='+encodeURIComponent(p.project_id));
    for(const [i,f]of (row.files||[]).entries()){const href='/api/operations/objects/'+row.id+'/files/'+i;if(f.path.endsWith('.png')){const img=node('img');img.src=href;img.alt=title(row)+'，待审封面';a.append(img);}link(a,f.path.endsWith('.zip')?'下载交接包':'查看来源或文件',href);}
    const detail=node('details');detail.append(node('summary','查看来源、版本与完整依据'),node('pre',JSON.stringify({id:row.id,basis:row.basis,...p},null,2)));a.append(detail);return a;
  }
  function restrict(){for(const id of ['strategyForm','imageForm','packForm'])$(id).querySelector('button').disabled=flight||!project;for(const id of ['oauthStartForm','officialReadForm'])$(id).querySelector('button').disabled=flight||!cap?.official_reads_enabled;}
  async function refresh(){cap=await request('/operations/connectors');$('opsConnectorState').textContent=(cap.official_reads_enabled?'抖音官方读取已启用，仍需获批并由本人授权。':'官方读取未启用，报表导入可继续。')+' 小红书浏览器MCP关闭。';
    const kinds=[...new Set([...document.querySelectorAll('[data-record-kind]')].map(e=>e.dataset.recordKind))];for(const k of kinds)cache[k]=await request('/operations/objects?kind='+k);
    for(const el of document.querySelectorAll('[data-record-kind]')){let rows=cache[el.dataset.recordKind]||[];if(el.dataset.recordKind==='strategy')rows=rows.filter(r=>!project||r.payload.product_id===project.id);if(['officialReadForm','disconnectForm'].includes(el.closest('form').id))rows=rows.filter(r=>r.payload.transport==='official');selectOptions(el,rows.map(r=>[r.id,title(r)]));}
    selectOptions($('oauthStartForm').elements.config_id,cap.oauth_configs.map(r=>[r.id,r.payload.client_key+' · '+r.id.slice(-6)]));
    const plans=await request('/operations/plans');selectOptions($('matrixForm').elements.plan_id,plans.filter(p=>p.plan?.version==='domestic-creative-v1'||p.version==='domestic-creative-v1').map(p=>[p.id,p.plan?.subject||p.subject||p.id.slice(-6)]));
    candidates();await renderHistory();restrict();
  }
  async function chooseProject(){const epoch=++projectEpoch,id=$('opsProject').value;project=null;restrict();if(id){const p=await request('/customer-projects/'+id);if(epoch!==projectEpoch)return;project=p;}
    $('opsProjectState').textContent=project?project.product.title+' · '+(project.product.status==='script_confirmed'?'文稿已确认，方向与听审仍按版本核对':'请先在商品工作台核对资料与文稿'):'可先分析市场样本，定位和封面需要已核对商品。';
    for(const id of ['opsCreate','opsProduction'])$(id).href='/create'+(project?'?project='+project.id:'');$('opsIdeas').href='/ideas'+(project?'?sourceProject='+project.id:'');
    const assets=project?project.media.filter(a=>a.kind!=='audio'):[];selectOptions($('imageForm').elements.asset_id,assets.map(a=>[a.id,a.name]));$('imageForm').elements.asset_id.options[0].textContent='暂缺商品图，生成标记图示';
    const jobs=project?project.versions.filter(v=>['ready','needs_review','rejected'].includes(v.status)):[];const rows=jobs.map(j=>[j.id,(j.status==='ready'?'已审':'待审／退回')+' · '+j.id.slice(-6)]);selectOptions($('packForm').elements.job_id,rows);selectOptions($('hypothesisForm').elements.parent_job_id,rows);await refresh();
  }
  function candidates(){const id=$('selectionForm').elements.hypothesis_id.value,p=(cache.hypothesis||[]).find(r=>r.id===id)?.payload;$('opsCandidates').replaceChildren();for(const c of p?.candidates||[]){const label=node('label'),input=node('input');input.type='radio';input.name='candidate_id';input.value=c.id;input.required=true;label.append(input,node('span',c.title+'：'+c.change));$('opsCandidates').append(label);}}
  async function renderHistory(){const kind=$('opsHistoryKind').value,rows=cache[kind]||await request('/operations/objects?kind='+kind);$('opsHistory').replaceChildren();if(!rows.length)$('opsHistory').append(node('p','还没有这类记录。完成上方对应任务后，会在这里保留依据。'));for(const row of rows.filter(r=>r.id!==lastResultId).slice(0,10))$('opsHistory').append(card(row));if(rows.length===1&&rows[0].id===lastResultId)$('opsHistory').append(node('p','最新结果已在上方展示，完整来源随记录保留。'));}
  function bind(id,action){$(id).onsubmit=async e=>{e.preventDefault();if(flight)return;flight=true;for(const b of document.querySelectorAll('form button'))b.disabled=true;$('opsState').textContent='正在本机处理，请保留当前页面…';try{const result=await action($(id));lastResultId=result?.id||null;$('opsResults').replaceChildren();if(result?.kind)$('opsResults').append(card(result));else if(result)$('opsResults').append(node('p',result.available===false?result.reason:result.profit?'已填费用贡献：'+result.profit+' '+result.currency+'；贡献率 '+result.margin_ratio:result.note||'本机操作完成'));if(result?.url?.startsWith('https://open.douyin.com/platform/oauth/connect/?')){const a=link($('opsResults'),'由本人前往抖音平台登录授权',result.url);a.target='_blank';a.rel='noreferrer';}await refresh();$('opsState').textContent='本机记录已保存。草稿与工程结果仍需实际人工核对。';}catch(error){$('opsState').textContent=error.message;}finally{flight=false;for(const b of document.querySelectorAll('form button'))b.disabled=false;restrict();}};}
  async function init(){build();token=(await request('/session')).token;
    const projects=await request('/customer-projects');selectOptions($('opsProject'),projects.map(p=>[p.id,p.title]));$('opsProject').options[0].textContent='先选择商品项目';$('opsProject').onchange=()=>chooseProject().catch(e=>$('opsState').textContent=e.message);
    bind('marketForm',f=>post('/research',new FormData(f)));
    bind('strategyForm',f=>{if(!project)throw Error('先选择商品项目');return post('/strategies',{...values(f),product_id:project.id,expected_revision:project.product.revision});});
    bind('marginForm',f=>post('/margin',Object.fromEntries(Object.entries(values(f)).map(([k,v])=>[k,v||null]))));
    bind('matrixForm',f=>post('/content-matrices',values(f)));bind('imageForm',f=>post('/image-packs',values(f)));bind('packForm',f=>post('/publication-packs',values(f)));
    bind('registrationForm',f=>post('/registrations',values(f)));bind('accountForm',f=>post('/accounts',values(f)));bind('sourceForm',f=>post('/sources',new FormData(f)));
    bind('observationForm',f=>{const v=values(f);return post('/observations/import',{source_id:v.source_id,metric_contract:{counting:v.counting,timezone:'Asia/Shanghai',observed_at:v.observed_at+(v.observed_at.length===16?':00':'')+'+08:00',metric_definitions:S.definitions(v.definitions)}});});
    bind('freezeForm',f=>post('/observations/freeze',{batch_ids:[...f.elements.batch_ids.selectedOptions].map(o=>o.value).filter(Boolean)}));
    bind('commentsForm',async f=>{const imported=await post('/comments/import',new FormData(f));return post('/comments/'+imported.id+'/analyze',{});});
    bind('hypothesisForm',f=>post('/hypotheses',values(f)));bind('selectionForm',f=>post('/iterations',values(f)));bind('compareForm',f=>post('/comparisons',values(f)));
    bind('oauthConfigForm',async f=>{const data=values(f);try{return await post('/connectors/douyin/config',data);}finally{f.elements.client_secret.value='';}});
    bind('oauthStartForm',async f=>{const result=await post('/connectors/douyin/authorize',values(f));return {note:result.note,url:result.url};});
    bind('officialReadForm',f=>{const v=values(f);return post('/connectors/douyin/read',{account_id:v.account_id,content_ids:v.content_ids.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),confirmed:v.confirmed});});
    bind('disconnectForm',f=>post('/connectors/'+f.elements.account_id.value+'/disconnect',{}));
    $('selectionForm').elements.hypothesis_id.onchange=candidates;$('opsHistoryKind').onchange=()=>renderHistory().catch(e=>$('opsState').textContent=e.message);
    await refresh();const selected=new URLSearchParams(location.search).get('project');if(selected&&projects.some(p=>p.id===selected)){$('opsProject').value=selected;await chooseProject();}const hash=location.hash.slice(1);if(S.modules.some(m=>m.id===hash))showModule(hash);$('opsState').textContent='先选择商品或导入样本，所有新内容均待实际核对。';
  }
  init().catch(error=>{$('opsState').textContent='读取未完成：'+error.message;restrict();});
})();
