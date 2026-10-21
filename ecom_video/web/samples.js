'use strict';
function exclusivePlayback(video){video.addEventListener('play',()=>{for(const other of document.querySelectorAll('video,audio'))if(other!==video)other.pause();});}
(async()=>{
 const root=document.getElementById('narrativeGallery');if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const response=await fetch('/api/samples/narrative');if(!response.ok)throw Error('完整叙事样片暂不可用');
  const rows=await response.json();root.replaceChildren();
  if(rows.length!==3){root.append(el('p','本安装目录未包含这组历史样片。可从“商品制作”新建项目；首次安装演练见“操作指南”。'));return;}
  for(const row of rows){
   const base='/api/samples/narrative/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 同一透明咖啡杯 · 实拍与火山合成配音'));
   const video=el('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=base+'video';video.poster=base+'poster';video.setAttribute('aria-label',row.title+'完整新版');card.append(video);
   const compare=el('details');compare.append(el('summary','对比此前版本与单镜修改'));
   for(const [kind,label] of [['parent','此前编排'],['retake','仅第三镜调整动效强度和时机']]){compare.append(el('p',label));const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload='none';v.src=base+kind;v.setAttribute('aria-label',row.title+label);compare.append(v);}card.append(compare);
   const links=el('div');links.className='downloads';for(const [kind,label] of [['video','下载待审完整版'],['shotbook','分镜、动作避让与Prompt'],['subtitles','字幕'],['narration','听整条配音']]){const a=el('a',label);a.href=base+kind+(kind==='narration'?'':'?download=true');links.append(a);}card.append(links,el('small','开场/讲解/收尾使用不同节奏。仅第三镜参数修改时其余镜头和声音保留；仍待人工听核与成片审核，不自动投放。'));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
})();
(async()=>{
 const root=document.getElementById('sampleGallery');
 const copy={cinema:['P6 / 形与留白','纯展示 · 字形露出、局部特写、音乐驱动'],social:['P6 / 桌边的一刻','场景种草 · 问句开场、生活构图、语义字卡'],lab:['P6 / 先看细节','商品解说 · 放大观察、扫描取景、配音驱动'],editorial:['P5 / 质感杂志','配音字级锚点、留白陈列、Remotion'],quiet:['P5 / 安静日常','全幅场景、素排字幕、缓慢运镜'],collage:['P5 / 生活剪贴','纸边构图、柔和入场、品牌字卡'],bauhaus:['P5 / 几何陈列','几何块面、明确层次、商品主角'],evidence:['P5 / 细节解说','真实素材与口播时间轴'],kinetic:['P5 / 节奏字卡','短标题与商品画面'],premium:['01 / 质感展示','慢推近、暖色留白、顶部字幕'],demo:['02 / 功能与细节演示','明确选段、局部细节、信息式字幕'],lifestyle:['03 / 场景转化','桌面情境、柔和横移、问题式结尾']};
 const node=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const response=await fetch('/api/samples');if(!response.ok)throw new Error('样片读取失败');
  const samples=await response.json();root.replaceChildren();
  if(!samples.length){root.append(node('p','当前还没有示例成片。'));return;}
  for(const style of ['cinema','social','lab','editorial','quiet','collage','bauhaus','evidence','kinetic','premium','demo','lifestyle']){
   const s=samples.find(x=>x.style===style);if(!s)continue;
   const card=node('article');card.className='panel';card.append(node('h2',copy[style][0]),node('p',copy[style][1]));
   const video=node('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=`/api/jobs/${s.id}/artifacts/video`;card.append(video);
   const links=node('div');links.className='downloads';
   for(const [label,url] of [['查看分镜 / 复制编辑',`/?job=${s.id}`],['下载成片',`/api/jobs/${s.id}/artifacts/video?download=true`],['无背景音乐版',`/api/jobs/${s.id}/artifacts/video_clean?download=true`]]){const a=node('a',label);a.href=url;links.append(a);}
   card.append(links,node('small',s.status==='ready'?'已记录本地人工复核':'待人工复核 · 未提交平台'));root.append(card);
  }
 }catch(e){root.replaceChildren(node('p',e.message));}
})();

