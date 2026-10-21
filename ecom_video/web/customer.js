'use strict';
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined)
    e.textContent = text; if (cls)
    e.className = cls; return e; };
const option = (value, text) => { const e = node('option', text); e.value = value; return e; };
const roles = { product: '商品全貌', detail: '细节', lifestyle: '使用场景', evidence: '测试证据', voice: '成品配音', music: '背景音乐' };
const statuses = { draft: '待生成', queued: '排队中', validating: '检查素材', rendering: '正在生成', auditing: '检查成片', needs_review: '待人工审片', ready: '已人工复核', failed: '生成失败', blocked: '内容预检未通过', cancelled: '已取消', rejected: '需要修改' };
const previewFlights = new Set();
let token = '', p = null, busy = false, timer = null, selected = '', previews = {}, scenes = [], settingsDirty = false, scriptDirty = false, shotEdits = new Map(), mediaEdits = new Map(), seenAlignment = '', stopAt = null;
const stagedAlignmentDrafts = new Set();
let scriptAlternatives=null;
function message(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
async function api(path, opts = {}) { const headers = { 'X-Workflow-Token': token, ...opts.headers }; if (opts.body && !(opts.body instanceof FormData))
    headers['Content-Type'] = 'application/json'; const r = await fetch('/api' + path, { ...opts, headers }); const data = await r.json(); if (!r.ok) {
    const e = Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    e.status = r.status;
    throw e;
} return data; }
const post = (path, data = {}) => api(path, { method: 'POST', body: JSON.stringify(data) });
const base = () => '/customer-projects/' + p.id;
const productBase = () => '/products/' + p.id;
const version = () => ({ revision: p.revision, job_id: p.job.id, board_revision: p.job.storyboard_revision });
const active = () => p?.job && ['queued', 'validating', 'rendering', 'auditing'].includes(p.job.status);
function dirty() { return settingsDirty || scriptDirty || shotEdits.size > 0 || mediaEdits.size > 0; }
function paintWorkspace() { window.CustomerWorkspace?.update({project:p,selected,previews,dirty:dirty(),busy,editStep:scriptDirty?'step2':settingsDirty||mediaEdits.size?'step1':'step4'}); }
function controls() { $('projectControls').disabled = busy; $('work').disabled = busy || !p; paintVolcVoice(); paintWorkspace(); }
async function run(fn) { if (busy)
    return; busy = true; controls(); try {
    await fn();
}
catch (e) {
    message(e.message, true);
}
finally {
    busy = false;
    controls();
    schedule();
} }
function setSettings() { const s = p.settings;
    $('motionRepeatLimit').value = s.motion_repeat_limit || 2;
    $('productReference').replaceChildren(option('', '选择一张清楚的商品参照图'), ...p.media.filter(a=>a.kind==='image').map(a=>option(a.id,a.name)));
    $('materialChecks').checked=!!s.material_checks; $('productReference').value=s.product_reference_id||''; $('referenceOnly').checked=!!s.reference_only; $('strictProduct').checked=!!s.strict_product; $('actionTiming').checked=!!s.action_timing; $('autoSelect').checked=!!s.auto_select; $('format').value = s.brief.format; $('brandName').value = s.brand_name; for (const k of ['category', 'audience', 'tone'])
    $(k).value = s.brief[k]; $('reviewContext').value = s.review_context; }
function settings() { return { ...p.settings, motion_repeat_limit:Number($('motionRepeatLimit').value), auto_select:$('autoSelect').checked, material_checks:$('materialChecks').checked, reference_only:$('referenceOnly').checked, strict_product:$('strictProduct').checked, action_timing:$('actionTiming').checked, product_reference_id:$('productReference').value||null, brief: { format: $('format').value, category: $('category').value, audience: $('audience').value, tone: $('tone').value }, brand_name: $('brandName').value, review_context: $('reviewContext').value }; }
function adopt(next, { reset = false } = {}) {
    const changedProject = reset || p?.id !== next.id, changedProduct = changedProject || p?.product.revision !== next.product.revision;
    if (changedProject) {
        selected = '';
        previews = {};
        settingsDirty = false;
        scriptDirty = false;
        shotEdits.clear();
        mediaEdits.clear();
        seenAlignment = '';
    }
    if (changedProduct || changedProject || p?.revision !== next.revision || p?.job?.id !== next.job?.id) clearMaterialReport();
    const changedBasis = p?.direction_basis !== next.direction_basis;
    if (changedProject || changedBasis || p?.recommendations?.fingerprint !== next.recommendations?.fingerprint) {
        previews = {};
        $('previewState').textContent = '';
    }
    if (p?.job?.id !== next.job?.id) {
        $('filmChecked').checked = false;
        $('filmReviewer').value = '';
        $('filmNote').value = '';
        previews = {};
        if (changedProject || changedBasis) selected = '';
    }
    p = next;
    $('customerIteration').hidden=!p.iteration;
    if(p.iteration){$('customerIterationText').textContent=`此新版来自冻结复盘 ${p.iteration.review_id}，父片 ${p.iteration.parent_job_id}。${p.iteration.style_confirm_needed?'当前分镜还需在迭代页人工确认风格；之后可继续生成。':''}`;$('customerIterationLink').href='/experiments?id='+encodeURIComponent(p.iteration.id);}
    if (changedProject || changedBasis) {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem('ecom.direction.' + p.id)); } catch (_) {}
        selected = saved?.basis === p.direction_basis ? saved.style : '';
    }
    if (!p.inputs_changed && p.job?.storyboard) selected = p.job.storyboard.creative?.style_id || selected;
    if (!p.recommendations?.options.some(s=>s.id===selected)) selected = '';
    localStorage.setItem('ecom.customer', p.id);
    history.replaceState(null, '', '/create?project=' + p.id);
    $('work').hidden = false;
    if (!settingsDirty)
        setSettings();
    paintMedia();
    if (changedProduct) {
        scriptDirty = false;
        paintFacts();
        paintScript();
    }
    paintDirections();
    paintAlignment();
    paintShots();
    paintResult();
    controls();
}
async function listProjects() { const list = await api('/customer-projects'); $('projectSelect').replaceChildren(option('', '新建客户商品'), ...list.map(x => option(x.id, x.title))); if (p)
    $('projectSelect').value = p.id; }
