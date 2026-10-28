# D0 开源采用与来源

核对日期：2026-10-28。此次仅使用既有依赖与固定 Git 资源，无新增模型、第三方运行时或平台账号连接。

| 来源 | 固定依据 | 采用/未采用 |
| --- | --- | --- |
| [AI Cross Border Ecommerce Agent Toolkit](https://github.com/heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/cec98a9cab382d28dfe5b4ed0de444f33c455cb5) | MIT；固定上游 SHA | 选取七模块 README、05 视频的 Prompt/模板/规范/时长脚本及 03/06/07 的校验参考。脚本只读，不导入执行；葡语词速、补零与跨境费率不进入业务计算。 |
| [用户 Fork](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/705c0a905bc14c4312e8aa1f0ca7cdd03b58f2f1) | 国内资源提交 `705c0a905bc14c4312e8aa1f0ca7cdd03b58f2f1` | 仅新增 `Domestic/` 的 D0 说明与模块清单，原 `Agents/`/LICENSE 保持；各模块标明待实施，不声称七个 Agent 已经可运行。 |
| Pydantic / 既有 `Strict`、`Reference`、`Result` | 沿用本库 uv.lock 锁定版本 | 复用严格模型与旧结果；新增数据契约不另建验证框架，不改变旧 v1。 |
| 既有 `AgentService` | 本库基线 `54dbfc0` | 复用只读提案、版本检查、原子 request_id 回执和事件；不新增请求表或自动执行。 |
| 既有 `maintenance` / SQLite | 本库基线及标准库 | 复用备份验证、禁止覆盖的恢复、普通文件/软链接边界和已有 14→15 迁移。D0 不写新迁移。 |

完整 MIT 原文位于 `resources/domestic-toolkit/LICENSE`，其 SHA256 及所有文件来源见 `domestic-toolkit.lock.json`。根资源锁为审核后随应用版本分发的信任锚；哈希验证用于发现文件变化，不等同于上游真实性签名或素材授权。

Fork 由已登录的 GitHub CLI 创建并推送独立 `codex/domestic-d0` 分支；本轮没有浏览器登录或 Computer Use。GitHub 连接器当时不可用，使用已有 CLI 回退，没有读取/打印认证密钥。原 PDF 和示例媒体未进入剪序资源包。

资源上限：锁文件 512 KiB、单文件 1 MiB、包总量 4 MiB、最多 64 个文件。当前 27 文件 147,594 字节；没有新增常驻进程或推理资源开销。未开展冷推理提速测试，因为 D0 不修改识别后端、缓存门槛或视频执行器。

MCP SDK、平台 MCP、n8n、生成式模型留在后续经授权阶段。Remotion/FFmpeg、VoiceStudio 及其权重许可继续按已有独立说明处理，不因 Fork 的 MIT 而改变。
