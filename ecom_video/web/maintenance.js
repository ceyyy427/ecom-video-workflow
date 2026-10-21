"use strict";
const checkButton = document.getElementById("deliveryCheck");
checkButton.addEventListener("click", async () => {
  const status = document.getElementById("deliveryCheckStatus");
  const results = document.getElementById("deliveryCheckResults");
  checkButton.disabled = true;
  results.replaceChildren();
  status.textContent = "正在检查本机依赖与数据版本…";
  try {
    const response = await fetch("/api/system/check", {cache: "no-store"});
    if (!response.ok) throw new Error("check_failed");
    const data = await response.json();
    const add = text => {
      const li = document.createElement("li"); li.textContent = text; results.append(li);
    };
    status.textContent = data.ready ? "核心依赖检查通过；请继续核对模型、授权和人工审核。" : "有未就绪项目，请按下方提示处理。";
    data.checks.forEach(row => add(`${row.status === "ok" ? "✓" : "待处理"} ${row.name}：${row.action}`));
    add(`数据库：${data.database.status === "ok" ? "完整性检查通过，版本 " + data.database.schema : data.database.status === "not_created" ? "尚未创建" : "版本不支持或校验失败，请先停止服务并检查备份"}`);
    add(`磁盘剩余 ${(data.free_bytes / 1024 ** 3).toFixed(1)} GiB。`);
    add(data.voice.configured ? "配音配置已检测到；本次未调用服务验证权限。" : "配音未配置；可上传成品配音或在本机设置语音 Key。");
    const pending = Object.values(data.database.pending).reduce((a, b) => a + b, 0);
    if (pending) add(`存在 ${pending} 项待执行/运行任务或计算租约，完成暂停/取消前不能备份。`);
    if (data.platform_writes_enabled) add("当前环境开启了平台写入开关；本流程不需要，请停止服务并关闭 ECOM_QIANCHUAN_WRITES 后再启动。");
    data.limits.forEach(add);
  } catch (_) {
    status.textContent = "自检读取失败；请确认本机服务正在运行，或在终端使用维护命令查看。";
  } finally {
    checkButton.disabled = false;
  }
});