async function loadProject(id) { clearTimeout(timer); adopt(await api('/customer-projects/' + id), { reset: true }); await listProjects(); message('项目已载入。资料、素材与已保存分镜已恢复。');
    if (p.recommendations) void showPreviews();
    if (p.job && !p.inputs_changed && p.job.status === 'draft' && !p.alignment) await autoAlign();
}
function sourceLink(source, locator) { const a = node('a', `${source?.file_name || '资料'} / ${locator}`); a.href = `/api/products/${p.id}/sources/${source.id}`; a.target = '_blank'; a.rel = 'noopener'; return a; }
function paintMedia() {
    $('sourceList').replaceChildren();
    for (const s of p.product.sources) {
        const row = node('p');
        row.append(sourceLink(s, `${s.extracted.units.length} 条原文`));
        $('sourceList').append(row);
    }
    $('mediaList').replaceChildren();
    for (const original of p.media) {
        const a = { ...original, ...mediaEdits.get(original.id) };
        const card = node('article'), media = node(a.kind === 'image' ? 'img' : a.kind === 'video' ? 'video' : 'audio');
        media.src = `/api/customer-projects/${p.id}/assets/${a.id}`;
        if (a.kind === 'image')
            media.alt = a.name;
        else {
            media.controls = true;
            media.preload = 'metadata';
        }
        card.append(media, node('strong', a.name));
        const role = node('select');
        for (const [value, title] of Object.entries(roles))
            if ((a.kind === 'audio') === (value === 'voice' || value === 'music'))
                role.append(option(value, title));
        role.value = a.role;
        role.setAttribute('aria-label', a.name + ' 用途');
        card.append(role);
        const start = node('input');
        start.type = 'number';
        start.min = '0';
        start.step = '.033';
        start.value = a.source_in;
        start.disabled = a.kind !== 'video';
        start.setAttribute('aria-label', a.name + ' 素材入点');
        if (a.kind === 'video') {
            const label = node('label', `使用入点（总长 ${a.metadata.duration.toFixed(2)} 秒）`);
            label.append(start);
            card.append(label);
        }
        const note = node('input');
        note.value = a.note;
        note.maxLength = 500;
        note.placeholder = '内容或测试来源说明';
        note.setAttribute('aria-label', a.name + ' 来源说明');
        card.append(note);
        for (const input of [role, start, note])
            input.oninput = () => mediaEdits.set(a.id, { role: role.value, source_in: Number(start.value), note: note.value });
        const save = node('button', '保存用途', 'secondary');
        save.type = 'button';
        save.onclick = () => run(async () => { const next = await api(base() + '/assets/' + a.id, { method: 'PUT', body: JSON.stringify({ revision: p.revision, role: role.value, source_in: Number(start.value), note: note.value }) }); mediaEdits.delete(a.id); adopt(next); message('素材用途已保存。已有成片保留；新分镜按更新后的素材准备。'); });
        const remove = node('button', '移除', 'secondary');
        remove.type = 'button';
        remove.onclick = () => run(async () => { const next = await api(base() + '/assets/' + a.id, { method: 'DELETE', body: JSON.stringify({ revision: p.revision }) }); mediaEdits.delete(a.id); adopt(next); message('已从项目素材库移除，历史成片的素材快照仍保留。'); });
        card.append(save, remove);
        paintContentAnalysis(a,card);
        $('mediaList').append(card);
    }
}
function paintFacts() {
    $('facts').replaceChildren();
    const review = p.product.fact_reviews.find(r => r.id === p.product.current_review_id), checked = new Set(review?.fact_ids || []);
    for (const f of p.product.facts) {
        const label = node('label', undefined, 'check'), box = node('input');
        box.type = 'checkbox';
        box.value = f.id;
        box.checked = checked.has(f.id);
        box.className = 'fact-choice';
        const text = node('span', f.text);
        text.append(sourceLink(p.product.sources.find(s => s.id === f.source_id), f.locator));
        label.append(box, text);
        $('facts').append(label);
    }
    if (!p.product.facts.length)
        $('facts').append(node('p', '上传产品资料后，这里会显示可核对的原文事实。长段原文可在原分镜工作台摘录。'));
    $('factsChecked').checked = false;
}
function currentDraft() { return p.product.script_drafts.find(d => d.id === p.product.current_draft_id); }
function paintScript() { if(scriptAlternatives && scriptAlternatives.revision!==p.product.revision){scriptAlternatives=null;$('scriptAlternatives').replaceChildren();} const draft = currentDraft(); scenes = (draft?.payload || []).map(s => ({ text: s.text, fact_ids: [...s.fact_ids] })); $('scriptPanel').hidden = !p.product.current_review_id; renderScenes(); $('scriptChecked').checked = false; const approval = p.product.script_approvals.find(a => a.draft_id === draft?.id); $('approvedHint').textContent = approval ? `当前文稿已由 ${approval.reviewer} 确认。修改后需要再次确认。` : ''; $('prepare').disabled = !approval; }
function renderScenes() {
    $('scriptScenes').replaceChildren();
    const review = p.product.fact_reviews.find(r => r.id === p.product.current_review_id);
    const facts = p.product.facts.filter(f => review?.fact_ids.includes(f.id));
    scenes.forEach((s, i) => { const row = node('div', undefined, 'customer-script-row'), label = node('label', `第 ${i + 1} 句`), text = node('textarea'); text.rows = 2; text.maxLength = 100; text.value = s.text; text.setAttribute('aria-label', `第 ${i + 1} 句文稿`); label.append(text); const refsLabel = node('label', '事实来源（可多选）'), refs = node('select'); refs.multiple = true; refs.size = Math.min(4, Math.max(2, facts.length)); refs.setAttribute('aria-label', `第 ${i + 1} 句事实来源`); for (const f of facts) {
        const opt = option(f.id, f.text);
        opt.selected = s.fact_ids.includes(f.id);
        refs.append(opt);
    } refsLabel.append(refs); row.append(label, refsLabel); const annotation=currentDraft()?.payload?.[i]; if(!scriptDirty && annotation?.visual_hint) row.append(node('small', '原稿镜头目的：'+({hook:'开场',appearance:'整体外观',detail:'细节',action:'操作动作',evidence:'依据展示',closing:'收尾'}[annotation.intent]||'待核对')+' · '+annotation.visual_hint)); text.oninput = () => { s.text = text.value; scriptDirty = true; $('scriptChecked').checked = false; }; refs.onchange = () => { s.fact_ids = Array.from(refs.selectedOptions, x => x.value); scriptDirty = true; $('scriptChecked').checked = false; }; $('scriptScenes').append(row); });
    paintWorkspace();
}
function paintDirections() {
    $('promptMatches').replaceChildren();
    $('directions').replaceChildren();
    const rec = p.recommendations;
    if (!rec) {
        $('styleState').textContent = '确认文稿与素材后自动推荐';
        $('makeBoard').disabled = true;
        $('previewStyles').hidden = true;
        $('selectionHint').textContent = '';
        $('previewState').textContent = '';
        return;
    }
    const planned = !!p.job?.storyboard && !p.inputs_changed;
    if (planned) selected = p.job.storyboard.creative?.style_id || selected;
    for (const s of rec.options) {
        const optionCard=node('article',undefined,'direction-option'), extra=node('details',undefined,'direction-details');
        extra.append(node('summary','查看编排与素材依据'));
        const card = node('button', undefined, 'direction');
        card.type = 'button';
        card.dataset.style = s.id;
        card.setAttribute('aria-pressed', String(selected === s.id));
        card.disabled = planned || active();
        if (previews[s.id]) {
            const im = node('img');
            im.src = previews[s.id];
            im.alt = s.name + ' · 当前商品风格帧';
            card.append(im);
        } else card.append(node('span','风格帧准备后显示当前商品','direction-placeholder'));
        card.append(node('span',selected===s.id?'✓ 已选方向':planned?'本版未采用':'选择此方向','direction-choice-state'));
        card.append(node('strong', s.name), node('p', s.description), node('small', s.reason));
        if (s.voice) card.append(node('p', `配音建议：${s.voice.name} · 语速 ${s.voice.speech_rate > 0 ? '+' : ''}${s.voice.speech_rate}`));
        if (s.motion) extra.append(node('p', '镜头组合：' + s.motion.description));
        if (s.prompt_direction) { const c=s.prompt_direction.cards[0]; extra.append(node('p','主画面：'+c.name),node('small','关键词：'+Object.entries(c.matched_inputs).filter(([,v])=>v.length).map(([k,v])=>k+' '+v.join('、')).join('；'))); }
        if (s.production) {
            extra.append(node('p', '完整编排：' + s.production.structure), node('p', '实拍安排：' + s.production.footage), node('p', '声音与画面节奏：' + s.production.rhythm), node('small', s.production.finish || ''), node('p', s.production.treatment?.summary || ''));
            extra.append(node('small', '已上传配音保留原声与时长；合成语气/语速需先试听。自动选段需开启并完成本机识别；素材不足会提示，不用无关画面凑齐。'));
        }
        if (s.material_fit) { const f=s.material_fit; card.append(node('p','素材适配：'+({needs_material:'需要补素材',unknown:'尚不能判断',possible_with_review:'有候选，待回看'}[f.status]||f.status)+' · 可候选 '+f.can_do.length+' 句 · 缺口 '+f.gap_count+' · 未知 '+f.unknown_count),node('small',f.note)); if(f.style_gap)extra.append(node('small',f.style_gap.message,'customer-warning')); for(const m of f.missing.slice(0,3))extra.append(node('small','第'+m.line+'句：'+m.message,'customer-warning')); }
        if (s.missing?.length) card.append(node('small', s.missing.join('；'), 'customer-warning'));
        card.onclick = () => { selected = s.id; localStorage.setItem('ecom.direction.'+p.id, JSON.stringify({basis:p.direction_basis, style:selected})); paintDirections(); paintVolcVoice(); };
        optionCard.append(card,extra);
        $('directions').append(optionCard);
    }
    $('styleState').textContent = planned ? '已保存风格；可在分镜中微调' : rec.version === 2 ? '已按商品、气质与人群推荐三个方向' : '补充气质与目标人群，获得更具体的三个方案';
    const blockers = p.preparation_blockers || [];
    const readyJob = !!p.job && !p.inputs_changed;
    const audioReady = p.settings.brief.format === 'showcase' || ['needs_review','confirmed'].includes(p.alignment?.status);
    $('makeBoard').disabled = planned || !selected || active() || !readyJob || blockers.length > 0 || !audioReady;
    paintPromptMatches(rec.options.find(s=>s.id===selected));
    $('previewStyles').hidden = false;
    const nextStep = planned ? '可在下方修改分镜。' : blockers.length ? '生成分镜前还需：'+blockers.join('；')+'。' : !readyJob ? '点击“使用已确认文稿，继续制作”准备素材。' : p.alignment?.status==='failed' ? '配音对齐未通过，请查看下方原因并修正文稿或配音。' : !audioReady ? '等待配音对齐；完成后逐句听核。' : p.alignment?.status==='needs_review' ? '请在下方听核配音，然后生成分镜。' : '可以生成分镜。';
    $('selectionHint').textContent = (selected ? '已选：'+rec.options.find(s=>s.id===selected)?.name+'。' : '请选择一个方向。') + nextStep + (settingsDirty ? ' 制作要求尚未保存，当前卡片仍是旧推荐；请先点击“保存制作要求”。' : '') + (rec.version === 2 ? ' 相同输入保持稳定；修改商品文稿、气质或人群并保存后会重新计算。' : '');
    paintWorkspace();
}
async function showPreviews() {
    if (!p?.recommendations || !p.media.some(a=>a.kind!=='audio')) return;
    const pid=p.id, key=pid+':'+p.recommendations.fingerprint;
    if (previewFlights.has(key)) return;
    if (Object.keys(previews).length===3) return;
    previewFlights.add(key);
    $('previewState').textContent='风格帧正在生成，可以先选择方向。';
    try {
        const urls=await post('/customer-projects/'+pid+'/direction-previews',{revision:p.revision});
        if (p?.id!==pid || key!==pid+':'+p.recommendations?.fingerprint) return;
        previews=urls; paintDirections(); $('previewState').textContent='三个风格帧已就绪；仅为视觉方向预览，分镜仍会按实际素材与配音生成。';
    } catch(e) {
        if (p?.id===pid && key===pid+':'+p.recommendations?.fingerprint) $('previewState').textContent='风格帧暂未生成：'+e.message+'。仍可选方向，或点击重试。';
    } finally { previewFlights.delete(key); }
}
function voiceAsset() { return p.job?.assets.find(a => a.metadata.customer_role === 'voice'); }
async function autoAlign() { if (p.settings.brief.format === 'showcase')
    return; const voice = voiceAsset(); if (!voice)
    return; const row = await post('/jobs/' + p.job.id + '/alignments', { asset_id: voice.id }); p.alignment = row; paintAlignment(); }
