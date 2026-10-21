"use strict";
const $ = (id) => document.getElementById(id);
const states = {
  draft: "待确认上传",
  upload_queued: "上传排队中",
  uploading: "正在上传",
  material_pending: "等待素材可查询",
  checking_material: "正在查询素材",
  awaiting_approval: "待确认创建广告",
  create_queued: "创建排队中",
  creating: "正在创建广告",
  submitted: "已收到计划 ID",
  failed: "已停止",
  unknown: "结果不明 · 需平台核验",
  cancelled: "已取消",
};
let session = "",
  current = null,
  auth = null,
  busy = false,
  generation = 0;
async function api(path, body) {
  const options =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-workflow-token": session,
          },
          body: JSON.stringify(body),
        };
  const response = await fetch("/api" + path, options);
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string" ? value.detail : "请检查输入内容",
    );
  return value;
}
function notice(text) {
  $("notice").textContent = text;
  $("notice").hidden = false;
}
async function run(action) {
  if (busy) return;
  busy = true;
  $("account").disabled = true;
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await action();
  } catch (e) {
    notice(e.message);
  } finally {
    busy = false;
    $("account").disabled = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
    if (auth) {
      $("authorize").disabled = !auth.configured;
      $("verify").disabled = auth.status !== "authorized";
    }
    if (current)
      $("submitConsent").disabled =
        current.status === "draft" &&
        !(auth?.status === "authorized" && auth?.writes_enabled);
  }
}
function options(select, rows, placeholder) {
  select.replaceChildren(
    new Option(placeholder, ""),
    ...rows.map((r) => new Option(r.label, r.id)),
  );
}
async function refresh() {
  const aid = $("account").value,
    seq = ++generation;
  if (!aid) {
    $("authStatus").textContent = "先到「投放与复盘」登记一个千川账户。";
    $("tasks").replaceChildren();
    return;
  }
  const [status, tasks] = await Promise.all([
    api("/qianchuan/accounts/" + aid),
    api("/qianchuan/tasks?account_id=" + encodeURIComponent(aid)),
  ]);
  if (seq !== generation || aid !== $("account").value) return;
  auth = status;
  const names = {
    unconfigured: "应用未配置",
    unauthorized: "尚未授权",
    authorized: "广告主已授权",
    reauthorize: "需要重新授权",
    revoked: "本地授权已断开",
  };
  $("authStatus").textContent =
    `广告主 ${status.advertiser_id} · ${names[status.status] || status.status} · 真实写入${status.writes_enabled ? "已开启" : "未开启"}${status.max_budget ? " · 每计划 budget 上限 ¥" + status.max_budget : ""}`;
  $("tasks").replaceChildren();
  for (const t of tasks) {
    const card = document.createElement("div");
    card.className = "task-card";
    const info = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = t.parameters.name;
    const p = document.createElement("p");
    p.textContent = `${states[t.status]} · ¥${t.parameters.budget} · ROI2 ${t.parameters.roi2_goal} · ${t.id.slice(0, 8)}`;
    info.append(title, p);
    const b = document.createElement("button");
    b.className = "secondary";
    b.textContent = "查看 / 确认";
    b.onclick = () => run(() => open(t.id));
    card.append(info, b);
    $("tasks").append(card);
  }
  if (!tasks.length) $("tasks").textContent = "暂无原生投放任务。";
}
async function open(id) {
  current = await api("/qianchuan/tasks/" + id);
  const t = current;
  $("taskTitle").textContent = t.parameters.name + " · " + states[t.status];
  $("summary").textContent =
    `账户：${t.source_snapshot.account.name} / ${t.source_snapshot.account.advertiser_id}；商品 ${t.parameters.product_id}；抖音号 ${t.parameters.aweme_id}；预算 ¥${t.parameters.budget}；目标 ROI2 ${t.parameters.roi2_goal}；AIGC：${t.parameters.is_aigc ? "是" : "否"}`;
  $("video").href = "/api/jobs/" + t.job_id + "/artifacts/video";
  $("payload").textContent =
    t.payload_preview || JSON.stringify(t.parameters, null, 2);
  $("hash").textContent = t.snapshot_hash
    ? "确认摘要：" +
      t.snapshot_hash +
      "；有效至 " +
      new Date(t.prepared_until * 1000).toLocaleString()
    : "";
  $("taskError").textContent =
    t.error ||
    (t.status === "submitted"
      ? "计划 ID：" +
        t.result?.ad_id +
        "；平台审核、花费与投放状态请在千川核验。"
      : "");
  $("consentForm").hidden = !["draft", "awaiting_approval"].includes(t.status);
  $("consentForm").reset();
  $("consentLabel").textContent =
    t.status === "draft"
      ? "我已核对账户、成片使用权及 AIGC 属性，同意上传此视频到千川。"
      : "我已核对以上精确参数、商品与素材；同意创建广告并立即开始排期，理解平台接受后可能产生费用。budget 是每计划平台预算参数，不是账户累计消费上限；目标 ROI2 不等于看板支付 ROI。";
  $("submitConsent").textContent =
    t.status === "draft" ? "确认上传素材" : "确认创建广告（可能产生费用）";
  $("resolveForm").hidden = t.status !== "unknown";
  $("resolveForm").reset();
  $("outcome").options[0].textContent =
    t.stage === "create"
      ? "已找到广告计划"
      : "已找到上传素材，结束本地任务并转平台人工处理";
  $("recheck").hidden =
    !["material_pending", "awaiting_approval"].includes(t.status) &&
    !(t.status === "failed" && t.material && !t.dispatch_started);
  $("cancel").hidden = ![
    "draft",
    "upload_queued",
    "material_pending",
    "awaiting_approval",
    "create_queued",
  ].includes(t.status);
  $("events").textContent = JSON.stringify(
    { material: t.material, result: t.result, events: t.events },
    null,
    2,
  );
  if (!$("detail").open) $("detail").showModal();
}
$("account").onchange = () =>
  run(async () => {
    $("oauthLink").hidden = true;
    auth = null;
    current = null;
    await refresh();
  });
