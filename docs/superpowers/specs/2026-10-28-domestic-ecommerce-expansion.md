# 国内电商运营 Agent 套件升级设计

日期：2026-10-28。状态：已通过设计；D0 实施记录见 [验收](../../DOMESTIC_D0_ACCEPTANCE.md)，D1–D6 候选实现、安装/升级及工程回归完成，最终独立复核与用户验收待处理。实际覆盖和未验项以[交付验收](../../DOMESTIC_ACCEPTANCE.md)为准；工程夹具不是客户确认，最终发布仍由用户决定。

## 目标与仓库关系

将项目扩展为面向抖音、小红书的本机运营套件：商品与人群定位 → 内容与封面 → 视频制作 → 客户自行发布/投放 → 数据及评论回流。视频制作继续使用剪序；非电商想法创作入口保留。

建议采用两个职责明确的仓库：

1. Fork `heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit`，保留上游七模块与历史，在 `Domestic/` 新增中文平台的 Prompt、模板、规范、案例和导出脚本。它是方法与资源的维护源。
2. `ecom-video-workflow` 继续作为可安装应用及执行引擎的维护源。固定版本同步 Fork 的资源包，增加运营入口和适配器；不复制另一套渲染器、数据库或审核状态。
3. Mac 客户只安装一个剪序应用包；Fork 首页链接到该交付包。资源包记录 Fork URL、上游 SHA、国内修订 SHA、文件哈希与许可。后续上游更新经过差异审阅再同步，不在运行时拉取 `main`。

这样既能基于 Fork 扩展七类运营方法，也能保留已验证的工作台、客户资料和制作能力。D0 已创建 [用户 Fork 国内分支](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/codex/domestic-d0/Domestic)，后续 D1/D4/D5 方法修订保留在本地 codex/domestic-suite 候选分支；未获最终发布前不推送，发行锁和文本随包。

## 已核对的事实与限制

证据分类：**事实**表示本轮直接读到文件/源码；**设计**表示拟新增；**待验证**表示尚未安装、实测或获得平台权限。

| 对象 | 本轮证据与判断 |
| --- | --- |
| 上游工具箱 | **事实**：固定提交 `cec98a9cab382d28dfe5b4ed0de444f33c455cb5`；MIT；七模块由 Prompt、模板、案例、说明和部分确定性 Python 脚本组成。根 README 明确定位为方法工具箱。仓库创建于 2026-10-13，截至核对未归档；维护历史较短，不能仅凭模块“完成”标签视为成熟生产系统。 |
| 上游视频模块 | **事实**：输出脚本、分镜、逐镜 Prompt、配音文案和字幕；README 明确不渲染，实际音画同步仍需其他工具及人工。适合复用规划结构，不能代替剪序。 |
| 上游时长脚本 | **事实**：`video_timing.py` 使用 `len(text.split()) / wps`，默认葡语 2.5 词/秒。中文不能直接照用；正式时间轴继续来自实际声音与本机对齐。 |
| 上游广告/评论脚本 | **事实**：存在默认数值补零和平台费率预设。只借鉴计算/解读分离与诊断结构；不覆盖剪序已有缺失值、口径、冻结和描述性比较逻辑，不照搬跨境费率。 |
| 本项目 | **事实**：基线提交 `54dbfc06b40624e937a5053771549ecd84f752f8`；已有 P13/P14 契约与有界执行、六个 7 秒真实预览、逐镜版本、人工审核、冻结复盘及下一版假设。六预览当前是有限配方和规则编排，不能称为任意风格自由生成。 |
| 本项目声音 | **事实**：已有火山、上传声音和独立 VoiceStudio 本机桥接。VoiceStudio 应用/模型许可分别核对，不宣称所有音色免费商用；不自动转为付费云配音。 |

## 复用评估

