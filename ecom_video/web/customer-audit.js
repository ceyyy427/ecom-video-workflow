'use strict';
function clearMaterialReport() {
    $('materialReadiness').replaceChildren(node('p','尚未检查或输入已变化。请重新检查当前已保存文稿。'));
}
function paintMaterialReport(report) {
    const box=$('materialReadiness'); box.replaceChildren();
    box.append(node('p',report.message || `待补/待核对 ${report.gap_count} 句，未能判断 ${report.unknown_count} 句。${report.script_confirmed?'当前已确认稿':'当前待确认草稿'}；不会改变任何确认。`));
    if(report.production_blockers?.length) box.append(node('p','进入制作还需：'+report.production_blockers.join('；')));
    const names={gap:'缺口',unknown:'未知',suggestion:'候选待回看'};
    for(const r of report.lines) {
        const card=node('article');
        card.append(node('strong',`第${r.line}句 · ${names[r.status]} · ${r.duration_basis==='estimated'?'估算':'实测'}${r.duration}秒`), node('p',r.text),node('p',r.message));
        for(const c of r.candidates) card.append(node('small',`${c.name} ${c.source_in.toFixed(2)}–${c.source_end.toFixed(2)}s · ${c.observation}`));
        box.append(card);
    }
}
function paintCombinedAudit(job) {
    const box=$('combinedAuditBody'); box.replaceChildren();
    const report=job?.audit;
    if(!report) {box.append(node('p','成片生成后汇总文字、选段、口播、画面文字与技术质量；仍需人工听核和审核。'));return;}
    box.append(node('p',report.summary));
    if(!report.sections) box.append(node('p','此报告只有文字预检：可能来自旧版，或在生成前已阻断。尚未做成片综合检查；旧片与审核记录保留。'));
    const labels={checked:'已检查',sampled:'抽样检查',partial:'部分未完成',needs_review:'待人工核对',not_checked:'未检查',error:'检查失败',not_applicable:'不适用'};
    const names={script_rules:'稿件规则',source_integrity:'来源完整性',product_evidence:'商品依据',selected_material:'实际选段',ocr:'画面文字OCR',asr:'成片口播ASR',alignment:'字级对齐与听核',technical:'编码与解码',rights:'素材授权',platform_policy:'平台规则与资质',visual_semantics:'视觉语义与同款'};
    for(const s of report.sections||[]) {
        const d=node('details'); d.append(node('summary',`${names[s.id]||s.id} · ${labels[s.status]||s.status}`));
        d.append(node('p',s.method||s.reason||s.scope||'详见可下载报告'));
        if(s.transcript!==undefined) d.append(node('p','实际识别：'+(s.transcript||'未识别人声')));
        box.append(d);
    }
    for(const f of report.findings) {
        const card=node('article'); card.append(node('strong',`第${f.line}镜 · ${f.source||'script'} · ${Number(f.time||0).toFixed(2)}秒`),node('p',f.reason),node('p',f.suggestion));
        if(job.artifacts.some(a=>a.kind==='video')) {
            const b=node('button','跳到此处核对','secondary'); b.type='button';
            b.onclick=()=>{const video=$('film');video.currentTime=Math.max(0,Number(f.time||0));video.scrollIntoView({block:'center'});};
            card.append(b);
        }
        box.append(card);
    }
    if(!report.findings.length) box.append(node('p','本次未命中所查规则，不代表合规或客户审核通过。'));
}