function paintAlignment() {
    const need = p.job && p.settings.brief.format !== 'showcase';
    $('alignmentPanel').hidden = !need;
    if (!need)
        return;
    const voice = voiceAsset();
    const url = voice ? `/api/jobs/${p.job.id}/assets/${voice.id}` : '';
    if ($('voicePlayer').getAttribute('src') !== url) {
        $('voicePlayer').pause(); stopAt = null; $('voicePlayer').src = url;
    }
    $('alignmentDetail').href = '/studio?job=' + p.job.id;
    const a = p.alignment;
    if (seenAlignment !== a?.id) {
        seenAlignment = a?.id || '';
        $('voiceChecked').checked = false;
        $('voiceReviewer').value = '';
    }
    $('alignmentState').textContent = !a ? '等待启动本机对齐' : a.status === 'running' ? '本机正在识别并尝试自动修复字级时间（最多两次）…' : a.status === 'failed' ? (a.result?.diagnostic?.code==='script_mismatch' ? '待核对：声音与当前确认稿不同，已查找原稿建议。' : '对齐失败：' + a.error) : a.status === 'confirmed' ? `已听核：${a.reviewer}。当前版本的配音时间已确认。` : '待听核：点击每句试听。低匹配与插值请核正，不能仅凭覆盖率通过。';
    const diagnosis = a?.result?.diagnostic || a?.result?.recovery?.original_diagnostic, panel = $('alignmentDiagnosis');
    const recovery = a?.result?.recovery;

    panel.replaceChildren(); panel.hidden = !diagnosis && !recovery;
    if(recovery) panel.append(node('strong','已生成待听核时间建议'),node('p',recovery.warning));
    if (diagnosis) {
        panel.append(node('strong', '配音与文稿对照'),
            node('p', `配音 ${diagnosis.duration.toFixed(2)} 秒 · 当前稿件锚点覆盖 ${Math.round(diagnosis.script_coverage*100)}%`),
            node('p', '识别内容（可能有错字，请试听）：' + (diagnosis.transcript || '未识别出人声')),
            node('p', '本次对齐文稿：' + diagnosis.script));
        for (const candidate of p.matching_script_drafts || []) {
            const draft = p.product.script_drafts.find(d=>d.id===candidate.draft_id);
            if (!draft || draft.id===p.product.current_draft_id) continue;
            const button = node('button', `载入匹配的历史文稿（${Math.round(candidate.score*100)}%）`, 'secondary');
            button.type='button'; button.dataset.draft=draft.id;
            button.onclick=()=>{
                if (scriptDirty && !confirm('替换当前未保存的文稿编辑？')) return;
                scenes=draft.payload.map(s=>({text:s.text,fact_ids:[...s.fact_ids]}));
                scriptDirty=true; $('scriptChecked').checked=false; renderScenes();
                $('scriptPanel').scrollIntoView({behavior:'smooth'});
                message('已载入历史原稿，尚未保存或确认。请核对两者一致和事实来源，然后确认文稿继续。');
            };
            panel.append(node('p', draft.payload.map(s=>s.text).join(' ')), button);
        }
        const best=(p.matching_script_drafts||[]).find(c=>c.score>=.9&&c.draft_id!==p.product.current_draft_id);
        if(best){
            const stamp=p.id+':'+a.id, draft=p.product.script_drafts.find(d=>d.id===best.draft_id);
            if(draft&&!stagedAlignmentDrafts.has(stamp)&&!dirty()){
                stagedAlignmentDrafts.add(stamp);scenes=draft.payload.map(s=>({text:s.text,fact_ids:[...s.fact_ids]}));scriptDirty=true;$('scriptChecked').checked=false;renderScenes();$('approvedHint').textContent='已自动载入匹配的原稿建议，尚未保存或确认；请核对后重新确认文稿。';
            }
            panel.append(node('p','已自动找回匹配的原稿建议。待确认编辑不会改写服务器已确认文稿；请到第二步核对后确认，才会创建新制作版本。'));
            const keep=node('button','保留当前确认稿，改换配音','secondary');keep.type='button';keep.onclick=()=>{scriptDirty=false;paintScript();paintVolcVoice();message('已保留当前确认稿。请选风格并明确合成对应配音，或上传正确音频。');};panel.append(keep);
        }
        panel.append(node('p','已自动尝试本机修复；内容确实不同仍需选择正确稿件或声音。不会自动改写事实、批准文稿或重复付费重合成。'));

    }
    $('retryAlignment').disabled = a?.status === 'running' || p.job.status !== 'draft';
    $('voiceChecked').disabled = $('voiceReviewer').disabled = a?.status !== 'needs_review';
    $('confirmListening').disabled = a?.status !== 'needs_review' || p.job.status !== 'draft' || p.inputs_changed;
    $('sentences').replaceChildren();
    for (const [i, s] of (a?.result?.sentences || []).entries()) {
        const row = node('div'), button = node('button', `${i + 1}. ${s.text} · 锚点覆盖 ${Math.round(s.match * 100)}%`);
        button.type = 'button';
        if (!s.ok)
            button.classList.add('uncertain');
        button.onclick = () => { const player = $('voicePlayer'); player.currentTime = s.start; stopAt = s.end; player.play().catch(e => message(e.message, true)); };
        row.append(button);
        if (a.status === 'needs_review') {
            const details = node('details'), summary = node('summary', '查看 / 校正字级时间');
            details.append(summary);
            const words = node('div', undefined, 'customer-word-times');
            for (const w of s.words) {
                const label = node('label', w.text + (w.anchored ? '' : ' · 插值'));
                for (const k of ['start', 'end']) {
                    const input = node('input');
                    input.type = 'number';
                    input.step = '.01';
                    input.min = '0';
                    input.value = w[k];
                    input.setAttribute('aria-label', `第${i + 1}句 ${w.text} ${k}`);
                    input.onchange = () => { w[k] = Number(input.value); $('voiceChecked').checked = false; };
                    label.append(input);
                }
                words.append(label);
            }
            details.append(words);
            row.append(details);
        }
        $('sentences').append(row);
    }
}
$('voicePlayer').ontimeupdate = () => { if (stopAt !== null && $('voicePlayer').currentTime >= stopAt) {
    $('voicePlayer').pause();
    stopAt = null;
} };
function field(row, label, value, kind, values, onChange) { const wrap = node('label', label); let input; if (kind === 'select') {
    input = node('select');
    for (const [v, t] of values)
        input.append(option(v, t));
}
else {
    input = node('input');
    input.type = kind;
    input.maxLength = 8;
    if (kind === 'number') {
        input.step = '.033';
        input.min = '0';
    }
} input.value = value; input.setAttribute('aria-label', label); input.onchange = () => onChange(kind === 'number' ? Number(input.value) : input.value); wrap.append(input); row.append(wrap); return input; }
function promptRecipe(currentRecipe,pendingRecipe,card){
 const actual=pendingRecipe??currentRecipe;
 return card?card.recipe:['media-punch-in','detail-dual-window','product-shape-reveal'].includes(actual)?'none':actual;
}
function paintShots() {
    $('shotList').replaceChildren();
    const job = p.job, b = job?.storyboard;
    if (!b)
        return;
    const editable = job.status === 'draft', locked = active();
    b.shots.forEach((shot, i) => {
        const changes = shotEdits.get(shot.shot_id) || {}, current = { ...shot, ...changes }, row = node('article', undefined, 'customer-shot');
        row.append(node('h3', `第 ${i + 1} 镜 · ${shot.duration.toFixed(2)} 秒`));
        const view = node('div', undefined, 'shot-preview'), asset = (editable?job.assets.find(a=>a.id===current.asset_id):(changes.media_id?p.media.find(a=>a.id===changes.media_id):null))||job.assets.find(a=>a.id===shot.asset_id), media = node(asset.kind === 'image' ? 'img' : 'video');
        media.src = !editable&&changes.media_id?`/api/customer-projects/${p.id}/assets/${asset.id}`:`/api/jobs/${job.id}/assets/${asset.id}`;
        if (asset.kind === 'image')
            media.alt = asset.name;
        else {
            media.controls = true;
            media.preload = 'metadata';
            media.onloadedmetadata = () => { media.currentTime = current.source_in; };
        }
        view.append(media, node('p', job.script.split('\n')[i]));
        row.append(view);
        const sentence = p.alignment?.result?.sentences?.[i];
        if (sentence && job.assets.some(a => a.role === 'voice' || a.metadata?.customer_role === 'voice')) {
            const listen = node('button', '试听此镜当前版本配音', 'secondary'); listen.type = 'button';
            listen.onclick = () => { const player = $('voicePlayer'); player.currentTime = sentence.start; stopAt = sentence.end; player.play().catch(e => message(e.message, true)); };
            row.append(listen);
        }
        const form = node('fieldset'), grid = node('div', undefined, 'customer-grid');
        form.disabled = locked;
        const mark = (k, v) => { shotEdits.set(shot.shot_id, { ...(shotEdits.get(shot.shot_id) || {}), [k]: v }); };
        const clearVisualGuards = () => { const mp=(shotEdits.get(shot.shot_id)||{}).motion_plan||current.motion_plan; if(mp)mark('motion_plan',{...mp,windows:(mp.windows||[]).filter(w=>w.basis==='voice_hint')}); };
        const choices = editable ? job.assets.filter(a => a.kind !== 'audio').map(a => [a.id, a.name]) : p.media.filter(a => a.kind !== 'audio').map(a => [a.id, a.name]);
        const mediaKey = editable ? 'asset_id' : 'media_id', value = changes[mediaKey] || (editable ? shot.asset_id : asset.metadata.library_id || '');
        const select = field(grid, `第 ${i + 1} 镜画面`, value, 'select', choices, v => { mark(mediaKey, v); const a = editable ? job.assets.find(a => a.id === v) : p.media.find(a => a.id === v); if (a) {
            mark('motion', a.kind === 'video' ? 'static' : 'push');
            if (a.kind !== 'video') mark('source_framing', 'original');
            mark('source_in', editable ? (a.metadata.source_in || 0) : a.source_in);
            clearVisualGuards();
            paintShots();
        } });
        if (!choices.some(([v]) => v === value)) {
            select.prepend(option('', '保留当前画面'));
            select.value = '';
        }
        field(grid, `第 ${i + 1} 镜素材入点`, current.source_in, 'number', null, v => {mark('source_in', v);clearVisualGuards();});
        field(grid, `第 ${i + 1} 镜字卡`, current.headline, 'text', null, v => mark('headline', v));
        const direction = p.recommendations?.options?.find(s=>s.id===b.creative?.style_id) || p.recommendations?.options?.[0];
        const recipes = direction?.motion?.choices || [];
        if (recipes.length) {
            const detail = node('details'), summary = node('summary', '查看本镜配方说明与 Prompt 来源'), hint = node('p'), source = node('a', '查看上游镜头卡');
            source.target = '_blank'; source.rel = 'noopener noreferrer';
            const explain = id => { const r = recipes.find(r => r.id === id); hint.textContent = r?.prompt || '保留旧版本镜头编排。'; source.hidden = !r?.source_url; if (r?.source_url) source.href = r.source_url; };
            field(grid, `第 ${i + 1} 镜动效配方`, current.shot_recipe || '', 'select', [['', '保留历史编排'], ...recipes.map(r => [r.id, r.name])], v => { mark('shot_recipe', v || null); markMotion('prompt_card',null); if (!v) mark('motion_plan', null); explain(v);paintShots(); });
            explain(current.shot_recipe); detail.append(summary, hint, source); form.append(detail);
        }
        const motionPlan = {version:2, strength:'balanced', cue_offset:0, protect_action:true, windows:[], repeat_limit:p.settings.motion_repeat_limit||2, intent:'auto', ...(current.motion_plan||{})};
        const markMotion = (key,value) => { const edits=shotEdits.get(shot.shot_id)||{}; mark('motion_plan',{...motionPlan,...(edits.motion_plan||{}),[key]:value}); if (!(edits.shot_recipe ?? current.shot_recipe)) mark('shot_recipe','none'); };
        const promptChoices=direction?.prompt_direction?.choices || [];
        field(grid, `第 ${i + 1} 镜商品画面 Prompt`,motionPlan.prompt_card||'','select',[['','保留基础编排'],...promptChoices.map(c=>[c.id,c.name])],v=>{const c=promptChoices.find(c=>c.id===v);mark('shot_recipe',promptRecipe(current.shot_recipe,shotEdits.get(shot.shot_id)?.shot_recipe,c));markMotion('prompt_card',v||null);paintShots();});
        field(grid, `第 ${i + 1} 镜画面精修`, motionPlan.visual_finish || 'legacy', 'select', [['legacy','保留原版'],['polished-v1','标题精排 · 人声关键词轻强调']], v=>markMotion('visual_finish',v));
        field(grid, `第 ${i + 1} 镜动效强度`, motionPlan.strength, 'select', [['subtle','克制'],['balanced','适中'],['bold','利落']], v=>markMotion('strength',v));
        const delay=field(grid, `第 ${i + 1} 镜动效偏移秒数`, motionPlan.cue_offset,'number',null,v=>markMotion('cue_offset',v)); delay.min='-.5';delay.max='1';delay.step='any';
        field(grid, `第 ${i + 1} 镜动作避让`, String(motionPlan.protect_action),'select',[['true','避让保护区间'],['false','关闭避让']],v=>markMotion('protect_action',v==='true'));
        const guardLabel=node('label',`第 ${i + 1} 镜保护区间（本镜秒数）`), ranges=node('input'); ranges.type='text';ranges.maxLength=200;ranges.placeholder='例如 0.20-1.50; 2.10-2.80';ranges.value=motionPlan.windows.map(w=>w.start.toFixed(2)+'-'+w.end.toFixed(2)).join('; ');ranges.setAttribute('aria-label',`第 ${i + 1} 镜保护区间`);
        ranges.onchange=()=>{try{const windows=ranges.value.trim()?ranges.value.split(';').map(part=>{const m=part.trim().match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);if(!m)throw Error('保护区间请用 起点-终点; 起点-终点');const start=Number(m[1]),end=Number(m[2]);if(start>=end||end>shot.duration+.001)throw Error('保护区间须在本镜时长内，结束晚于开始');return {start,end,basis:'manual'};}):[];if(windows.length>8)throw Error('每镜最多8个保护区间');ranges.setCustomValidity('');markMotion('windows',windows);}catch(e){ranges.setCustomValidity(e.message);ranges.reportValidity();message(e.message,true);}};
        guardLabel.append(ranges);grid.append(guardLabel);
        form.append(node('small', motionPlan.windows.length ? `动作区间来源：${[...new Set(motionPlan.windows.map(w=>({manual:'手动标记',analysis:'本机分析建议（待核对）',voice_hint:'口播词提示（未核验实拍）'}[w.basis]||'待核对')))].join('、')}。` : '尚无动作保护区间。可手动填写；开启动作对齐可使用本机分析建议，仍须播放核对。'));
        for (const [key, label, values] of [['motion', '运镜', [['static', '固定 / 保留实拍'], ['push', '缓慢推近'], ['pull', '缓慢拉远'], ['pan_left', '向左移动'], ['pan_right', '向右移动']]], ['fit', '画幅', [['contain', '完整显示'], ['cover', '铺满画面']]], ['treatment', '编排', [['hero', '开场露出'], ['macro', '细节聚焦'], ['split', '双窗观察'], ['context', '场景展开'], ['footage', '实拍全画幅'], ['end', '收尾停留'], ['auto', '自动']]], ['transition', '转场', [['cut', '直接切接'], ['wipe', '遮罩擦拭'], ['iris', '开幕露出'], ['push-stack', '底边推叠（品牌底色衔接）'], ['line-carry', '线条接力'], ['media-pass', '媒体前景交接']]]]) {
            const input = field(grid, `第 ${i + 1} 镜${label}`, current[key], 'select', values, v => mark(key, v));
            if (key === 'transition' && !editable) {
                input.disabled = true;
                input.title = '成片单镜修订保留转场，避免影响相邻镜头；转场可在未提交分镜中修改。';
            }
        }
        if (asset.kind === 'video') field(grid, `第 ${i + 1} 镜源视频取景`, current.source_framing || 'original', 'select', [['original','保留原画幅'],['square','方形取景 · 裁两侧或上下']], v => mark('source_framing', v));
        form.append(node('small', '横屏实拍在竖屏中可能偏小。方形取景会裁掉部分源画面，使用下方焦点调整；源素材预览仍显示原片，请生成新版后核对商品、双手和动作全过程。不会自动通过审核。'));
        for (const key of ['focus_x', 'focus_y']) {
            const input = field(grid, `第 ${i + 1} 镜${key === 'focus_x' ? '水平' : '垂直'}焦点`, current[key], 'number', null, v => mark(key, v));
            input.step = '.05';
            input.max = '1';
        }
        form.append(grid, node('small', '字卡最多8字，须摘自本镜已确认文稿；配方只改变呈现，字幕仍跟随原配音。细节框使用下方焦点，须人工核对；选择“静止留看”可关闭额外动效。成片单镜修订保留原转场与其他镜头。'));
        const button = node('button', editable ? '保存这一镜' : '仅修改此镜并生成新版');
        button.type = 'button';
        button.onclick = () => { if ([ranges, delay].every(input => input.reportValidity())) run(() => saveShot(shot.shot_id)); };
        form.append(button);
        row.append(form);
        candidatePicker(row,shot,i,editable,locked);
        paintShotVoice(row,shot,i);
        $('shotList').append(row);
    });
}
async function saveShot(id) {
    const changes = shotEdits.get(id);
    if (!changes || !Object.keys(changes).length)
        throw Error('请先修改这一镜的参数');
    if (settingsDirty || scriptDirty || mediaEdits.size)
        throw Error('请先保存制作要求、素材用途或文稿，再修改镜头');
    if (p.job.status === 'draft') {
        const b = structuredClone(p.job.storyboard), shot = b.shots.find(s => s.shot_id === id);
        Object.assign(shot, changes);
        if (changes.asset_id) {
            const a = p.job.assets.find(a => a.id === changes.asset_id);
            shot.role = a.metadata.customer_role || 'product';
            shot.evidence_note = a.metadata.evidence_note || '';
        }
        await api('/jobs/' + p.job.id + '/storyboard', { method: 'PUT', body: JSON.stringify({ revision: p.job.storyboard_revision, board: b }) });
        shotEdits.delete(id);
        adopt(await api(base()));
        message('这一镜已保存。其他镜头未改动。');
    }
    else {
        const payload = { ...version(), shot_id: id, request_id: crypto.randomUUID(), changes };
        const next = await post(base() + '/revise-shot', payload);
        shotEdits.delete(id);
        adopt(next);
        adopt(await post(base() + '/submit', version()));
        message('已创建只修改此镜的新版本，正在生成；原版保留。');
    }
}
function paintResult() {
    paintWorkspace();
    const job = p.job;
    $('projectState').textContent = p.product.title + ' · 修订 ' + p.revision;
    $('jobState').textContent = job ? statuses[job.status] || job.status : '等待选定风格';
    $('inputChanged').hidden = !p.inputs_changed;
    $('render').disabled = !job?.storyboard || job.status !== 'draft' || p.inputs_changed || !!p.iteration?.style_confirm_needed || (p.settings.brief.format !== 'showcase' && p.alignment?.status !== 'confirmed');
    $('cancelRender').hidden = !active();
    $('retryRender').hidden = job?.status !== 'failed';
    $('advanced').href = job ? '/?job=' + job.id : '/';
    $('planningNotes').replaceChildren(node('p', '以下为初次自动安排依据；人工修改后以当前镜头参数为准，动作同步需重新预览。'), ...p.planning_notes.map(t => node('p', t)));
    $('renderMessage').textContent = job?.error || (job ? `当前：${statuses[job.status] || job.status}。只修改画面可用各镜下方的按钮；修改稿件或声音请回到上方重新确认。` : '选定方向后生成分镜。');
    const artifact = job?.artifacts.find(a => a.kind === 'video');
    $('film').hidden = !artifact;
    if (artifact) {
        const src = `/api/jobs/${job.id}/artifacts/video`;
        if ($('film').getAttribute('src') !== src)
            $('film').src = src;
    }
    else
        $('film').removeAttribute('src');
    $('downloads').replaceChildren();
    if (artifact)
        for (const [kind, label] of [['video', '下载成片'], ['video_clean', '无背景音乐版'], ['shotbook', '分镜记录'], ['subtitles', '字幕 SRT'], ['audit', '综合审核 JSON'], ['audit_html', '综合审核 HTML']]) {
            if (!job.artifacts.some(a => a.kind === kind))
                continue;
            const a = node('a', label);
            a.href = `/api/jobs/${job.id}/artifacts/${kind}?download=true`;
            $('downloads').append(a);
        }
    paintCombinedAudit(job);
    $('reviewPanel').hidden = !job || job.status !== 'needs_review';
    $('versions').replaceChildren(node('h3', '已保存的制作版本'));
    for (const v of p.versions) {
        const a = node('a', `${new Date(v.created_at * 1000).toLocaleString('zh-CN')} · ${statuses[v.status] || v.status}`);
        a.href = '/?job=' + v.id;
        a.target = '_blank';
        a.rel = 'noopener';
        $('versions').append(a);
    }
}
function schedule() { clearTimeout(timer); if (!p || !(active() || p.alignment?.status === 'running' || analysisPending()))
    return; const pid = p.id, jid = p.job?.id; timer = setTimeout(async () => { if (busy) {
    schedule();
    return;
} try {
    const next = await api('/customer-projects/' + pid);
    if (p?.id !== pid || p.job?.id !== jid)
        return;
    const status = p.job?.status, alignmentStatus = p.alignment?.status, mediaStamp=analysisStamp(p);
    p = next;
    if(mediaStamp!==analysisStamp(p)) { clearMaterialReport(); paintMedia(); paintDirections(); }
    if (alignmentStatus !== p.alignment?.status) { paintAlignment(); paintDirections(); }
    paintResult();
    if (status !== p.job?.status) {
        paintShots();
        if (p.job?.status === 'needs_review')
            message('成片已生成，请完整观看后审核；也可只修改不满意的镜头。');
        else if (['failed', 'blocked'].includes(p.job?.status))
            message(p.job.error || '生成未完成，请查看下方原因。', true);
    }
}
catch (e) {
    message('状态读取失败：' + e.message, true);
} schedule(); }, 1500); }
async function prepareFlow() { if (settingsDirty || mediaEdits.size)
    throw Error('请先保存制作要求与素材用途'); if (scriptDirty)
    throw Error('请先确认修改后的文稿'); adopt(await post(base() + '/prepare', { revision: p.revision })); await autoStart(); }