(async()=>{
 const root=document.getElementById('clientGallery');
 const node=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch('/api/samples/client');if(!r.ok)throw Error('完整样片目录暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(!rows.length){root.append(node('p','本安装目录未包含这组历史样片。可从“商品制作”新建项目；首次安装演练见“操作指南”。'));return;}
  for(const row of rows){
   const base='/api/samples/client/'+encodeURIComponent(row.style)+'/';
   const card=node('article');card.className='panel';card.append(node('h2',row.title),node('p',row.description),node('p',Math.round(row.duration*10)/10+' 秒 · 1080 × 1920 · 实拍'));
   const video=node('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=base+'video';video.poster=base+'poster';video.setAttribute('aria-label',row.title+'完整样片');card.append(video);
   const links=node('div');links.className='downloads';
   for(const [kind,label] of [['video','下载待审样片'],['shotbook','查看分镜与来源'],['subtitles','下载字幕'],['narration','试听配音']]){const a=node('a',label);a.href=base+kind+(kind==='video'||kind==='subtitles'?'?download=true':'');links.append(a);}
   card.append(links,node('small','待人工确认 · 非性能测评 · 未投放'));root.append(card);
  }
 }catch(e){root.replaceChildren(node('p',e.message));}
})();

async function comparisonGallery(rootId,prefix,unchanged){
 const root=document.getElementById(rootId);if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch(prefix);if(!r.ok)throw Error('定向推荐示例暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(!rows.length){root.append(el('p','本安装目录未包含这组历史样片。可从“商品制作”新建项目；首次安装演练见“操作指南”。'));return;}
  for(const row of rows){
   const base=prefix+'/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 单句换声新版 · 待听审'));
   if(prefix.endsWith('/production')){const note=el('p','这是反馈时的历史取景版本。主体取景修订与原版对照：');const a=el('a','查看页首取景修订');a.href='#framingExamples';note.append(a);card.append(note);}
   const video=el('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=base+'video';video.poster=base+'poster';video.setAttribute('aria-label',row.title+'单句换声新版');card.append(video);
   const compare=el('details'),summary=el('summary','对比父片与第三句配音');compare.append(summary);
   const parent=el('video');exclusivePlayback(parent);parent.controls=true;parent.playsInline=true;parent.preload='none';parent.src=base+'parent';parent.setAttribute('aria-label',row.title+'父片');compare.append(parent);
   for(const [kind,title] of [['old','第三句 · 原配音'],['new','第三句 · 新配音']]){const label=el('label',title),audio=el('audio');exclusivePlayback(audio);audio.controls=true;audio.preload='none';audio.src=base+kind;label.append(audio);compare.append(label);}
   if(prefix.endsWith('/production')){compare.append(el('p','仅首镜动效调整（以上方语音新版为父片）'));const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload='none';v.src=base+'retake';v.setAttribute('aria-label',row.title+'首镜动效修订');compare.append(v);}
   card.append(compare);
   const links=el('div');links.className='downloads';for(const [kind,title] of [['video','下载待审新版'],['parent','下载父片'],['shotbook','分镜与来源'],['subtitles','新版字幕'],['recommendations','三个推荐与依据'],...(prefix.endsWith('/categories')?[['selection','人工选段核对记录']]:[]),...(prefix.endsWith('/production')?[['retake','仅首镜调整动效的对照']]:[])]){const a=el('a',title);a.href=base+kind+'?download=true';links.append(a);}card.append(links,el('small',`其余${unchanged}镜参数/实拍及区间外原声保留；总时长与最终混音可变化。无自动投放。`));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
}
comparisonGallery('productionGallery','/api/samples/production',5);
void (async()=>{
 const root=document.getElementById('readinessGallery');if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const response=await fetch('/api/samples/readiness');if(!response.ok)throw Error('脚本与审核示例暂不可用');
  const rows=await response.json();root.replaceChildren();
  if(!rows.length){root.append(el('p','本安装目录未包含这组历史样片。可从“商品制作”新建项目；首次安装演练见“操作指南”。'));return;}
  for(const row of rows){
   const base='/api/samples/readiness/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 待人工听审'));
   const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload='metadata';v.src=base+'video';v.poster=base+'poster';card.append(v);
   const links=el('div');links.className='downloads';
   for(const [kind,title] of [['video','下载待审成片'],['report','综合审核 HTML'],['audit','审核 JSON'],['script','生成稿与引用'],['preflight','制作前素材检查'],['selection','人工选段记录'],['subtitles','字幕'],['shotbook','分镜']]){const a=el('a',title);a.href=base+kind+'?download=true';links.append(a);}
   card.append(links,el('small','本机示例配音；实拍区间人工校正，原识别结果保留。审核未覆盖项不算通过，不自动投放。'));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
})();
comparisonGallery('contextualGallery','/api/samples/contextual',6);
comparisonGallery('categoryGallery','/api/samples/categories',4);

(async()=>{
 const root=document.getElementById('motionGallery');if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch('/api/samples/motion');if(!r.ok)throw Error('动效对比暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(!rows.length){root.append(el('p','本安装目录未包含这组历史样片。可从“商品制作”新建项目；首次安装演练见“操作指南”。'));return;}
  for(const row of rows){
   const base='/api/samples/motion/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 同文稿、同配音、同实拍选段'));
   const video=el('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=base+'video';video.poster=base+'poster';video.setAttribute('aria-label',row.title+'新版动效');card.append(video);
   const detail=el('details');detail.append(el('summary','对比此前编排'));
   const parent=el('video');exclusivePlayback(parent);parent.controls=true;parent.playsInline=true;parent.preload='none';parent.src=base+'parent';parent.setAttribute('aria-label',row.title+'此前编排');detail.append(parent);card.append(detail);
   const links=el('div');links.className='downloads';for(const [kind,label] of [['video','下载待审动效版'],['parent','下载此前版本'],['retake','仅第三镜关闭动效的对照'],['shotbook','配方、Prompt 与来源'],['subtitles','字幕']]){const a=el('a',label);a.href=base+kind+'?download=true';links.append(a);}card.append(links,el('small','配方为竖屏适配；无新增云调用。仍待人工听核与审片，不自动投放。'));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
})();

async function qualityComparison(id,url,expected,extras=[]){
 const root=document.getElementById(id);if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch(url);if(!r.ok)throw Error('精修对比暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(rows.length!==expected){root.append(el('p','本安装目录没有这组示例。新建商品后可在逐镜设置中选择画面精修。'));return;}
  for(const row of rows){
   const base=url+'/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 同实拍/同配音 · 待人工听审'));
   const video=el('video');exclusivePlayback(video);video.controls=true;video.playsInline=true;video.preload='metadata';video.src=base+'video';video.poster=base+'poster';video.setAttribute('aria-label',row.title+'精修版');card.append(video);
   const details=el('details');details.append(el('summary','对比原版与只关闭第三镜精修'));
   for(const [kind,label]of[['parent','精修前原版'],['retake','仅第三镜关闭精修']]){details.append(el('p',label));const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload='none';v.src=base+kind;v.setAttribute('aria-label',row.title+label);details.append(v);}card.append(details);
   const links=el('div');links.className='downloads';for(const[k,label]of[['video','下载待审精修版'],['shotbook','分镜与精修记录'],['subtitles','字幕'],['narration','原配音'],...extras]){const a=el('a',label);a.href=base+k+(k==='narration'?'':'?download=true');links.append(a);}card.append(links,el('small','标题与轻强调只使用原稿；估算字不强调。仅改一镜时其余镜头文件与整片解码声音保持不变。'));
   root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
}
qualityComparison('qualityGallery','/api/samples/quality',3);
qualityComparison('refinementGallery','/api/samples/refinement',2,[['recommendations','三方案与输入对照'],['treatment','节奏与字锚点记录'],['selection','原人工选段依据']]);

// A separate comparison keeps all historical demonstrations and review states intact.
(async()=>{
 const root=document.getElementById('framingGallery');if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch('/api/samples/framing');if(!r.ok)throw Error('取景对照暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(!rows.length){root.append(el('p','取景修订尚未发布，旧版本保持原样。'));return;}
  for(const row of rows){
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description));
   const base='/api/samples/framing/'+encodeURIComponent(row.style)+'/';
   for(const [kind,label]of[['video','主体取景修订 · 待听核与审片'],['parent','反馈时的完整原版'],['retake','仅第三镜微调水平取景']]){
    card.append(el('p',label));const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload=kind==='video'?'metadata':'none';v.src=base+kind;v.setAttribute('aria-label',row.title+label);if(kind==='video')v.poster=base+'poster';card.append(v);
   }
   const links=el('div');links.className='downloads';for(const[k,label]of[['video','下载取景修订'],['framing','逐镜取景与保留记录'],['shotbook','分镜与来源'],['narration','试听原配音']]){const a=el('a',label);a.href=base+k+(k==='narration'?'':'?download=true');links.append(a);}card.append(links,el('small','没有重写文稿或配音；裁边必须人工核对全过程，不自动认定商品或动作正确，不自动投放。'));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
})();

async function promptGallery(rootId,prefix,unchanged,hasParent=true,detailComparison=false){
 const root=document.getElementById(rootId);if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch(prefix);if(!r.ok)throw Error('商品画面方案暂不可用');
  const rows=await r.json();root.replaceChildren();if(rows.length!==3){root.append(el('p','这组完整实拍对照尚未发布，旧样片保持原样。'));return;}
  for(const row of rows){
   const base=prefix+'/' +encodeURIComponent(row.style)+'/',card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 待人工听核与审片'));
   const player=(kind,label)=>{const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload=kind==='video'?'metadata':'none';v.src=base+kind;v.setAttribute('aria-label',label);if(kind==='video')v.poster=base+'poster';return v;};
   card.append(player('video',row.title));const d=el('details');d.append(el('summary',hasParent?'对照原编排与仅首镜换 Prompt':'对照仅首镜换 Prompt 的副本'));if(hasParent)d.append(el('p','此前基础编排（统一对照；风格和混音也可能不同）'),player('parent','原编排'));d.append(el('p','仅首镜换同类 Prompt 变体'),player('retake','仅首镜换Prompt'));if(detailComparison)d.append(el('p','仅第二镜细节括号换变体，其余六镜不变'),player('detail-retake','仅第二镜细节换Prompt'));card.append(d);
   const links=el('div');links.className='downloads';for(const[k,label]of[['video','下载待审成片'],['recommendations','三个推荐与命中依据'],['prompts','逐镜Prompt与避让结果'],['shotbook','分镜与素材来源'],['narration','试听原配音']]){const a=el('a',label);a.href=base+k+(k==='narration'?'':'?download=true');links.append(a);}if(detailComparison){const a=el('a','三份待确认备选稿与逐句策略');a.href=base+'alternatives?download=true';links.append(a);}card.append(links,el('small',`同帧双窗不是前后效果对比；动效不生成商品功能。单镜副本其余${unchanged}镜及整片声音保留。`));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
}
promptGallery('promptGallery','/api/samples/prompts',5);
promptGallery('promptCategoryGallery','/api/samples/prompt-categories',4);

promptGallery('libraryMotionGallery','/api/samples/library-motion',4);

promptGallery('productCardGallery','/api/samples/product-cards',4,false);

promptGallery('semanticGallery','/api/samples/semantic-mix',6,false,true);

(async()=>{
 const root=document.getElementById('materialGallery');if(!root)return;
 const el=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 try{
  const r=await fetch('/api/samples/material-checks');if(!r.ok)throw Error('素材检查示例暂不可用');
  const rows=await r.json();root.replaceChildren();
  if(!rows.length){root.append(el('p','本目录尚未包含完整验收样片。可在商品制作中开启“增强素材检查”，选择参照图并重新识别。'));return;}
  for(const row of rows){
   const base='/api/samples/material-checks/'+encodeURIComponent(row.style)+'/';
   const card=el('article');card.className='panel';card.append(el('h3',row.title),el('p',row.description),el('p',row.duration.toFixed(1)+'秒 · 真实抽样证据 · 待人工听审'));
   const v=el('video');exclusivePlayback(v);v.controls=true;v.playsInline=true;v.preload='metadata';v.src=base+'video';v.poster=base+'poster';card.append(v);
   const d=el('details');d.append(el('summary','只修改一镜后的对照'));const one=el('video');exclusivePlayback(one);one.controls=true;one.playsInline=true;one.preload='none';one.src=base+'retake';d.append(one);card.append(d);
   const links=el('div');links.className='downloads';
   for(const[k,label]of[['video','下载待审成片'],['recognition','原始识别与复核'],['preflight','逐句素材缺口'],['selection','实际选段依据'],['recommendations','三个风格与素材适配'],['license','素材来源及许可'],['acceptance','自动验收与未覆盖项'],['shotbook','逐镜记录'],['subtitles','字幕'],['narration','试听配音']]){const a=el('a',label);a.href=base+k+(k==='narration'?'':'?download=true');links.append(a);}card.append(links,el('small','自动验证记录不代替客户确认；旧版本保留，不自动投放。'));root.append(card);
  }
 }catch(e){root.replaceChildren(el('p',e.message));}
})();
