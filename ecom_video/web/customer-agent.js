/* Bounded local production controls. All human decisions remain explicit. */
(() => {
    let current = null, flight = false;
    const labels = {proposed:'计划已准备',queued:'等待执行',running:'自动制作中',paused:'已暂停新步骤',waiting_human:'等待人工确认',completed:'已完成并人工审片',failed:'本次运行已停止',cancelled:'已取消',unknown:'上次结果待核对'};
    const gates = {storyboard:'请在分镜区实际核对并确认最终分镜风格后恢复',facts_script:'请先核对事实和文稿，再创建新计划',media:'需要商品素材',voice_upload:'需要成品配音',style:'请确认一个风格后恢复',listening:'请在上方逐句听核配音后恢复',alignment_failed:'对齐未通过，请在上方检查配音与文稿',film_review:'请在下方完整观看并人工审核成片'};
    const terminal = e => !e || ['completed','failed','cancelled','unknown'].includes(e.status);
    const binding = e => ({plan_hash:e.plan_hash,revision:e.revision,policy_id:e.policy.policy_id});
    const stamp = project => JSON.stringify([project.revision,project.product.revision,project.job?.id,project.job?.storyboard_revision,project.job?.status,project.alignment?.id,project.alignment?.status,analysisStamp(project)]);
    const panel = document.getElementById('agentPanel');
    async function request(path, body) {
        const r = await fetch('/api/agent'+path, {method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Workflow-Token':token},...(body?{body:JSON.stringify(body)}:{})});
        const data = await r.json();
        if(!r.ok) throw Error(data.error?.safe_message || data.detail || '本机自动制作请求未完成');
        return data;
    }
    function paint() {
        $('agentState').textContent = current ? `${labels[current.status]||current.status}。${gates[current.waiting_for]||''} 步骤 ${current.steps_used}/${current.policy.max_steps}，本机模型 ${current.usage.model_calls}/${current.policy.max_model_calls} 次。${current.error?.safe_message||''}` : '一次启动，按已确认资料自动识别、选段、准备分镜和渲染；遇到人工确认会停下。';
        $('agentStart').disabled = !p || (!terminal(current) && current.status!=='proposed') || dirty() || !selected || p.product.status!=='script_confirmed';
        $('agentPause').disabled = terminal(current) || ['paused','proposed'].includes(current.status);
        $('agentResume').disabled = !current || !['paused','waiting_human'].includes(current.status) || current.inflight_step || dirty();
        $('agentCancel').disabled = terminal(current);
    }
    async function saveChoice() {
        if(!selected || !$('agentStyleChecked').checked || !$('agentReviewer').value.trim()) throw Error('请选定风格，填写确认人并勾选风格确认。');
        current = await request(`/runs/${current.run_id}/style`, {...binding(current),style_id:selected,direction_basis:p.direction_basis,reviewer:$('agentReviewer').value.trim(),confirmed:true});
    }
    async function act(action) {
        if(flight) return;
        flight=true;
        try {
            if(dirty() && action!=='cancel' && action!=='pause') throw Error('请先保存未完成的修改，再继续自动制作。');
            if(action==='start') {
                if(!selected || !$('agentStyleChecked').checked || !$('agentReviewer').value.trim()) throw Error('请先确认风格并填写确认人。');
                const proposal=await request('/runs',{schema_version:1,request_id:'ui-'+crypto.randomUUID().replaceAll('-',''),operation:'project.produce',input:{project_id:p.id,expected_revision:p.revision,expected_product_revision:p.product.revision,policy:{policy_id:'local-v1',max_steps:Number($('agentSteps').value),max_elapsed_s:Number($('agentSeconds').value),max_model_calls:Number($('agentCalls').value),max_cost_cny:'0'}}});
                current=await request(`/runs/${proposal.run_id}/execution`);
                await saveChoice();
                current=await request(`/runs/${current.run_id}/execute`,binding(current));
            } else {
                if(action==='resume' && current.waiting_for==='style') await saveChoice();
                if(action==='resume' && current.waiting_for==='listening' && p.alignment?.status!=='confirmed') {
                    const a=p.alignment;
                    if(a?.status!=='needs_review' || !$('voiceChecked').checked || !$('voiceReviewer').value.trim()) throw Error('请在上方逐句听核，填写听核人并勾选确认，再恢复制作。');
                    p.alignment=await post('/jobs/'+p.job.id+'/alignments/'+a.id+'/confirm',{confirmed:true,reviewer:$('voiceReviewer').value.trim(),result:{sentences:a.result.sentences.map(s=>({words:s.words.map(w=>({start:w.start,end:w.end}))}))}});
                    paintAlignment();
                }
                current=await request(`/runs/${current.run_id}/${action}`,binding(current));
            }
            paint();message($('agentState').textContent);
        } catch(e) { message(e.message,true); }
        finally {flight=false;paint();}
    }
    async function refresh() {
        if(flight || !p || !token) return;
        const pid=p.id;
        try {
            const rows=await request('/executions?project_id='+pid);
            if(p?.id!==pid)return;
            current=rows[0]||null;
            if(current && !terminal(current) && !dirty() && !busy) {
                const next=await api('/customer-projects/'+pid);
                if(p?.id===pid && stamp(next)!==stamp(p)) adopt(next);
            }
            paint();
        } catch(e) { $('agentState').textContent=e.message; }
    }
    for(const action of ['start','pause','resume','cancel']) $('agent'+action[0].toUpperCase()+action.slice(1)).onclick=()=>act(action);
    for(const id of ['makeBoard','render']) $(id).addEventListener('click',event=>{
        if(!terminal(current) && current.status!=='proposed') {
            event.preventDefault();event.stopImmediatePropagation();
            message('自动制作正在管理此版本，请使用下方的“确认后恢复”；单独修改分镜前请先取消本次运行。',true);
        }
    },true);
    fetch('/api/agent/capabilities').then(r=>r.json()).then(cap=>{
        panel.hidden=!cap.execution_enabled;
        if(cap.execution_enabled) { void refresh(); setInterval(()=>void refresh(),2000); }
    }).catch(()=>{panel.hidden=true;});
})();