async function autoStart() { if (p.job.status !== 'draft' || p.inputs_changed)
    return; if (!p.alignment && p.settings.brief.format !== 'showcase') {
    try {
        await autoAlign();
    }
    catch (e) {
        message('配音对齐尚未开始：' + e.message, true);
    }
} void showPreviews(); }
$('createProject').onclick = () => run(async () => { if (dirty() && !confirm('有未保存修改，继续新建项目？'))
    return; const next = await post('/customer-projects', { title: $('newTitle').value, settings: { material_checks:true, auto_select:true, reference_only:true, strict_product:true, action_timing:true, brief: { format: 'narrated' } } }); adopt(next, { reset: true }); await listProjects(); message('项目已创建。上传产品资料、商品画面和配音。'); });
$('projectSelect').onchange = () => run(async () => { const id = $('projectSelect').value; if (!id) {
    $('projectSelect').value = p?.id || '';
    return;
} if (dirty() && !confirm('切换会放弃未保存的编辑，继续？')) {
    $('projectSelect').value = p.id;
    return;
} await loadProject(id); });
for (const id of ['format', 'brandName', 'category', 'audience', 'tone', 'motionRepeatLimit', 'reviewContext', 'autoSelect', 'referenceOnly', 'strictProduct', 'actionTiming', 'materialChecks', 'productReference'])
    $(id).oninput = () => { settingsDirty = true; paintDirections(); paintVolcVoice(); };
