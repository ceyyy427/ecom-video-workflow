# P3 巨量千川原生接口

P3 已实现应用配置、OAuth 授权/刷新、素材上传与查询、全域短视频带货广告创建、原生日报同步。默认关闭真实写入。开发验收使用 HTTP/平台测试替身；没有真实账户授权、素材上传、广告创建或消费。

## 启动与账号配置

在项目根目录运行：

```sh
uv sync --locked
uv run python scripts/qianchuan_setup.py --data var --port 8765
```

工具交互输入 App ID、Secret（隐藏输入）和每计划 `budget` 参数上限。不要把 Secret、token 或授权码发到聊天。macOS 使用 Security.framework 钥匙串；Linux 使用 secret-tool/Secret Service。Windows 本版原生授权不支持，原有本地剪辑与人工投放包可继续使用。没有明文凭据回退。

你需要在巨量开放平台准备自己的千川应用和可直接授权的广告主账户，并开通所用接口权限：OAuth 获取/刷新令牌、授权账户查询、视频上传、千川视频查询、全域短视频带货广告创建、千川素材报表。实际应用类别、审核与接口权限以你的开发者控制台为准。本版不展开代理商、组织或店铺授权层级。

配置回调：`http://127.0.0.1:8765/api/qianchuan/oauth/callback`。在平台登记同一地址。若平台不允许你的应用使用本地 HTTP 回调，停止授权；当前版本没有公网 HTTPS 回调代理，不要把本地服务直接暴露公网，需要按该应用要求扩展部署回调。

1. 启动 `uv run python -m ecom_video --data var --port 8765`，打开 `http://127.0.0.1:8765`。
2. 在“投放与复盘”添加千川账户，填写真实广告主 ID；再进入“千川原生投放”。Ocean Watch 授权别名对原生接口无效。
3. 点击“生成授权链接”→“前往千川授权”，使用有该广告主权限的账号确认。链接 10 分钟过期且仅能使用一次。授权必须包含登记的直接广告主。
4. 返回原页面刷新/核验，状态应为“广告主已授权”。仅完成授权不会上传或创建广告。更改应用配置或重新授权会使旧确认失效。
5. 准备进行真实写入时，先停止服务，再运行：

```sh
ECOM_QIANCHUAN_WRITES=1 uv run python -m ecom_video --data var --port 8765
```

`.env` 文件不会自动读取。此开关对该进程所有原生任务生效。默认启动不带开关仍可查看、授权和只读同步。默认启动后如果领取到了旧的已确认队列，任务会失败并停住，不会偷偷延迟到未来开启时重发。

## 上传与最终人工确认

选择经过既有审核流程的成片，填写商品 ID、抖音号 `aweme_id`、计划名、创意标题、budget、目标 ROI2，并明确选择 AIGC 属性。ID 按字符串输入，避免浏览器大整数精度损失；精确请求预览由后端序列化为文本。

- 保存草稿不调用平台。
- 确认上传：核对广告主、视频使用权和 AIGC 属性，才进入后台上传。复制并核对本地 SHA256 后上传，multipart 携带 MD5。上传返回的视频 ID、素材 ID、封面 ID 必须齐全。
- 素材库可能延迟可见，每 30 秒查询一次，最多 20 次，然后等待你手动“重新查询素材并生成预览”。查询核对广告主、视频 ID、素材 ID、MD5 和竖版类型，不表示平台审核通过。
- 最终确认：展示账户、商品、预算、目标 ROI2、精确 JSON 请求及摘要；需要填写确认人、核对说明并勾选费用确认。预览与确认最多有效 15 分钟。授权、配置或内容变化后旧确认不可用。
- 当前创建模板：一个商品、一个已上传竖版视频；`VIDEO_PROM_GOODS`、`SMART_BID_CUSTOM`、`SCHEDULE_FROM_NOW`；关闭智能优选素材 `smart_select_material=false`，设置 `hide_in_aweme=true`。计划名自动带任务 ID 后缀用于查找。
- `budget` 是平台预算参数；本机上限不是累计账户消费上限。预算周期、平台最小预算、竞价资格、商品权限、账户可投类型和素材限制需在真实账户联调核验。目标 ROI2 与看板“支付金额/花费”不是同一口径。
- 平台接受创建后可能立即产生费用。此版本不提供自动停投、调预算或智能优化；请在平台管理运行中计划。

