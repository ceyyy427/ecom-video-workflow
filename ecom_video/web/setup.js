"use strict";
const el = id => document.getElementById(id);
let token, pollTimer;
async function api(path, body) {
  if (!token) {
    const session = await fetch("/api/session", {cache: "no-store"});
    if (!session.ok) throw new Error("无法连接本机服务，请重新启动。");
    token = (await session.json()).token;
  }
  const response = await fetch(path, body === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Workflow-Token": token}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "输入格式无效，请检查后重试。");
  return data;
}
function options(select, values, current) {
  select.replaceChildren();
  Object.entries(values).forEach(([value, label]) => {
    const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option);
  });
  if (Object.hasOwn(values, current)) select.value = current;
}
async function refresh() {
  el("refreshSetup").disabled = true;
  el("setupState").textContent = "正在读取本机依赖与配置；不发起付费调用…";
  try {
    const [setup, check] = await Promise.all([api("/api/setup/status"), api("/api/system/check")]);
    const list = el("environmentChecks"); list.replaceChildren();
    check.checks.forEach(row => {const li = document.createElement("li"); li.textContent = `${row.status === "ok" ? "✓" : "待处理"} ${row.name}：${row.action}`; list.append(li);});
    el("diskStatus").textContent = `工作磁盘剩余 ${(check.free_bytes / 1024 ** 3).toFixed(1)} GiB；业务数据版本 ${check.database.schema || "尚未创建"}。`;
    el("setupState").textContent = setup.platform_writes ? "当前实例开启平台写入。请关闭它并用“启动剪序.command”重新进入客户模式。" : check.ready ? "核心环境检查通过。请继续检查模型和声音；人工确认全部保留，平台写入已关闭。" : "存在待处理项目，按下方提示补齐；可以先整理商品资料。";
    const v = setup.vision;
    options(el("visionModel"), Object.fromEntries(v.models.map(m => [m, m])), v.selected);
    el("saveVision").disabled = !v.models.length || v.environment_override;
    el("visionStatus").textContent = v.message || `当前配置：${v.selected}。保存时验证本机图片能力，不进行素材推理。`;
    if (v.environment_override) el("visionStatus").textContent += " 由启动环境固定；修改环境配置并重启后可在此选择。";
    el("asrStatus").textContent = setup.asr.present ? "已检测到字幕模型文件；尚未在本页校验。" : "字幕模型尚未安装；需要配音对齐时请安装。";
    const voice = setup.voice;
    options(el("setupSpeaker"), voice.speakers, voice.speaker);
    el("voiceStatus").textContent = voice.message + (voice.environment_override ? " 当前来自启动环境；页面保存已禁用，避免保存后实际仍使用旧 Key。" : " 可在下方保存或明确替换。");
    ["voiceKey", "setupSpeaker", "replaceVoice", "saveVoice"].forEach(id => {el(id).disabled = voice.environment_override;});
    await progress();
  } catch (error) { el("setupState").textContent = error.message; }
  finally {el("refreshSetup").disabled = false;}
}
async function progress() {
  clearTimeout(pollTimer);
  try {
    const data = await api("/api/setup/asr");
    const running = ["running", "cancelling"].includes(data.state);
    if (data.state === "complete") el("asrStatus").textContent = "字幕模型已在本次服务运行中通过 SHA256 校验。";
    el("asrProgress").textContent = data.message + (data.bytes ? ` 已接收 ${(data.bytes / 1024 ** 2).toFixed(1)} MiB。` : "");
    el("installAsr").disabled = running || !el("asrConsent").checked;
    el("cancelAsr").disabled = !running || data.state === "cancelling";
    if (running) pollTimer = setTimeout(progress, 1500);
  } catch (error) {el("asrProgress").textContent = error.message + " 刷新可恢复查看进度。";}
}
el("refreshSetup").addEventListener("click", refresh);
el("saveVision").addEventListener("click", async () => {
  el("saveVision").disabled = true;
  try {
    const data = await api("/api/setup/vision", {model: el("visionModel").value});
    el("visionResult").textContent = `已验证并保存 ${data.model}；未执行素材识别。`;
  } catch (error) {el("visionResult").textContent = error.message;}
  finally {el("saveVision").disabled = false;}
});
el("voiceForm").addEventListener("submit", async event => {
  event.preventDefault(); el("saveVoice").disabled = true;
  const body = {api_key: el("voiceKey").value, speaker: el("setupSpeaker").value, replace: el("replaceVoice").checked};
  el("voiceKey").value = "";
  try {
    const result = await api("/api/setup/voice", body);
    el("voiceResult").textContent = result.message;
    el("replaceVoice").checked = false;
    await refresh();
  } catch (error) {el("voiceResult").textContent = error.message;}
  finally {body.api_key = ""; el("saveVoice").disabled = el("voiceKey").disabled;}
});
el("asrConsent").addEventListener("change", progress);
el("installAsr").addEventListener("click", async () => {
  el("installAsr").disabled = true;
  try {await api("/api/setup/asr", {confirmed: true}); await progress();}
  catch (error) {el("asrProgress").textContent = error.message; el("installAsr").disabled = !el("asrConsent").checked;}
});
el("cancelAsr").addEventListener("click", async () => {
  try {await api("/api/setup/asr/cancel", {}); await progress();}
  catch (error) {el("asrProgress").textContent = error.message;}
});
window.addEventListener("pagehide", () => {clearTimeout(pollTimer); el("voiceKey").value = "";});
refresh();