$('saveSettings').onclick = () => run(async () => { const next = await api(base(), { method: 'PUT', body: JSON.stringify({ revision: p.revision, settings: settings() }) }); settingsDirty = false; adopt(next); await enqueueMissingAnalysis(); message('制作要求已保存。需要新版本时，使用已确认文稿继续制作。'); });
async function uploads(input, role) { const files = Array.from(input.files || []); input.value = ''; for (const file of files) {
    message('正在保存：' + file.name);
    const data = new FormData();
    data.append('revision', p.revision);
    data.append('role', role);
    data.append('file', file);
    adopt(await api(base() + '/assets', { method: 'POST', body: data }));
} await enqueueMissingAnalysis(); message('素材已保存。自动模式会识别画面内容；也可手动标记用途和入点。'); }
$('visuals').onchange = () => run(() => uploads($('visuals'), 'product'));
$('voiceUpload').onchange = () => run(() => uploads($('voiceUpload'), 'voice'));
$('musicUpload').onchange = () => run(() => uploads($('musicUpload'), 'music'));
$('documents').onchange = () => run(async () => { if (scriptDirty)
    throw Error('先保存或确认当前文稿，再上传新的产品资料'); const files = Array.from($('documents').files); $('documents').value = ''; for (const file of files) {
    const data = new FormData();
    data.append('revision', p.product.revision);
    data.append('file', file);
    await api(productBase() + '/documents', { method: 'POST', body: data });
    adopt(await api(base()));
} message('原文已归档，请选择并核实事实。'); });
$('confirmFacts').onclick = () => run(async () => {
    if (!$('factsChecked').checked) throw Error('请先核对原文并勾选事实确认');
    if (!$('factReviewer').value.trim() || !$('factNote').value.trim()) throw Error('请填写事实确认人和核对说明');
    const previous = scenes.map(s=>({text:s.text,fact_ids:[...s.fact_ids]}));
    const fact_ids = Array.from(document.querySelectorAll('.fact-choice:checked'), x=>x.value);
    const prod = await post(productBase()+'/facts/confirm', {revision:p.product.revision,fact_ids,reviewer:$('factReviewer').value,note:$('factNote').value,confirmed:true});
    if (previous.length) {
        const preserved = previous.map(s=>({...s,fact_ids:s.fact_ids.filter(id=>fact_ids.includes(id))}));
        const missing = preserved.some((s,i)=>s.fact_ids.length!==previous[i].fact_ids.length);
        if (!missing) await post(productBase()+'/scripts', {revision:prod.revision,scenes:preserved});
        adopt(await api(base()));
        if (missing) { scenes=preserved; scriptDirty=true; renderScenes(); }
        message(missing ? '事实已更新，原文稿已保留在编辑区。请为失效引用重新选择来源并确认文稿。' : '事实已确认，保留原文稿为待确认版本，避免替换已有配音的原稿。请重新核对文稿。');
    } else {
        await post(productBase()+'/scripts/generate', {revision:prod.revision,mode:'directed',brief:p.settings.brief});
        adopt(await api(base()));
        message('已根据确认事实编排建议文稿。已有配音时，请使用对应稿件并核对来源。');
    }
});
$('scriptUpload').onchange = () => run(async () => { const f = $('scriptUpload').files[0]; if (!f)
    return; if (f.size > 16000)
    throw Error('口播稿过长，请提供120秒以内的文本'); $('scriptPaste').value = await f.text(); $('scriptUpload').value = ''; message('口播稿已读取，点击按行替换后核对每句事实来源。'); });
