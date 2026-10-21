"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const states = {
    awaiting_approval: "等待人工确认",
    queued: "等待生成投放包",
    exporting: "正在导出",
    awaiting_manual: "等待人工投放",
    submitted: "已登记提交回执",
    active: "人工登记：投放中",
    paused: "人工登记：已暂停",
    rejected: "人工登记：平台拒绝",
    completed: "人工登记：已结束",
    failed: "失败",
    cancelled: "已取消",
    fetching: "读取报表中",
  };
  const transitions = {
    awaiting_manual: ["submitted"],
    submitted: ["active", "paused", "rejected", "completed"],
    active: ["paused", "completed", "rejected"],
    paused: ["active", "completed", "rejected"],
  };
  let token = "",
    accounts = [],
    tasks = [],
    current = null,
    busy = false,
    timer,
    pendingSync = false,
    renderedQuery = "";
  const show = (text) => {
    $("notice").textContent = text;
    $("notice").hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => {
      $("notice").hidden = true;
    }, 7000);
  };
  async function api(path, options = {}) {
    const opts = {
      ...options,
      headers: { "X-Workflow-Token": token, ...options.headers },
    };
    if (options.body && !(options.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(options.body);
    }
    const r = await fetch("/api" + path, opts);
    const data = await r.json();
    if (!r.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : "输入不符合要求，请检查字段",
      );
    return data;
  }
  async function action(fn) {
    if (busy) return;
    busy = true;
    const buttons = [
      ...document.querySelectorAll(
        "button:not(dialog form[method] button), #account, #startDate, #endDate",
      ),
    ];
    const disabled = buttons.map((b) => b.disabled);
    buttons.forEach((b) => (b.disabled = true));
    try {
      await fn();
    } catch (e) {
      show(e.message);
    } finally {
      buttons.forEach((b, i) => (b.disabled = disabled[i]));
      busy = false;
    }
  }
  const post = (path, body) => api(path, { method: "POST", body });
  const form = (id, fn) =>
    $(id).addEventListener("submit", (e) => {
      e.preventDefault();
      action(fn);
    });
  function choice(select, items, placeholder) {
    select.replaceChildren();
    if (placeholder) {
      const option = el("option", placeholder);
      option.value = "";
      select.append(option);
    }
    for (const [value, text] of items) {
      const option = el("option", text);
      option.value = value;
      select.append(option);
    }
  }
  function accountId() {
    if (!$("account").value) throw Error("请先添加并选择广告主账户");
    return $("account").value;
  }
  function range() {
    return {
      account_id: accountId(),
      start_date: $("startDate").value,
      end_date: $("endDate").value,
    };
  }
  function query() {
    return new URLSearchParams(range()).toString();
  }
  function value(v) {
    return v === null || v === undefined ? "—" : v;
  }
  function percent(v) {
    return v === null ? "—" : `${(Number(v) * 100).toFixed(2)}%`;
  }
  async function loadAccounts(selected) {
    accounts = await api("/distribution/accounts");
    choice(
      $("account"),
      accounts.map((a) => [
        a.id,
        `${a.name} · ${a.platform === "qianchuan" ? "千川" : "巨量引擎"} · ${a.advertiser_id}`,
      ]),
      accounts.length ? null : "请先添加账户",
    );
    if (selected) $("account").value = selected;
  }
  async function loadJobs() {
    const jobs = (await api("/jobs")).filter((j) => j.status === "ready");
    for (const id of ["job", "bindingJob"])
      choice(
        $(id),
        jobs.map((j) => [j.id, `${j.title} · ${j.id.slice(0, 8)}`]),
        "选择已审核成片",
      );
    if (!jobs.length)
      $("job").options[0].textContent = "暂无审核成片，请先完成剪辑审核";
  }
  async function loadTasks() {
    tasks = await api("/distribution/tasks");
    const list = $("tasks");
    list.replaceChildren();
    const filtered = tasks.filter((t) => t.account_id === $("account").value);
    if (!filtered.length)
      list.append(el("p", "当前账户暂无投放任务。", "muted"));
    for (const t of filtered) {
      const card = el("article", undefined, "task-card");
      const info = el("div");
      info.append(
        el("h3", t.snapshot.name),
        el(
          "p",
          `${states[t.status]} · 意向预算 ¥${t.snapshot.budget_cny} · 目标 ROI ${t.snapshot.target_roi}`,
        ),
      );
      const button = el("button", "查看与确认", "secondary");
      button.onclick = () => action(() => openTask(t.id));
      card.append(info, button);
      list.append(card);
    }
  }
  async function openTask(id) {
    current = await api("/distribution/tasks/" + id);
    const t = current;
    $("taskTitle").textContent = t.snapshot.name;
    const summary = $("taskSummary");
    summary.replaceChildren(
      el("p", states[t.status], "badge"),
      el(
        "p",
        `广告主 ${t.snapshot.account.advertiser_id} · ${t.snapshot.account.name}`,
      ),
      el(
        "p",
        `意向预算 ¥${t.snapshot.budget_cny} · 目标 ROI ${t.snapshot.target_roi}`,
      ),
      el("p", t.snapshot.budget_scope, "muted"),
      el("p", `确认快照 SHA256：${t.snapshot_hash}`, "hash"),
    );
    const video = t.snapshot.artifacts.find((a) => a.kind === "video");
    summary.append(el("p", `成片 SHA256：${video.sha256}`, "hash"));
    $("videoLink").href = `/api/jobs/${t.job_id}/artifacts/video`;
    $("packageLink").hidden = !t.package_path;
    $("packageLink").href = `/api/distribution/tasks/${t.id}/package`;
    $("approvalForm").hidden = t.status !== "awaiting_approval";
    $("approvalForm").reset();
    $("cancelTask").hidden = !["awaiting_approval", "queued"].includes(
      t.status,
    );
    const next = transitions[t.status] || [];
    $("receiptForm").hidden = !next.length;
    $("receiptForm").reset();
    choice(
      $("receiptStatus"),
      next.map((s) => [s, states[s]]),
    );
    $("adId").value = t.receipt?.ad_id || "";
    $("adId").readOnly = !!t.receipt;
    $("taskEvents").textContent = t.events
      .map(
        (
          e,
        ) => `${new Date(e.created_at * 1000).toLocaleString()} · ${states[e.status]}
${e.detail}`,
      )
      .join("\n\n");
    if (!$("taskDialog").open) $("taskDialog").showModal();
  }
  form("accountForm", async () => {
    const a = await post("/distribution/accounts", {
      name: $("accountName").value,
      platform: $("platform").value,
      advertiser_id: $("advertiser").value,
      auth_account_id: $("authAlias").value,
    });
    $("accountForm").reset();
    await loadAccounts(a.id);
    await loadTasks();
    await dashboard();
    show("账户已保存；平台授权需单独配置。");
  });
  form("taskForm", async () => {
    const t = await post("/distribution/tasks", {
      job_id: $("job").value,
      account_id: accountId(),
      name: $("planName").value,
      budget: $("budget").value,
      target_roi: $("targetRoi").value,
    });
    await loadTasks();
    await openTask(t.id);
  });
  form("approvalForm", async () => {
    await post(`/distribution/tasks/${current.id}/approve`, {
      snapshot_hash: current.snapshot_hash,
      reviewer: $("approver").value,
      note: $("approvalNote").value,
      confirmed: $("approvalCheck").checked,
    });
    await openTask(current.id);
    await loadTasks();
    show("已确认，等待生成本地投放包。");
  });
  form("receiptForm", async () => {
    await post(`/distribution/tasks/${current.id}/receipt`, {
      status: $("receiptStatus").value,
      ad_id: $("adId").value,
      reviewer: $("receiptActor").value,
      note: $("receiptNote").value,
      confirmed: $("receiptCheck").checked,
    });
    await openTask(current.id);
    await loadTasks();
    show("人工核验记录已保存。");
  });
  $("cancelTask").onclick = () =>
    action(async () => {
      await post(`/distribution/tasks/${current.id}/cancel`, {});
      await openTask(current.id);
      await loadTasks();
    });
  $("refreshTasks").onclick = () =>
    action(async () => {
      await loadJobs();
      await loadTasks();
    });
  $("account").onchange = () =>
    action(async () => {
      await loadTasks();
      await dashboard();
    });
  form("filterForm", dashboard);
  form("importForm", async () => {
    const data = new FormData();
    for (const [k, v] of Object.entries(range())) data.append(k, v);
    data.append("actor", $("importActor").value);
    data.append("confirmed", String($("importCheck").checked));
    if ($("importWindow").value.trim()) data.append("attribution_window", $("importWindow").value.trim());
    data.append("context_confirmed", String($("importWindowCheck").checked));
    data.append("file", $("reportFile").files[0]);
    await api("/reports/import", { method: "POST", body: data });
    $("importCheck").checked = false;
    await dashboard();
    show("报表已校验并保存来源。");
  });
  form("syncForm", async () => {
    await post("/reports/syncs", { ...range(), actor: $("syncActor").value });
    await loadSyncs();
    show("已加入只读报表同步队列。");
  });
  form("bindingForm", async () => {
    await post("/reports/bindings", {
      account_id: accountId(),
      material_id: $("materialId").value,
      job_id: $("bindingJob").value,
      actor: $("bindingActor").value,
      confirmed: $("bindingCheck").checked,
    });
    $("bindingCheck").checked = false;
    await dashboard();
    show("素材关联已保存。");
  });
  async function loadSyncs() {
    const syncs = await api(
      "/reports/syncs?account_id=" + encodeURIComponent(accountId()),
    );
    pendingSync = syncs.some((s) => ["queued", "fetching"].includes(s.status));
    $("syncs").replaceChildren(
      ...syncs
        .slice(0, 8)
        .map((s) =>
          el(
            "p",
            `${s.start_date} 至 ${s.end_date} · ${states[s.status] || s.status}${s.error ? " · " + s.error : ""}`,
          ),
        ),
    );
  }
  function draw(daily) {
    const width = 1000,
      height = 175,
      pad = 28;
    const max = Math.max(
      1,
      ...daily.flatMap((d) => [
        Number(d.totals.spend || 0),
        Number(d.totals.revenue || 0),
      ]),
    );
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 1000 210");
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      "每日花费和支付金额；精确数值见下表，未知值不画柱",
    );
    const step = (width - 2 * pad) / daily.length;
    daily.forEach((d, i) => {
      for (const [j, key, color] of [
        [0, "spend", "#2459cf"],
        [1, "revenue", "#36a198"],
      ]) {
        if (d.totals[key] === null) continue;
        const bar = document.createElementNS(ns, "rect");
        const h = (Number(d.totals[key]) / max) * (height - 25);
        Object.entries({
          x: pad + i * step + step * (0.12 + j * 0.38),
          y: height - h,
          width: step * 0.32,
          height: h,
          fill: color,
        }).forEach(([k, v]) => bar.setAttribute(k, v));
        const title = document.createElementNS(ns, "title");
        title.textContent = `${d.date} ${key === "spend" ? "花费" : "支付金额"} ¥${d.totals[key]}`;
        bar.append(title);
        svg.append(bar);
      }
      if (i % Math.max(1, Math.ceil(daily.length / 10)) === 0) {
        const text = document.createElementNS(ns, "text");
        text.setAttribute("x", pad + i * step + step / 2);
        text.setAttribute("y", "198");
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("font-size", "12");
        text.textContent = d.date.slice(5);
        svg.append(text);
      }
    });
    $("chart").replaceChildren(svg);
  }
  async function dashboard() {
    if (!accounts.length) {
      $("dashboard").hidden = true;
      return;
    }
    const q = query();
    const d = await api("/reports/dashboard?" + q);
    renderedQuery = q;
    $("dashboard").hidden = false;
    $("exportReview").href = "/api/reports/export?" + q;
    $("coverage").textContent =
      `${d.status === "complete" ? "数据完整" : d.status === "empty" ? "尚无报表" : "数据不完整"} · ${d.start_date} — ${d.end_date} · 缺少日期 ${d.missing_dates.length} 天；未知指标显示 —`;
    $("basis").textContent = d.basis;
    const cards = [
      ["花费（元）", value(d.totals.spend), "区间合计"],
      ["支付金额（元）", value(d.totals.revenue), "支付口径"],
      ["支付 ROI", value(d.ratios.payment_roi), "支付金额 ÷ 花费"],
      ["点击率", percent(d.ratios.ctr), "点击 ÷ 展示"],
      ["支付订单", value(d.totals.orders), "非利润指标"],
      ["每单成本（元）", value(d.ratios.cpa), "花费 ÷ 支付订单"],
      ["千次展示成本（元）", value(d.ratios.cpm), "花费 ÷ 展示 × 1000"],
      ["完播率", percent(d.ratios.completion_rate), "缺少完播次数时不推算"],
    ];
    $("kpis").replaceChildren(
      ...cards.map(([name, v, note]) => {
        const card = el("div", undefined, "kpi");
        card.append(el("span", name), el("strong", v), el("small", note));
        return card;
      }),
    );
    draw(d.daily);
    $("dailyRows").replaceChildren(
      ...d.daily.map((r) => {
        const tr = el("tr");
        for (const v of [
          r.date,
          r.covered ? "已覆盖" : "缺失",
          r.totals.spend,
          r.totals.revenue,
          r.totals.clicks,
          r.totals.orders,
        ])
          tr.append(el("td", value(v)));
        return tr;
      }),
    );
    $("materialRows").replaceChildren(
      ...d.materials.map((r) => {
        const tr = el("tr");
        for (const v of [
          r.material_id,
          r.binding ? r.binding.job_id.slice(0, 8) : "待关联",
          r.observed_totals.spend,
          r.observed_totals.revenue,
          r.ratios.payment_roi,
          r.reported_days,
        ])
          tr.append(el("td", value(v)));
        return tr;
      }),
    );
    $("batches").replaceChildren(
      ...d.batches.map((b) => {
        const card = el("div", undefined, "source-card");
        card.append(
          el(
            "p",
            `${b.source === "csv" ? "人工导入 CSV" : b.source === "qianchuan_api" ? "千川原生 API" : "Ocean Watch API"} · ${b.start_date}—${b.end_date} · 操作人 ${b.actor} · ${new Date(b.created_at * 1000).toLocaleString()}`,
          ),
          el("p", `SHA256 ${b.sha256}`, "hash"),
        );
        const link = el("a", "下载来源证据");
        link.href = `/api/reports/batches/${b.id}/source`;
        card.append(link);
        return card;
      }),
    );
    $("insights").replaceChildren(
      ...[d.attribution, ...d.notes].map((n) => el("li", n)),
    );
    await loadSyncs();
  }
  async function init() {
    token = (await api("/session")).token;
    const today = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Shanghai",
    }).format(new Date());
    $("startDate").value = today;
    $("endDate").value = today;
    const cap = await api("/distribution/capabilities");
    $("capabilities").textContent =
      `投放包可用 · Ocean Watch ${cap.runtime_verified ? "固定版本已校验" : "尚未安装"} · ${cap.message}`;
    await loadAccounts();
    await loadJobs();
    await loadTasks();
    await dashboard();
    const jobId = new URLSearchParams(location.search).get("job");
    if (jobId) $("job").value = jobId;
  }
  action(init);
  setInterval(() => {
    if (busy || document.hidden || !accounts.length) return;
    const pending = tasks.some((t) =>
      ["queued", "exporting"].includes(t.status),
    );
    if (pendingSync && !pending && !$("taskDialog").open)
      action(async () => {
        await loadSyncs();
        if (!pendingSync && query() === renderedQuery) await dashboard();
      });
    if (pending)
      action(async () => {
        await loadTasks();
        if (
          current &&
          $("taskDialog").open &&
          ["queued", "exporting"].includes(current.status)
        )
          await openTask(current.id);
      });
  }, 2500);
})();