## 故障与人工核验

平台写入只派发一次，绝不自动重发。OS 进程锁覆盖发送直到完成；即使租约过期，只要旧执行进程还活着并持锁，就不能恢复为可人工解除的任务。若进程挂起，请先停止旧服务/工作进程，确认其已退出，再重启恢复与核验；不能只因等待很久就认为请求不会再发出。网络断开、无有效回执、进程在派发后中断等情况标为“结果不明”。同账户/成片的其他写入也会停止。

先去平台核对广告主、带后缀的计划名、时间和素材 MD5。找到广告计划则登记计划 ID；找到上传素材则结束本地流程并转平台人工处理（本版不从不完整上传回执猜测封面 ID）；只有确实确认该写入未产生时，才登记“未产生”。人工记录标为 `human_recorded`，不假装 API 核验。确认未产生后，另建草稿并重新审批。不要仅凭请求超时就宣告未创建。

取消仅取消尚未派发的本地步骤；不会删除平台素材或取消已创建广告。授权刷新结果不明时要求重新授权，不重复使用可能已轮换的 refresh token。

## 数据复盘

“投放与复盘”中的同步操作：账户存在原生授权记录时使用原生千川 API；无原生记录才使用独立 Ocean Watch。原生授权过期/断开会报错，不自动切换授权身份。原生来源显示“千川原生 API”，最多 7 天、每次快照最多 5000 行，完整抓取才原子入库。任一天或任何分页失败，整批不应用；缺失指标保持 unknown。报表仅保留白名单规范化字段与 request_id，不保存任意上游内容或 token。平台素材 ID 与本地成片可在复盘页人工绑定。

## 本地接口

所有修改路由沿用本地同源与 `X-Workflow-Token`。只有 GET OAuth 回调允许跨站导航，以一次性 state 验证。

| 路由 | 功能 |
|---|---|
| GET `/api/qianchuan/accounts/{id}` | 公共配置/授权状态，无密钥 |
| POST `/api/qianchuan/accounts/{id}/authorize` | 生成一次性授权链接 |
| GET `/api/qianchuan/oauth/callback` | 消费 state、换取令牌、验证广告主 |
| POST `/api/qianchuan/accounts/{id}/verify`、`disconnect` | 只读核验 / 本地断开 |
| POST `/api/qianchuan/tasks` | 基于已审核成片创建草稿 |
| GET `/api/qianchuan/tasks?account_id=...`、`/tasks/{id}` | 列表/含审计记录的详情 |
| POST `/api/qianchuan/tasks/{id}/upload` | 上传人工确认 |
| POST `/api/qianchuan/tasks/{id}/recheck` | 重新核验素材、重建预览 |
| POST `/api/qianchuan/tasks/{id}/approve` | 带 snapshot_hash 的最终费用确认 |
| POST `/api/qianchuan/tasks/{id}/cancel`、`resolve` | 取消后续步骤 / 人工结果核验 |

原生状态：`draft → upload_queued → uploading → material_pending ↔ checking_material → awaiting_approval → create_queued → creating → submitted`。另有 `failed / unknown / cancelled`。`submitted` 只代表拿到计划 ID，不代表平台已通过审核或正在投放。

SQLite v4 新增 OAuth 会话、授权引用、原生任务、事件表；保留 P2 人工投放表。业务库仅保存凭据引用、有效期与授权状态；Secret/token 保存在系统安全存储。备份数据库不能备份 token，迁移机器需要重新配置授权。

## 验证与依据

- `uv run pytest -q`：默认跳过需要 OS 凭据库的显式集成测试。
- `ECOM_TEST_KEYCHAIN=1 uv run pytest -q`：macOS 使用独立随机命名空间的无敏感测试值，写/读/更新/删除后清理。
- `uv run --group browser python scripts/browser_p3.py`：独立临时数据目录，实际 Chromium/FFmpeg，注入内存凭据和平台响应测试替身。真实平台请求数为 0。
- 代码契约来源及未核验边界：[P3 接口来源](P3_CONTRACTS.md)。
