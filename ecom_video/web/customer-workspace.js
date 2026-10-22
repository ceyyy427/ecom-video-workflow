/* Read-only presentation adapter. No network, storage, form writes or approvals. */
(function () {
  'use strict';
  const statusNames = {draft:'待生成',queued:'排队中',validating:'检查素材',rendering:'正在生成',
    auditing:'检查成片',needs_review:'待人工审片',ready:'已人工复核',failed:'生成失败',
    blocked:'内容预检未通过',cancelled:'已取消',rejected:'需要修改'};
  const check = (text, state='pending') => ({text,state});
  const localImage = value => typeof value === 'string' && value.startsWith('/api/') ? value : null;

  function summarize(state={}) {
    const p=state.project;
    if (!p) return {title:'新建商品项目',save:'选择项目后开始制作',checks:[
      check('待确认事实'),check('待确认文稿'),check('待选择风格'),check('待人工听核'),check('待人工审片')],
      available:{material:false,direction:false,film:false},mode:'material',preview:null,
      next:{href:'#projectControls',text:'下一步：选择或新建项目'}};
    const product=p.product || {}, job=p.job, format=p.settings?.brief?.format;
    const changed=!!p.inputs_changed || !!state.dirty;
    const facts=!!product.current_review_id;
    const script=(product.script_approvals || []).some(a=>a.draft_id === product.current_draft_id);
    const selected=p.recommendations?.options?.find(o=>o.id === state.selected);
    const savedStyle=!!job?.storyboard && !changed && !p.iteration?.style_confirm_needed && (!p.delivery_reviews?.enabled || !!p.delivery_reviews.storyboard);
    const heard=p.alignment?.status === 'confirmed' && !changed;
    const reviewed=job?.status === 'ready' && !changed;
    const checks=[check(facts?'已确认事实':'待确认事实',facts?'done':'pending'),
      check(state.dirty?'本地编辑未保存':script?'已确认当前稿':'待确认文稿',script && !state.dirty?'done':'pending'),
      check(savedStyle?'已保存风格':p.iteration?.style_confirm_needed?'待确认迭代风格':selected?'已选择 · 待保存':'待选择风格',savedStyle?'done':'pending'),
      format==='showcase'?check('纯展示 · 无需配音','neutral'):check(heard?'已人工听核':p.alignment?.status==='failed'?'对齐失败 · 待处理':'待人工听核',heard?'done':'pending'),
      check(reviewed?'已人工复核':job?.status==='ready'?'旧版已审 · 新输入待审':'待人工审片',reviewed?'done':'pending')];
    const visuals=(p.media || []).filter(a=>['image','video'].includes(a.kind));
    const material=visuals.find(a=>a.id === p.settings?.product_reference_id) || visuals[0];
    const direction=selected && localImage(state.previews?.[selected.id]);
    const film=job?.artifacts?.some(a=>a.kind === 'video');
    const available={material:!!material,direction:!!direction,film:!!film};
    const mode=state.mode || (film?'film':'material');
    let preview=null;
    if(mode==='material' && material) preview={kind:material.kind,src:`/api/customer-projects/${encodeURIComponent(p.id)}/assets/${encodeURIComponent(material.id)}`,label:'商品素材 · '+material.name};
    if(mode==='direction' && direction) preview={kind:'image',src:direction,label:selected.name+' · 风格帧示意，不代表成片'};
    if(mode==='film' && film) preview={kind:'video',src:`/api/jobs/${encodeURIComponent(job.id)}/artifacts/video`,label:(changed?'旧版成片 · 输入或编辑已变化':'成片')+' · '+(statusNames[job.status] || job.status)};
    let next={href:'#step1',text:'下一步：上传商品资料与素材'};
    if(state.dirty) next={href:'#'+(state.editStep || 'step2'),text:'下一步：保存并核对本地修改'};
    else if((product.sources || []).length || visuals.length) {
      if(!facts) next={href:'#step2',text:'下一步：核对商品事实'};
      else if(!script) next={href:'#step2',text:'下一步：核对并确认当前文稿'};
      else if(!selected && !savedStyle) next={href:'#step3',text:'下一步：选择视频方向'};
      else if(format!=='showcase' && !heard) next={href:'#step3',text:'下一步：检查配音并完成听核'};
      else next={href:'#step4',text:job?.status==='needs_review'?'下一步：完整观看并人工审片':reviewed?'查看成片与已保存版本':'下一步：检查分镜与制作状态'};
    }
    return {title:product.title || p.title || '商品项目',save:state.dirty?'有未保存的本地编辑':state.busy?'正在处理当前操作':`已载入修订 ${p.revision}`,
      checks,available,mode,preview,next};
  }

  function mount(doc, env={}) {
    const get=id=>doc.getElementById(id);
    const modes=Array.from(doc.querySelectorAll('[data-preview-mode]'));
    const links=Array.from(doc.querySelectorAll('.workspace-steps a'));
    const checkIds=['workspaceFactState','workspaceScriptState','workspaceStyleState','workspaceListeningState','workspaceFilmState'];
    let last={},mode=null,projectId=null;
    const setText=(id,text)=>{const e=get(id);if(e.textContent!==text)e.textContent=text;};
    function media(element, source) {
      if (element.getAttribute('src') !== source) {
        if(element.pause) element.pause();
        if(source) element.setAttribute('src',source); else element.removeAttribute('src');
      }
      element.hidden=!source;
    }
    function update(state) {
      last=state;
      const id=state.project?.id || null;
      if(id!==projectId){projectId=id;mode=null;}
      const view=summarize({...state,mode});
      setText('workspaceProjectTitle',view.title);
      setText('workspaceSaveState',view.save);
      get('workspaceSaveState').dataset.dirty=String(!!state.dirty);
      get('workspaceSteps').hidden=!state.project;
      view.checks.forEach((c,i)=>{setText(checkIds[i],c.text);get(checkIds[i]).dataset.state=c.state;});
      modes.forEach(button=>{button.disabled=!view.available[button.dataset.previewMode];button.setAttribute('aria-pressed',String(view.mode===button.dataset.previewMode));});
      const visual=view.preview;
      media(get('workspacePreview'),visual?.kind==='video'?visual.src:null);
      media(get('workspaceImage'),visual?.kind==='image'?visual.src:null);
      get('workspaceImage').setAttribute('alt',visual?.label || '');
      get('workspaceEmpty').hidden=!!visual;
      setText('workspaceMediaCaption',visual?.label || ({material:'上传并选择当前商品素材后预览；不使用其他商品占位。',direction:'当前还没有所选方向的风格帧，先确认文稿并选择方向。',film:'还没有当前制作版本的成片，生成后仍需人工审片。'}[view.mode]));
      setText('workspaceNext',view.next.text+' ↗');get('workspaceNext').setAttribute('href',view.next.href);
    }
    modes.forEach(button=>button.addEventListener('click',()=>{if(!button.disabled){mode=button.dataset.previewMode;update(last);}}));
    function step(id) { links.forEach(a=>{if(a.getAttribute('href')==='#'+id)a.setAttribute('aria-current','step');else a.removeAttribute('aria-current');}); }
    links.forEach(a=>a.addEventListener('click',()=>step(a.getAttribute('href').slice(1))));
    if(env.IntersectionObserver) {
      const observer=new env.IntersectionObserver(entries=>{
        const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>Math.abs(a.boundingClientRect.top)-Math.abs(b.boundingClientRect.top));
        if(visible.length)step(visible[0].target.id);
      },{rootMargin:'-10% 0px -60% 0px',threshold:0});
      for(let i=1;i<=4;i++) observer.observe(get('step'+i));
    }
    // Only these two mirrored players are coordinated; polling never seeks or plays.
    get('workspacePreview').addEventListener('play',()=>get('film').pause());
    get('film').addEventListener('play',()=>get('workspacePreview').pause());
    return {update};
  }

  if(typeof module!=='undefined' && module.exports) module.exports={summarize,mount};
  if(typeof document!=='undefined') {
    window.CustomerWorkspace=mount(document,{IntersectionObserver:window.IntersectionObserver});
    if(typeof paintWorkspace==='function') paintWorkspace();
    const refresh=()=>queueMicrotask(()=>{if(typeof paintWorkspace==='function')paintWorkspace();});
    document.getElementById('work').addEventListener('input',refresh);
    document.getElementById('work').addEventListener('change',refresh);
  }
})();