$("refresh").onclick = () =>
  run(async () => {
    await refresh();
    if (current && $("detail").open) await open(current.id);
  });
$("authorize").onclick = () =>
  run(async () => {
    const r = await api(
      "/qianchuan/accounts/" + $("account").value + "/authorize",
      {},
    );
    $("oauthLink").href = r.url;
    $("oauthLink").hidden = false;
    notice("授权链接已生成，10 分钟内有效。点击「前往千川授权」。");
  });
$("verify").onclick = () =>
  run(async () => {
    await api("/qianchuan/accounts/" + $("account").value + "/verify", {});
    await refresh();
  });
$("disconnect").onclick = () =>
  run(async () => {
    await api("/qianchuan/accounts/" + $("account").value + "/disconnect", {});
    await refresh();
  });
$("draftForm").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    if (!$("account").value) throw Error("请选择千川账户");
    const t = await api("/qianchuan/tasks", {
      account_id: $("account").value,
      job_id: $("job").value,
      name: $("name").value,
      product_id: $("product").value,
      aweme_id: $("aweme").value,
      title: $("title").value,
      budget: $("budget").value,
      roi2_goal: $("roi").value,
      is_aigc: $("aigc").value === "true",
    });
    await refresh();
    await open(t.id);
  });
};
$("consentForm").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    const t = current;
    const b = {
      reviewer: $("reviewer").value,
      note: $("note").value,
      confirmed: $("confirmed").checked,
    };
    const action = t.status === "draft" ? "upload" : "approve";
    if (action === "approve") b.snapshot_hash = t.snapshot_hash;
    await api("/qianchuan/tasks/" + t.id + "/" + action, b);
    await refresh();
    await open(t.id);
  });
};
$("recheck").onclick = () =>
  run(async () => {
    const id = current.id;
    await api("/qianchuan/tasks/" + id + "/recheck", {});
    await refresh();
    await open(id);
  });
$("cancel").onclick = () =>
  run(async () => {
    const id = current.id;
    await api("/qianchuan/tasks/" + id + "/cancel", {});
    await refresh();
    await open(id);
  });
$("resolveForm").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    const id = current.id;
    await api("/qianchuan/tasks/" + id + "/resolve", {
      outcome: $("outcome").value,
      ad_id: $("adId").value,
      reviewer: $("resolveActor").value,
      note: $("resolveNote").value,
      confirmed: $("resolveCheck").checked,
    });
    await refresh();
    await open(id);
  });
};
run(async () => {
  session = (await api("/session")).token;
  const [accounts, jobs] = await Promise.all([
    api("/distribution/accounts"),
    api("/jobs"),
  ]);
  options(
    $("account"),
    accounts
      .filter((a) => a.platform === "qianchuan")
      .map((a) => ({ id: a.id, label: a.name + " / " + a.advertiser_id })),
    "请选择账户",
  );
  options(
    $("job"),
    jobs
      .filter((j) => j.status === "ready")
      .map((j) => ({ id: j.id, label: j.title + " / " + j.id.slice(0, 8) })),
    "请选择已审核成片",
  );
  const chosen = new URLSearchParams(location.search).get("account");
  if (
    chosen &&
    accounts.some((a) => a.id === chosen && a.platform === "qianchuan")
  )
    $("account").value = chosen;
  else if ($("account").options.length > 1) $("account").selectedIndex = 1;
  await refresh();
});
// Poll the list, never replace an open approval or a form the user is editing.
setInterval(() => {
  if (!busy && !$("detail").open) run(refresh);
}, 10000);
