# P13：统一 Agent 工具入口

P13 已提供四个本机读取工具：`project.read`、`project.check`、`creative.recommend`、`reports.dashboard`。它们保存一次读取结果及审计事件；不会启动识别、选段、分镜、渲染或投放。未来执行机制属于 P14。

事实、文稿、风格、配音听核和成片审核继续使用现有页面。`creative.recommend` 读取已确认事实与文稿生成的三个方向，不替用户选择；资料不齐时返回 `HUMAN_CONFIRMATION_REQUIRED`。`project.check` 只检查元数据，不解码素材，也不验证商品事实真假。

## 开启与发现

默认关闭。仅对当前启动进程开启（无需把密钥写入命令）：

```sh
ECOM_AGENT_ENABLED=1 .venv/bin/python -m ecom_video --data var
.venv/bin/python -m ecom_video.agent_cli capabilities
curl -s http://127.0.0.1:8765/api/agent/capabilities
```

CLI 的后续 `run/get/events` 也需在该进程环境设置 `ECOM_AGENT_ENABLED=1`。`capabilities` 和 `--help` 不打开数据库；参数错误、开关关闭也不会由 CLI 创建数据库。工具目录返回严格输入/结果 JSON Schema、前置确认、能力与大小限制；Provider 当前仅有数据契约，没有接入新传输或模型。

## 一份命令同时用于 CLI 与 HTTP

先通过既有 `GET /api/customer-projects/{project_id}` 读取 `revision` 与 `product.revision`；下例 ID 和两个版本需替换为实际值，再保存为本机 `command.json`：

```json
{
  "schema_version": 1,
  "request_id": "p13-check-001",
  "operation": "project.check",
  "input": {
    "project_id": "00000000000000000000000000000000",
    "expected_revision": 0,
    "expected_product_revision": 0
  }
}
```

```sh
ECOM_AGENT_ENABLED=1 .venv/bin/python -m ecom_video.agent_cli --data var run --input command.json
ECOM_AGENT_ENABLED=1 .venv/bin/python -m ecom_video.agent_cli --data var get RUN_ID
ECOM_AGENT_ENABLED=1 .venv/bin/python -m ecom_video.agent_cli --data var events RUN_ID --after-seq 0 --limit 100
```

`--input -` 可读标准输入。stdout 是 JSON；安全诊断写 stderr；退出码 0 成功、1 运行/开关失败、2 输入错误。帮助输出为普通文本。

HTTP：`POST /api/agent/runs` 使用同一 JSON；继承 `X-Workflow-Token` 与同源限制，令牌从既有 `GET /api/session` 获取，勿放入命令 JSON。`GET /api/agent/runs/{run_id}` 查询结果；`GET /api/agent/runs/{run_id}/events?after_seq=0&limit=100` 查询事件，下一页用返回的 `next_seq`。游标范围 0–9223372036854775807，每页最多 100。

三个项目工具都校验客户项目和产品两个版本；改稿即使未改变客户项目版本也会使新请求失效。复用 request_id 且输入相同会返回历史原结果；不同输入返回 409。读取最新状态请使用新 request_id 和当前两个版本。

报表命令的 `operation` 为 `reports.dashboard`，`input` 替换为：

```json
{"account_id":"00000000000000000000000000000000","start_date":"2026-10-01","end_date":"2026-10-17","material_limit":20}
```

日期为 ISO 格式，含首尾最多 31 天，素材条数 1–100。沿用现有 Decimal 指标口径及缺失/零区分；仅读取已导入数据，不发起同步。保存的是当时读取结果，不等同于 P15 的冻结复盘证据；不提供计划/人群比较或因果结论。

## 记录、错误与安全边界

`proposed` 表示读取建议已就绪，绝不表示成片完成。有效工具调用失败保存 `failed` 和安全错误；非法输入、关闭开关、请求 ID 冲突返回 `rejected`，不保存原始拒绝输入。每个持久化运行有 `request_accepted`、`proposal_ready/tool_failed` 两条递增事件，同事务提交；查询一个已保存的失败运行仍返回 HTTP 200。

错误包含 `code/stage/retryable/outcome_uncertain/safe_message/evidence_refs`；当前无自动重试和计费调用。常见代码：`INVALID_INPUT` 422、`AGENT_DISABLED` 403、`NOT_FOUND` 404、`REQUEST_CONFLICT/STALE_INPUT/HUMAN_CONFIRMATION_REQUIRED` 409、`DOMAIN_REJECTED` 422、`OUTPUT_LIMIT` 413、`INTERNAL_ERROR` 500。POST 成功为 201。Host/Origin/token 传输层拒绝仍保留旧接口的错误格式。

命令不接受任意路径、Shell、SQL、URL、密钥或代签审核字段；CLI 本机输入文件路径属于入口参数，不进入工具命令。命令上限 64 KiB、结果 256 KiB。记录包含用户文稿等本机业务信息，仍需维护者管理数据目录权限；此处审计可追踪但不防本机篡改。

## 迁移与回退

启动新版 Store 会自动升级至 schema v9（即使 Agent 开关关闭），只新增 `agent_runs/agent_events`；不改旧任务、快照或审批。升级前停机备份整个数据目录；数据库单文件备份用于迁移核对，不能替代素材备份。

软回退：关闭 `ECOM_AGENT_ENABLED` 并重启新版，继续使用原制作页面。旧版只支持 v8，不能直接打开 v9；硬回退须停机导出新增记录，再恢复匹配 v8 的备份与源码。不要手改 `user_version`。

离线可执行验收及证据见 P13_ACCEPTANCE.md（历史记录或本机文件，未随公开版分发）。
