"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  draft: "草稿",
  queued: "等待生成",
  validating: "检查输入",
  rendering: "正在合成",
  auditing: "检查成片",
  needs_review: "待人工复核",
  ready: "复核通过",
  rejected: "已退回",
  blocked: "预检阻断",
  failed: "生成失败",
  cancelled: "已取消",
};
const active = ["queued", "validating", "rendering", "auditing"];
let token = "",
  selected = null,
  job = null,
  dirty = false,
  busy = false,
  noticeTimer;
const node = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
function notify(message, failed = false) {
  $("notice").textContent = message;
  $("notice").className = failed ? "failure" : "";
  $("notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(
    () => ($("notice").hidden = true),
    failed ? 9000 : 4000,
  );
}
async function api(path, options = {}) {
  const headers = { "X-Workflow-Token": token, ...options.headers };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, { ...options, headers });
  const data = await response.json();
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail))
      detail = detail.map((x) => `${x.loc.at(-1)}: ${x.msg}`).join("；");
    throw new Error(detail || `请求失败 (${response.status})`);
  }
  return data;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  refreshControls();
  try {
    await fn();
    await refreshList();
  } catch (error) {
    notify(error.message, true);
  } finally {
    busy = false;
    refreshControls();
  }
}
function currentInput() {
  return {
    title: $("title").value,
    script: $("script").value,
    seconds: Number($("seconds").value),
  };
}
function countLines() {
  const lines = $("script")
    .value.split("\n")
    .filter((x) => x.trim());
  $("lineCount").textContent = `${lines.length} 镜`;
}
function fillEditor() {
  $("title").value = job?.title || "";
  $("script").value = job?.script || "";
  $("seconds").value = job?.seconds || 3;
  dirty = false;
  countLines();
  $("reviewer").value = "";
  $("reviewNote").value = "";
  $("confirmed").checked = false;
}
function refreshControls() {
  const draft = !job || job.status === "draft";
  ["title", "script", "seconds", "save"].forEach(
    (id) => ($(id).disabled = !draft || busy),
  );
  if (job?.provenance) {
    $("title").disabled = true;
    $("script").disabled = true;
  }
  document.dispatchEvent(new Event("workflow-controls"));
  $("newJob").disabled = busy;
  $("visualFiles").disabled = !job || !draft || busy;
  $("audioFile").disabled =
    !job || !draft || busy || job.assets.filter((a) => a.kind === "audio").length >= 2;
  $("submit").disabled =
    !job || !draft || busy || !job.assets.some((a) => a.kind !== "audio");
  $("submit").textContent = busy ? "正在处理…" : "锁定脚本并生成";
  $("saveHint").textContent = dirty
    ? "有未保存修改"
    : !job
      ? "先保存草稿，再添加素材"
      : draft
        ? "草稿已保存"
        : "脚本与素材已锁定";
  $("submitHint").textContent = job?.provenance ? "产品脚本已确认；修改文案请回到产品资料夹" : !draft
    ? "修改内容请复制为新草稿"
    : job?.assets.some((a) => a.kind !== "audio")
      ? "提交后保留当前脚本版本"
      : "至少添加一个画面素材";
  $("cancel").hidden = !job || !["draft", ...active].includes(job.status);
  $("retry").hidden =
    !job || job.status !== "failed" || job.attempts >= job.max_attempts;
  $("clone").hidden = !job || job.status === "draft";
  ["cancel", "retry", "clone"].forEach((id) => ($(id).disabled = busy));
  document
    .querySelectorAll("#assets button,#audioAssets button,#reviewForm button")
    .forEach((b) => (b.disabled = busy));
}
function showAssets() {
  $("assets").replaceChildren();
  $("audioAssets").replaceChildren();
  const assets = job?.assets || [];
  $("assetCount").textContent =
    `${assets.filter((a) => a.kind !== "audio").length} / 30`;
  assets.forEach((a, i) => {
    const item = node("div", undefined, "asset");
    if (a.kind !== "audio") {
      const preview = node(a.kind === "image" ? "img" : "video");
      preview.src = `/api/jobs/${job.id}/assets/${a.id}`;
      if (a.kind === "image") preview.alt = a.name;
      else {
        preview.muted = true;
        preview.preload = "metadata";
      }
      item.append(preview);
    }
    const text = node("div", undefined, "file-label");
    text.append(
      node("strong", a.name),
      node(
        "small",
        `${a.kind === "audio" ? "配音" : `素材 ${i + 1}`} · ${(a.size / 1024 / 1024).toFixed(1)} MiB`,
      ),
    );
    item.append(text);
    if (job.status === "draft") {
      const remove = node("button", "移除");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除 ${a.name}`);
      remove.onclick = () =>
        action(async () => {
          job = await api(`/jobs/${selected}/assets/${a.id}`, {
            method: "DELETE",
          });
          render();
        });
      item.append(remove);
    }
    $(a.kind === "audio" ? "audioAssets" : "assets").append(item);
  });
}
function render() {
  $("pageTitle").textContent = job?.title || "把脚本变成一条成片";
  $("jobMeta").textContent = job
    ? `任务 ${job.id.slice(0, 8)} / 尝试 ${job.attempts} 次`
    : "新建视频";
  $("status").textContent = labels[job?.status || "draft"];
  $("status").className = "badge " + (job?.status || "draft");
  const step =
    !job || job.status === "draft" ? 1 : active.includes(job.status) ? 2 : 3;
  [1, 2, 3].forEach((n) =>
    $("step" + n).classList.toggle("active", n === step),
  );
  showAssets();
  const artifacts = job?.artifacts || [];
  const video = artifacts.find((a) => a.kind === "video");
  $("video").hidden = !video;
  $("previewEmpty").hidden = !!video;
  if (video) {
    const src = `/api/jobs/${job.id}/artifacts/video`;
    if ($("video").getAttribute("src") !== src) $("video").src = src;
  } else if ($("video").hasAttribute("src")) {
    $("video").pause();
    $("video").removeAttribute("src");
    $("video").load();
  }
  const hint = active.includes(job?.status)
    ? "视频正在生成"
    : job?.status === "blocked"
      ? "脚本需要先修改"
      : job?.status === "failed"
        ? "这次生成未完成"
        : "下一条成片，从这里开始";
  $("previewEmpty").querySelector("h3").textContent = hint;
  $("previewEmpty").querySelector("p").textContent = active.includes(
    job?.status,
  )
    ? "可以留在此页等待；关闭页面不会取消任务。"
    : job?.status === "blocked"
      ? "查看下方预检原因，复制为新草稿后修改。"
      : "保存脚本，添加画面素材，生成后在这里预览和复核。";
  $("downloads").replaceChildren();
  const names = {
    video: "下载 MP4",
    video_clean: "下载无背景音乐版",
    subtitles: "字幕 SRT",
    audit: "审核 JSON",
    audit_html: "综合审核 HTML",
    manifest: "镜头清单",
    qc: "质量报告",
    provenance: "事实来源",
  };
  artifacts.forEach((a) => {
    const link = node("a", names[a.kind] || a.kind);
    link.href = `/api/jobs/${job.id}/artifacts/${a.kind}?download=true`;
    link.download = "";
    $("downloads").append(link);
  });
  $("error").hidden = !job?.error;
  $("error").textContent = job?.error || "";
  $("auditBody").replaceChildren();
  const report = job?.audit;
  $("auditBadge").textContent = report
    ? report.status === "blocked"
      ? "有阻断项"
      : "需人工复核"
    : "等待生成";
  if (report) {
    $("auditBody").append(node("p", report.summary, "muted"));
    if (!report.findings.length)
      $("auditBody").append(
        node("p", "规则未命中风险词。以下内容仍需人工核验。", "muted"),
      );
    report.findings.forEach((f) => {
      const box = node("div", undefined, "finding");
      box.append(
        node(
          "strong",
          `第 ${f.line} 镜 · ${f.term} · ${f.severity === "block" ? "阻断" : "待核验"}`,
        ),
        node("p", f.reason),
        node("p", f.suggestion),
      );
      $("auditBody").append(box);
    });
    const list = node("ul", undefined, "checks");
    report.manual_checks.forEach((t) => list.append(node("li", t)));
    $("auditBody").append(list);
  } else
    $("auditBody").append(
      node(
        "p",
        "文字规则预检后，仍需检查卖点真实性、画面、口播、素材授权与平台要求。",
        "muted",
      ),
    );
  $("reviewForm").hidden = job?.status !== "needs_review";
  $("reviewResult").textContent = (job?.reviews || [])
    .map((r) => `${r.reviewer} · ${labels[r.decision]}\n${r.note}`)
    .join("\n");
  $("events").replaceChildren();
  (job?.events || []).forEach((e) =>
    $("events").append(
      node(
        "li",
        `${new Date(e.created_at * 1000).toLocaleTimeString("zh-CN")} ${e.message}`,
      ),
    ),
  );
  document.dispatchEvent(new Event("workflow-render"));
  refreshControls();
}
async function refreshList() {
  const items = await api("/jobs");
  $("jobs").replaceChildren();
  if (!items.length)
    $("jobs").append(node("p", "还没有任务，先保存第一份脚本。", "muted"));
  items.forEach((j) => {
    const b = node(
      "button",
      undefined,
      "job" + (j.id === selected ? " selected" : ""),
    );
    b.append(
      node("strong", j.title),
      node(
        "small",
        `${labels[j.status]} · ${new Date(j.created_at * 1000).toLocaleDateString("zh-CN")}`,
      ),
    );
    b.onclick = async () => {
      if (busy) return;
      if ((dirty || window.storyboardEditor?.dirty) && !confirm("切换任务会丢弃尚未保存的脚本修改，继续吗？"))
        return;
      await action(async () => {
        const next = await api("/jobs/" + j.id);
        selected = j.id;
        job = next;
        localStorage.setItem("ecom.selected", selected);
        fillEditor();
        render();
      });
    };
    $("jobs").append(b);
  });
}
async function saveDraft() {
  if (dirty && window.storyboardEditor?.dirty && !confirm("保存脚本会重置未保存的分镜修改，继续吗？")) throw new Error("已保留当前编辑，请先决定要保存的版本");
  const data = currentInput();
  job = await api(selected ? "/jobs/" + selected : "/jobs", {
    method: selected ? "PUT" : "POST",
    body: JSON.stringify(data),
  });
  selected = job.id;
  localStorage.setItem("ecom.selected", selected);
  if (dirty) window.storyboardEditor?.invalidate();
  dirty = false;
  render();
}
$("scriptForm").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    await saveDraft();
    notify("草稿已保存，可以添加素材。");
  });
};
["title", "script", "seconds"].forEach((id) =>
  $(id).addEventListener("input", () => {
    dirty = true;
    countLines();
    refreshControls();
  }),
);
$("newJob").onclick = () => {
  if (busy) return;
  if ((dirty || window.storyboardEditor?.dirty) && !confirm("丢弃尚未保存的修改并新建任务？")) return;
  selected = null;
  job = null;
  localStorage.removeItem("ecom.selected");
  fillEditor();
  render();
  refreshList().catch((e) => notify(e.message, true));
  $("title").focus();
};
async function uploadFiles(input, isAudio) {
  const files = [...input.files];
  if (!files.length) return;
  await action(async () => {
    for (const file of files) {
      const ext = file.name.split(".").at(-1).toLowerCase();
      const data = new FormData();
      data.append(
        "kind",
        isAudio
          ? "audio"
          : ["mp4", "mov", "webm"].includes(ext)
            ? "video"
            : "image",
      );
      data.append("file", file);
      job = await api(`/jobs/${selected}/assets`, {
        method: "POST",
        body: data,
      });
      render();
    }
    notify("素材已添加。");
  });
  input.value = "";
}
$("visualFiles").onchange = () => uploadFiles($("visualFiles"), false);
$("audioFile").onchange = () => uploadFiles($("audioFile"), true);
$("submit").onclick = () =>
  action(async () => {
    if (dirty) await saveDraft();
    if (window.storyboardEditor) await window.storyboardEditor.ensureSaved();
    job = await api(`/jobs/${selected}/submit`, { method: "POST" });
    render();
    notify("脚本已锁定，任务进入生成队列。");
  });
["cancel", "retry"].forEach(
  (name) =>
    ($(name).onclick = () =>
      action(async () => {
        job = await api(`/jobs/${selected}/${name}`, { method: "POST" });
        render();
      })),
);
$("clone").onclick = () =>
  action(async () => {
    job = await api(`/jobs/${selected}/clone`, { method: "POST" });
    selected = job.id;
    localStorage.setItem("ecom.selected", selected);
    fillEditor();
    render();
    notify("已复制为新草稿，原记录保留。");
  });
$("reviewForm").onsubmit = (e) => {
  e.preventDefault();
  const decision = e.submitter.value;
  action(async () => {
    job = await api(`/jobs/${selected}/review`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        reviewer: $("reviewer").value,
        note: $("reviewNote").value,
        confirmed: $("confirmed").checked,
      }),
    });
    render();
    notify(
      decision === "ready"
        ? "人工复核已记录。"
        : "已退回；可以复制为新草稿修改。",
    );
  });
};
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
async function poll() {
  try {
    const health = await api("/health");
    const online = health.workers.length > 0;
    $("health").textContent =
      !health.ffmpeg || !health.ffprobe || !health.font_ready
        ? "缺少渲染依赖，请运行环境检查"
        : online
          ? "本地渲染服务在线"
          : "渲染进程离线，队列等待启动";
    $("healthDot").classList.toggle(
      "online",
      online && health.font_ready && health.ffmpeg && health.ffprobe,
    );
    if (!busy) {
      const id = selected;
      if (id && active.includes(job?.status)) {
        const next = await api("/jobs/" + id);
        if (!busy && selected === id) {
          job = next;
          render();
        }
      }
      await refreshList();
    }
  } catch (e) {
    $("health").textContent = "本地服务连接中断";
    $("healthDot").classList.remove("online");
  } finally {
    setTimeout(poll, 2500);
  }
}
(async () => {
  try {
    token = (await api("/session")).token;
    selected = new URLSearchParams(location.search).get("job") || localStorage.getItem("ecom.selected");
    if (selected) {
      try {
        job = await api("/jobs/" + selected);
      } catch {
        selected = null;
        localStorage.removeItem("ecom.selected");
      }
    }
    fillEditor();
    render();
    await refreshList();
    window.workflowReady = true;
    document.dispatchEvent(new Event("workflow-ready"));
    poll();
  } catch (e) {
    notify(e.message, true);
    $("health").textContent = "连接失败，请刷新页面";
  }
})();
