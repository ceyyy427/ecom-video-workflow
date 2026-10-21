"use strict";
let product = null, productDirty = false, productReady = false, modelAvailable = false;
const productStates = {collecting: "待确认事实", facts_confirmed: "事实已确认", script_draft: "脚本待确认", script_confirmed: "脚本已确认"};
const productDraft = () => product?.script_drafts.find(d => d.id === product.current_draft_id);
const productReview = () => product?.fact_reviews.find(r => r.id === product.current_review_id);
const selectedFacts = () => (productReview()?.fact_ids || []).map(id => product.facts.find(f => f.id === id));
const productPath = () => `/products/${product.id}`;
const productPost = (path, data) => api(productPath() + path, {method: "POST", body: JSON.stringify({revision: product.revision, ...data})});
function productMode(show) {
  $("productPanel").hidden = !show;
  $("productMode").setAttribute("aria-pressed", String(show));
  $("manualMode").setAttribute("aria-pressed", String(!show));
}
$("productMode").onclick = () => productMode(true);
$("manualMode").onclick = () => productMode(false);
function mayDiscardProduct() {
  return !productDirty || confirm("切换或重新生成会丢弃尚未保存的分镜修改，继续吗？");
}
function factSelectionChanged() {
  const approved = productReview()?.fact_ids;
  if (!approved) return false;
  const checked = [...document.querySelectorAll("#factsList input:checked")].map(el => el.value);
  return checked.length !== approved.length || checked.some(id => !approved.includes(id));
}
function productControls() {
  const selectionChanged = factSelectionChanged();
  $("factSelectionHint").textContent = selectionChanged ? "勾选已变化，请先重新确认所选事实，或恢复上次选择。" : productReview() ? "当前生成使用上次人工确认的所选事实。" : "";
  const locked = busy || !productReady;
  document.querySelectorAll("#productPanel input,#productPanel textarea,#productPanel select,#productPanel button").forEach(el => {el.disabled = locked;});
  $("generateScript").disabled = locked || !productReview() || selectionChanged;
  $("generationMode").querySelector('option[value="model"]').disabled = !modelAvailable;
  $("confirmFacts").disabled = locked || !product?.facts.length;
  $("approveScript").disabled = locked || !productDraft() || productDirty || selectionChanged;
  $("saveProductDraft").disabled = locked || !productDraft() || !productDirty;
  $("reloadProduct").disabled = locked || !product;
}
document.addEventListener("workflow-controls", productControls);
function modelHint() {
  const external = $("generationMode").value === "model";
  $("externalConsentLabel").hidden = !external;
  $("modelHint").textContent = external ? "模型只选择与排列已确认事实。返回无来源内容将停止生成；接口调用可能产生费用。" : "本地编排原文事实，并添加固定开场与结尾。" + (modelAvailable ? "" : " 模型接口尚未配置。");
}
$("generationMode").onchange = modelHint;
async function productList() {
  const items = await api("/products");
  $("productSelect").replaceChildren(new Option("新建资料夹", ""));
  items.forEach(p => $("productSelect").add(new Option(`${p.title} · ${productStates[p.status]}`, p.id)));
  $("productSelect").value = product?.id || "";
}
async function loadProduct(id) {
  const next = id ? await api("/products/" + id) : null;
  product = next;
  if (id) localStorage.setItem("ecom.product", id);
  else localStorage.removeItem("ecom.product");
  productDirty = false;
  renderProduct();
  await productList();
}
$("productSelect").onchange = () => {
  const id = $("productSelect").value;
  $("productSelect").value = product?.id || "";
  if (!mayDiscardProduct()) return;
  action(() => loadProduct(id));
};
$("reloadProduct").onclick = () => {if (mayDiscardProduct()) action(() => loadProduct(product.id));};
$("createProduct").onsubmit = e => {
  e.preventDefault();
  if (!mayDiscardProduct()) return;
  action(async () => {
    product = await api("/products", {method: "POST", body: JSON.stringify({title: $("productTitle").value})});
    localStorage.setItem("ecom.product", product.id);
    productDirty = false;
    $("productTitle").value = "";
    renderProduct();
    await productList();
    notify("资料夹已创建，添加产品文档或链接。");
  });
};
async function acceptProduct(next) {
  product = next;
  productDirty = false;
  renderProduct();
  await productList();
}
$("productFile").onchange = () => {
  const file = $("productFile").files[0];
  if (!file) return;
  if (!mayDiscardProduct()) {$("productFile").value = ""; return;}
  action(async () => {
    const form = new FormData();form.append("revision", product.revision);form.append("file", file);
    await acceptProduct(await api(productPath()+"/documents", {method: "POST", body: form}));
    notify("资料已解析，请核对候选事实。");
  }).finally(() => {$("productFile").value = "";});
};
$("linkProduct").onsubmit = e => {
  e.preventDefault();
  if (!mayDiscardProduct()) return;
  action(async () => {
    notify("正在读取公开网页，最长约 40 秒…");
    await acceptProduct(await productPost("/links", {url: $("productUrl").value}));
    $("productUrl").value = "";
    notify("网页快照已保存，请核对正文与产品字段。");
  });
};
function sourceName(id) {const s = product.sources.find(s => s.id === id);return s?.original_url || s?.file_name || id;}
function renderQuoteUnits() {
  const source = product?.sources.find(s => s.id === $("quoteSource").value);
  $("quoteUnit").replaceChildren();
  source?.extracted.units.forEach(u => $("quoteUnit").add(new Option(u.locator, u.id)));
  renderQuoteContext();
}
function renderQuoteContext() {
  const source = product?.sources.find(s => s.id === $("quoteSource").value);
  $("quoteContext").textContent = source?.extracted.units.find(u => u.id === $("quoteUnit").value)?.text || "添加资料后可查看原文。";
  $("quoteText").value = "";
}
$("quoteSource").onchange = renderQuoteUnits;
$("quoteUnit").onchange = renderQuoteContext;
$("quoteForm").onsubmit = e => {
  e.preventDefault();
  if (!mayDiscardProduct()) return;
  action(async () => {
    await acceptProduct(await productPost("/quotes", {source_id: $("quoteSource").value, unit_id: $("quoteUnit").value, text: $("quoteText").value}));
    notify("摘录已加入候选，请重新确认事实。");
  });
};
$("factsForm").onsubmit = e => {
  e.preventDefault();
  if (!mayDiscardProduct()) return;
  const ids = [...document.querySelectorAll("#factsList input:checked")].map(el => el.value);
  action(async () => {
    await acceptProduct(await productPost("/facts/confirm", {fact_ids: ids, reviewer: $("factsReviewer").value, note: $("factsNote").value, confirmed: $("factsChecked").checked}));
    notify("事实确认已记录，可以生成脚本。");
  });
};
$("generateProduct").onsubmit = e => {
  e.preventDefault();
  if (!mayDiscardProduct()) return;
  action(async () => {
    await acceptProduct(await productPost("/scripts/generate", {mode: $("generationMode").value, external_consent: $("externalConsent").checked}));
    notify("脚本草稿已生成，请逐镜核对文字与事实来源。");
  });
};
function readScenes() {
  return [...document.querySelectorAll(".script-scene")].map(el => ({text: el.querySelector("textarea").value, fact_ids: [...el.querySelector("select").selectedOptions].map(o => o.value)}));
}
$("saveProductDraft").onclick = () => action(async () => {
  await acceptProduct(await productPost("/scripts", {scenes: readScenes()}));
  notify("修改已保存为新版本，请确认当前脚本。");
});
async function adoptProductJob(next) {
  job = next;selected = job.id;
  localStorage.setItem("ecom.selected", selected);
  fillEditor();render();await refreshList();
  $("pageTitle").scrollIntoView({behavior: "smooth", block: "start"});
}
$("scriptApproval").onsubmit = e => {
  e.preventDefault();
  if (dirty && !confirm("进入产品剪辑草稿会丢弃下方尚未保存的手写脚本修改，继续吗？")) return;
  action(async () => {
    const next = await productPost("/scripts/confirm", {draft_id: product.current_draft_id, reviewer: $("scriptReviewer").value, note: $("scriptNote").value, confirmed: $("scriptChecked").checked, seconds: 3});
    await loadProduct(product.id);
    await adoptProductJob(next);
    notify("已创建剪辑草稿。添加画面素材后即可生成视频。");
  });
};
function renderProduct() {
  $("productContent").hidden = !product;
  $("productStatus").textContent = product ? productStates[product.status] : "选择资料夹";
  if (!product) {productControls();return;}
  $("sourceList").replaceChildren();
  $("quoteSource").replaceChildren();
  product.sources.forEach(s => {
    const box = node("div", undefined, "source-card");
    box.append(node("strong", s.original_url || s.file_name), node("small", `${new Date(s.created_at*1000).toLocaleString("zh-CN")} · ${s.extracted.units.length} 段 · SHA-256 ${s.sha256.slice(0,12)}…`));
    const download = node("a", "下载原始资料 / 网页快照");download.href = `/api/products/${product.id}/sources/${s.id}`;download.download = "";box.append(download);
    if(s.final_url && s.final_url !== s.original_url) box.append(node("small", "最终地址：" + s.final_url));
    $("sourceList").append(box);
    $("quoteSource").add(new Option(s.original_url || s.file_name, s.id));
  });
  if(!product.sources.length) $("sourceList").append(node("p", "还没有资料。", "muted"));
  renderQuoteUnits();
  $("factsList").replaceChildren();
  const review = productReview();
  product.facts.forEach(f => {
    const label = node("label", undefined, "fact-item");
    const check = node("input");check.type = "checkbox";check.value = f.id;check.checked = review?.fact_ids.includes(f.id) || false;check.onchange = productControls;
    const content = node("div");content.append(node("span", f.text), node("small", `${sourceName(f.source_id)} · ${f.locator}`));
    const context = node("details");context.append(node("summary", "查看所在段落"));
    const unit = product.sources.find(s=>s.id===f.source_id)?.extracted.units.find(u=>u.id===f.unit_id);
    context.append(node("p",unit?.text || ""));content.append(context);label.append(check,content);$("factsList").append(label);
  });
  if(!product.facts.length) $("factsList").append(node("p", "暂无短句候选。可以在左侧查看原文，摘录完整的产品事实。", "muted"));
  $("factsChecked").checked=false;
  $("factsNote").value="";
  const draft = productDraft();
  $("draftMeta").textContent = draft ? `版本 ${product.script_drafts.findIndex(d=>d.id===draft.id)+1} · ${draft.mode === "extractive" ? "本地编排" : draft.mode === "model" ? "模型选材" : "人工编辑"}` : review ? "事实已确认，可以生成" : "等待事实确认";
  $("scriptScenes").replaceChildren();
  const facts = selectedFacts();
  draft?.payload.forEach((scene,index)=>{
    const row=node("div",undefined,"script-scene");row.append(node("strong",String(index+1).padStart(2,"0")));
    const copy=node("div");const text=node("textarea");text.value=scene.text;text.maxLength=100;text.rows=3;text.setAttribute("aria-label",`第 ${index+1} 镜文案`);copy.append(text,node("p",scene.attribution==="neutral"?"固定中性文案，无产品事实":scene.attribution==="exact_quote"?"原文引用":"人工改写 · 须核对是否保持原意","scene-citation"));
    const refs=node("div",undefined,"scene-refs");const select=node("select");select.multiple=true;select.setAttribute("aria-label",`第 ${index+1} 镜事实引用`);
    facts.forEach(f=>{const option=new Option(f.text,f.id);option.selected=scene.fact_ids.includes(f.id);select.add(option);});refs.append(select,node("p",scene.fact_ids.map(id=>{const f=facts.find(x=>x.id===id);return f?`${sourceName(f.source_id)} · ${f.locator}`:"";}).join("；")||"中性开场/结尾可不选事实；多选按 ⌘ / Ctrl。","scene-citation"));
    const mark = () => {productDirty=true;$("scriptChecked").checked=false;$("draftMeta").textContent="有未保存修改 · 保存后重新确认";productControls();};
    text.oninput=mark;select.onchange=mark;row.append(copy,refs);$("scriptScenes").append(row);
  });
  $("saveProductDraft").hidden=!draft;$("scriptEditHint").hidden=!draft;$("scriptApproval").hidden=!draft;
  $("scriptChecked").checked=false;$("scriptNote").value="";
  $("productApprovalResult").replaceChildren();
  const approval = product.script_approvals.find(a=>a.draft_id===draft?.id);
  if(approval){
    $("scriptApproval").hidden=true;
    const open=node("button","打开已创建的剪辑任务","secondary");
    open.onclick=()=>{if(dirty&&!confirm("丢弃下方未保存脚本，切换到此任务？"))return;action(async()=>adoptProductJob(await api("/jobs/"+approval.job_id)));};
    $("productApprovalResult").append(node("p",`${approval.reviewer} 已确认此版本。编辑后保存为新版本，可再次确认。`),open);
  }
  $("productEvents").replaceChildren();product.events.forEach(e=>$("productEvents").append(node("li",`修订 ${e.revision} · ${new Date(e.created_at*1000).toLocaleString("zh-CN")} · ${e.message}`)));
  modelHint();productControls();
}
function renderJobProvenance() {
  const p = job?.provenance;
  $("jobProvenance").hidden=!p;
  $("jobProvenanceBody").replaceChildren();
  if(!p)return;
  $("jobProvenanceBody").append(node("p",`事实确认：${p.fact_review.reviewer} · ${p.fact_review.note}。脚本确认：${p.script_approval.reviewer} · ${p.script_approval.note}。`));
  const list=node("ol");p.scenes.forEach(s=>{if(!s.fact_ids.length)return;const item=node("li",s.text);s.fact_ids.forEach(id=>{const f=p.facts.find(f=>f.id===id);const source=p.sources.find(x=>x.id===f.source_id);item.append(node("p",`${f.text} — ${source.original_url||source.file_name} / ${f.locator}`));});list.append(item);});$("jobProvenanceBody").append(list);
  const open=node("button","回到产品资料夹编辑新版本","text-button");open.onclick=()=>{if(!mayDiscardProduct())return;action(async()=>{await loadProduct(p.product_id);productMode(true);$("productPanel").scrollIntoView({behavior:"smooth"});});};$("jobProvenanceBody").append(open);
}
document.addEventListener("workflow-render",renderJobProvenance);
window.addEventListener("beforeunload",e=>{if(productDirty){e.preventDefault();e.returnValue="";}});
async function initializeProducts() {
  try {
    const capabilities=await api("/products/capabilities");modelAvailable=capabilities.model.configured;
    productReady=true;
    const id=localStorage.getItem("ecom.product");
    if(id){try{await loadProduct(id);}catch{localStorage.removeItem("ecom.product");await productList();}}
    else await productList();
    renderJobProvenance();modelHint();productControls();
  }catch(error){notify("产品资料模块加载失败："+error.message,true);}
}
document.addEventListener("workflow-ready",initializeProducts,{once:true});
if(window.workflowReady)initializeProducts();
productControls();