| 来源与固定依据 | 采用方向 | 当前不采用/实施门槛 |
| --- | --- | --- |
| [上游工具箱](https://github.com/heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/cec98a9cab382d28dfe5b4ed0de444f33c455cb5)；[MIT](https://github.com/heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit/blob/cec98a9cab382d28dfe5b4ed0de444f33c455cb5/LICENSE) | 01 市场、02 定位、03 商品内容、04 图片、05 视频、06 复盘、07 评论的输入/输出/自检封装；证据与确定性脚本分离 | 不引入整份内部 SOP PDF 或示例媒体；不照搬葡语词速、Shopee/ML 费率、平台规则、预算调整执行。文字/脚本复制须保留 MIT。 |
| [官方 MCP Python SDK v2.3.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0)；MIT；该 tag 的 pyproject 要求 Python ≥3.10、Pydantic ≥2.12、httpx2 ≥2.10 | 候选可选 MCP 客户端/服务端；优先标准 SDK，不自行实现协议；本项目 Python ≥3.11 满足其解释器下限 | **待验证**：先在独立环境核对固定版本依赖与现有锁文件兼容，再记录包及哈希；不用 `main` API 代替版本契约，不安装完整额外 CLI 工具链。 |
| [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp/tree/7797fd375aba02dcd33afe143f6bee13e5870859)；Apache-2.0；Go 1.24、Rod/浏览器 | 学习工具分类、参数与输出形式；保留未来适配位 | **事实**：源码创建浏览器；当前不安装/调用登录、搜索、发布、互动工具。MCP 不会使浏览器自动化变成官方 API，也不会自动提供使用权。 |
| [douyin-mcp](https://github.com/Kuhakucai/douyin-mcp/tree/53c888a5e1d83ea70978e71432ad8774707d69b7)；AGPL-3.0；Playwright | 参考数据新鲜度、覆盖率、缺失说明、缓存的设计 | 当前不嵌入/分发或调用浏览器同步；AGPL 与平台权限分别评估，不能把独立进程说成自动免除许可义务。 |
| [抖音官方数据接口](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/video-data/)与[授权说明](https://open.douyin.com/platform/resource/docs/develop/permission/overall-permission) | D3 申请/授权后的本人作品只读数据；无权限保留导出导入 | **事实**：`video.data` 需申请且用户授权；查询的是 token 对应用户作品。特定读接口使用 POST，读写判断按能力语义而非 HTTP 方法。不能预先保证账户能获批。 |
| [小红书官方文档](https://open.xiaohongshu.com/document/developer/file/17)与[电商 API 目录](https://open.xiaohongshu.com/document/api?apiId=5721&apiNavigationId=5&gatewayId=103&gatewayVersionId=1661&id=35) | 已核验公开文档、客户授权导出和可获批接口的适配 | **事实**：可见商品/订单等电商接口；**待验证**：未取得通用笔记数据 API 的可用凭证和契约。不能承诺“登录即自动读取全部笔记”；D3 默认人工导入。 |
| [n8n 许可](https://github.com/n8n-io/n8n/blob/b6520fb6aef75f1aec74ac82298a9cc4920e8b72/LICENSE.md) | 后期可选外部 HTTP 触发样例，复用现有工作流 API | Sustainable Use License，有使用/分发边界，不按 MIT 处理；不嵌入交付包、不替代本机队列，不把调度层声称为视觉推理提速方案。 |
| 已接入的 Remotion/FFmpeg、Shotcraft、Lemo、Narrato 字幕兼容与 `spoken_copy.py` | 持续复用当前渲染、有限卡片、声音时钟和口语化守则；参考现有 third-party 声明 | 不再下载一套平行生产引擎；不将参考卡数量当成可执行模板数量；Remotion 许可继续按既有声明单独核对。 |

D0 已固定下载工具箱参考资源且未执行上游脚本；D3 官方 MCP 2.3.0 在隔离环境完成内存协议验证，作为可选依赖，不默认安装或调用。官方抖音只读契约已核对并模拟验证，真实账号权限/回调仍待实接；浏览器 MCP 与 n8n 不嵌入运行。详见各期采用依据，以下设计表保留最初评估语境。

## 系统结构与 Agent 边界

```mermaid
flowchart LR
  I[想法/商品/已授权素材/人群] --> B[国内运营 Brief 与证据]
  B --> P[Agent 提出六方案与工具计划]
  P --> H[人工核对事实/文稿/方向]
  H --> G[契约与版本校验]
  G --> R[既有有界 Runtime 与资源租约]
  R --> W[识别/选段/声音对齐/Remotion/FFmpeg]
  W --> Q[人工听核/分镜及成片审核]
  Q --> E[发布交接包]
  E --> U[客户自行发布或投放]
  U --> D[官方只读/人工导入]
  D --> F[冻结复盘与评论洞察]
  F --> P
```

Agent 提升规划、检索和工具选择效率；实际编码仍交给确定性执行器。不预设增加 Agent 就能缩短模型推理时间。

可恢复失败：只对幂等本机计算从最近有效检查点重试；模型不就绪回到已有手动/规则路径。回退改变文稿、素材、时长或方案依据时形成新版本，退回相应人工确认。版本过期、事实不足、素材缺口、低质量结果必须明确停下；结果不明不得自动重发，取消不重启。平台写入在全部阶段都不在能力白名单中。

## 共用协议（设计）

- `SuiteBrief.v1`：`project_id, platform, objective, audience, tone, product_ref, sku_color_policy, evidence_refs, material_refs, duration_s, constraints`。可选 `content_brief` 完整保留旧请求的想法、来源及素材归属；D0 不冒充已将跨项目素材解析到新项目。不在旧 v1 增加必填字段或取消 24 秒限制。
- `SuitePlan.v1`：`plan_id, revision, basis, brief_ref, six_options, tasks, gaps, cost_policy, source_versions`。每方案含 `narrative, hook, script_refs, storyboard_ref, voice_profile, render_recipe, evidence_refs, feasibility`；默认三种叙事各两种视觉编排，但须通过差异校验，不仅换色换标题。
- `ToolSpec.v1`：`id, version, input_schema, output_schema, effects, transport, requires_human, timeout_s, retries, resource_class, license_ref`。工具只传对象 ID/哈希，不接受任意路径、shell、Python/JS 代码或任意远程 URL。
- `OpsResult.v1`：`status, output_refs, evidence_refs, warnings, error, usage, checkpoint_ref`；状态为 `completed/needs_human/failed/unknown`，适配既有运行记录，不修改 P13 旧结果格式。
- `Observation.v1`：`platform, account_ref, content_ref, observed_at, metric_date, dataset_kind, metric_definition, values, missing_reasons, source_ref`。`organic/ad` 分开；累计观测不能冒充每日增量。
- `PublicationPack.v1`：成片版本/哈希、审核状态、封面、标题正文/话题、字幕、来源、客户发布清单；不含账号密钥，不产生发布/投放动作。

## 不变条件与交付下限

- 保留现有 UI 风格与制作入口；新增运营选择、连接状态及交接包，技术字段默认折叠；不是再建另一套桌面应用。
- 本机模型优先；云模型/配音沿用明确授权和计费确认；缺本机能力不能偷偷改用云服务。
- 不使用 Computer Use，包括以第三方 MCP 作为绕道的浏览器操作；Remotion 的离线渲染浏览器按既有用途保留，不访问平台账号。
- 不自动发布、投放、调价、回复评论或私信；人工发布/投放与平台只读数据分开。
- 事实、文稿、风格/最终分镜、听核、逐镜与成片审核绑定实际版本；工程夹具不得作为客户签收。
- 旧任务、新旧 `ContentBrief`、历史审批、源素材、备份均须兼容；schema 只增量迁移，回滚用独立目录的升级前备份。
- 首次发布验收覆盖藏蓝软壳衣（私有授权素材）与另一许可实拍品类；公开 README 只能使用明确允许公开的媒体。
- 实际速度报告分别给出冷启动、已有缓存、Agent/固定工作流路径的实测；同款、主体可见、动作完整的门槛不能降低。