$('applyScript').onclick = () => { const lines = $('scriptPaste').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean); if (!lines.length || lines.length > 30 || lines.some(s => s.length > 100)) {
    message('文稿须1–30行，每行不超过100字。', true);
    return;
} const review = p.product.fact_reviews.find(r => r.id === p.product.current_review_id); scenes = lines.map(text => ({ text, fact_ids: p.product.facts.filter(f => review?.fact_ids.includes(f.id) && text.includes(f.text)).map(f => f.id) })); scriptDirty = true; $('scriptChecked').checked = false; renderScenes(); message('已替换待确认文稿；未匹配的句子请手动选择事实来源。'); };
$('approveScript').onclick = () => run(async () => { if (!$('scriptChecked').checked)
    throw Error('请逐句核对文稿与来源后确认'); if (!$('scriptReviewer').value.trim())
    throw Error('请填写文稿确认人'); if (!$('scriptNote').value.trim()) throw Error('请填写文稿核对说明，例如核对了哪份资料、哪些措辞'); let prod = p.product; if (scriptDirty || !currentDraft()) {
    await post(productBase() + '/scripts', { revision: prod.revision, scenes });
    scriptDirty = false;
    adopt(await api(base()));
    prod = p.product;
} await post(productBase() + '/scripts/confirm', { revision: prod.revision, draft_id: prod.current_draft_id, reviewer: $('scriptReviewer').value, note: $('scriptNote').value, confirmed: true, seconds: 3 }); scriptDirty = false; adopt(await api(base())); void showPreviews(); $('directions').scrollIntoView({behavior:'smooth'}); if (p.preparation_blockers.length) { message('文稿已确认，三个风格已推荐。可先选择方向；'+p.preparation_blockers.join('；')+'。'); return; } await prepareFlow(); });
$('prepare').onclick = () => run(prepareFlow);
$('previewStyles').onclick = () => { previews={}; void showPreviews(); };
$('retryAlignment').onclick = () => run(autoAlign);
async function confirmListening() {
    if (settingsDirty || scriptDirty || mediaEdits.size || p.inputs_changed)
        throw Error('请先保存制作要求、素材用途并确认文稿');
    let a = p.alignment;
    if (p.settings.brief.format === 'showcase' || a?.status === 'confirmed') return a;
    if (a?.status !== 'needs_review' || p.job.status !== 'draft')
        throw Error('请等待配音对齐完成；失败时可重新对齐');
    if (!$('voiceChecked').checked || !$('voiceReviewer').value.trim())
        throw Error('请先逐句听核并填写听核人');
    a = await post('/jobs/' + p.job.id + '/alignments/' + a.id + '/confirm', { confirmed: true, reviewer: $('voiceReviewer').value, result: { sentences: a.result.sentences.map(s => ({ words: s.words.map(w => ({ start: w.start, end: w.end })) })) } });
    p.alignment = a;
    return a;
}
$('confirmListening').onclick = () => run(async () => {
    await confirmListening();
    adopt(await api(base()));
    message('本版配音听核已保存。已有分镜可以继续制作；迭代新版还需确认当前风格。');
});
$('makeBoard').onclick = () => run(async () => { if (settingsDirty || scriptDirty || mediaEdits.size)
    throw Error('请先保存制作要求、素材用途并确认文稿'); if (!selected)
    throw Error('请选择一个风格'); const a = await confirmListening();
    adopt(await post(base() + '/plan', { ...version(), style_id: selected, fingerprint: p.recommendations.fingerprint, alignment_id: p.settings.brief.format === 'showcase' ? null : a.id })); message('已自动生成分镜。可以调整任意一镜，再生成成片。'); $('shotList').scrollIntoView({ behavior: 'smooth' }); });
$('render').onclick = () => run(async () => { if (dirty())
    throw Error('请先保存未完成的镜头、制作要求或文稿修改'); adopt(await post(base() + '/submit', version())); message('已进入生成队列。完成后可在这里播放、审核或只修改某一镜。'); });
$('cancelRender').onclick = () => run(async () => { await post('/jobs/' + p.job.id + '/cancel'); adopt(await api(base())); message('任务已取消，已有版本和素材保留。'); });
$('retryRender').onclick = () => run(async () => { await post('/jobs/' + p.job.id + '/retry'); adopt(await api(base())); message('已提交重试。'); });
$('acceptFilm').onclick = () => run(async () => { if (!$('filmChecked').checked)
    throw Error('请完成成片检查后确认'); await post('/jobs/' + p.job.id + '/review', { decision: 'ready', reviewer: $('filmReviewer').value, note: $('filmNote').value, confirmed: true }); $('filmChecked').checked = false; adopt(await api(base())); message('已记录人工审核通过，可下载交付；平台投放由客户操作。'); });
window.addEventListener('beforeunload', e => { if (dirty()) {
    e.preventDefault();
    e.returnValue = '';
} });
(async () => { try {
    token = (await api('/session')).token;
    await loadVolcVoiceStatus();
    await listProjects();
    const id = new URLSearchParams(location.search).get('project') || localStorage.getItem('ecom.customer');
    if (id)
        await run(() => loadProject(id));
    else
        message('新建一个客户商品项目，或继续已有项目。');
    controls();
}
catch (e) {
    message(e.message, true);
    controls();
} })();

$('generateDirected').onclick=()=>run(async()=>{
    if(settingsDirty || scriptDirty) throw Error('先保存制作要求并确认或保存当前文稿修改，再生成新版');
    await post(productBase()+'/scripts/generate',{revision:p.product.revision,mode:'directed',brief:p.settings.brief});
    adopt(await api(base()));
    message('新版文稿已生成，逐句镜头建议与事实来源在下方。原稿、原配音与成片保留；请重新确认本稿，配音需使用对应稿件。');
});
$('checkMaterials').onclick=()=>run(async()=>{
    if(dirty()) throw Error('先保存制作要求、文稿和素材修改，再检查已保存版本');
    const id=p.id, revision=p.revision, productRevision=p.product.revision;
    const result=await api(base()+'/preflight');
    if(p.id===id && p.revision===revision && p.product.revision===productRevision) paintMaterialReport(result);
});

function paintPromptMatches(direction){
 const box=$('promptMatches');if(!direction?.prompt_direction)return;
 if(!direction.selected_card)box.append(node('p','此项目保留原确认策略与旧镜头。修改商品、人群或气质并保存后可重新推荐新版三卡，仍需重新确认风格。'));
 box.append(node('h3','这个方向的 Prompt 与画面依据'),node('p',direction.prompt_direction.method),node('p','本机库共 '+direction.prompt_direction.choices.length+' 张版本化卡片；下方按商品与语气匹配三个画面候选，逐镜可以替换或关闭。'));

 for(const c of direction.prompt_direction.cards){
  const d=node('details'), summary=node('summary',(c.id===direction.selected_card?.id?'本方向自动选定：':'其他方向可改选：')+c.name+(c.status==='blocked'?' · 待补素材':' · 焦点与动作待核对'));d.append(summary,node('p',c.prompt));
  d.append(node('p','命中：'+Object.entries(c.matched_inputs).filter(([,v])=>v.length).map(([k,v])=>k+' '+v.join('、')).join('；')),node('p','要求：'+c.requirements.join('；')));
  if(c.product_adaptation)d.append(node('p','商品适配：'+c.product_adaptation.product+'；人群：'+c.product_adaptation.audience+'；气质：'+c.product_adaptation.tone),node('small','选择依据：'+Object.entries(c.score_breakdown).map(([k,v])=>k+' '+v).join(' / ')+'；分数不是效果预测'));
  if(c.missing.length)d.append(node('p',c.missing.join('；'),'customer-warning'));
  const a=node('a','参考方法与来源');a.href=c.source.url;a.target='_blank';a.rel='noopener noreferrer';d.append(a,node('small',' · '+c.source.license+' · '+c.source.commit.slice(0,12)));box.append(d);
 }
 if(direction.reference_matches?.length){const refs=node('details');refs.append(node('summary','从124张镜头卡检索的扩展参考（未适配不会执行）'));for(const c of direction.reference_matches){const p=node('p',c.id+' · '+c.adaptation_note+' · '+c.summary);const a=node('a','查看完整Prompt与150变体索引');a.href='/prompts?card='+encodeURIComponent(c.id);a.target='_blank';a.rel='noopener noreferrer';p.append(a);refs.append(p);}box.append(refs);}
 if(direction.prompt_direction.mix_policy)box.append(node('p','本方向按句组合多种卡片：细节→焦点括号，完整来源数据/销售→原文信息行，场景→媒体交接，动作→连续实拍；无依据或时长不足会降为留看并提示。'));
 box.append(node('p','选择方向后，按逐句内容、动作保护和素材清晰度匹配镜头；不是把网页 Prompt 原样交给模型执行。单镜 Prompt 可调整，所有听审关口保留。'));
}
// Optional chips append to existing free-text inputs; saved values use the existing contract.
for(const [id,tags]of [['audience',['通勤上班族','年轻学生','首次购买者','重视工艺的消费者']],['tone',['科技利落','活泼有节奏','温柔自然','精致克制','理性清楚']]]){
 const input=$(id);if(!input)continue;const group=node('div',undefined,'customer-keyword-tags');
 for(const tag of tags){const b=node('button',tag,'secondary');b.type='button';b.onclick=()=>{if(!input.value.includes(tag)){input.value=(input.value.trim()?input.value.trim()+'、':'')+tag;input.dispatchEvent(new Event('change',{bubbles:true}));}};group.append(b);}input.parentElement.append(group);
}

$('previewAlternatives').onclick=()=>run(async()=>{
 if(dirty())throw Error('先保存商品、人群、气质和文稿修改，再比较备选稿');
 const result=await post(productBase()+'/scripts/alternatives',{revision:p.product.revision,brief:p.settings.brief});
 scriptAlternatives=result;
 const box=$('scriptAlternatives');box.replaceChildren(node('p',result.method));
 for(const candidate of result.candidates){
  const d=node('details');d.append(node('summary',candidate.name+' · '+candidate.payload.length+'句 · 待确认'));
  const list=node('ol');candidate.payload.forEach((row,i)=>{
   const li=node('li',row.text),plan=candidate.shot_strategies[i];
   const sources=row.fact_ids.map(id=>p.product.facts.find(f=>f.id===id)?.locator||id).join('、');
   li.append(node('small',' 来源：'+(sources||'中性引导语')+'；展示：'+plan.explanation));
   if(plan.missing?.length)li.append(node('small',plan.missing.join('；'),'customer-warning'));
   list.append(li);
  });d.append(list);
  if(candidate.material_fit){const f=candidate.material_fit;d.append(node('p','现有素材：候选 '+f.can_do.length+'句，缺口 '+f.gap_count+'句，未知 '+f.unknown_count+'句；镜长暂估，听核后重检。'));for(const m of f.missing)d.append(node('small','第'+m.line+'句：'+m.message,'customer-warning'));}
  const use=node('button','采用这份备选，创建待确认稿');use.type='button';
  use.onclick=()=>run(async()=>{
   if(dirty()||active())throw Error('先保存修改并等待当前制作结束，再采用备选稿');
   if(scriptAlternatives!==result || p.product.revision!==result.revision)throw Error('资料已变化，请重新比较备选稿');
   await post(productBase()+'/scripts/alternatives/adopt',{revision:result.revision,brief:p.settings.brief,basis:result.basis,candidate_id:candidate.id});
   scriptAlternatives=null;box.replaceChildren();adopt(await api(base()));
   message('已创建待确认新稿。请核对事实与文稿，选定风格后重新准备对应配音和听核；旧版保留。');
  });d.append(use);box.append(d);
 }
 message('三份备选稿已生成供比较；当前确认稿与配音没有替换。');
});
