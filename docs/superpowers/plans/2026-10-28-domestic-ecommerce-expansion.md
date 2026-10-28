# 国内电商运营 Agent 套件分阶段执行清单

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于上游运营工具箱的 Fork，将剪序扩展为抖音/小红书的商品定位、内容生产、视频交付、投后复盘与评论迭代套件。

**Architecture:** Fork 维护国内运营方法与资源；现有仓库继续维护 UI、数据库和制作引擎。Agent 通过严格方案/工具契约调用已有 Runtime，确定性工作流承接本机执行与安全恢复；所有客户确认继续有效。

**Tech Stack:** 既有 Python 3.11+/FastAPI/Pydantic/SQLite、Remotion/FFmpeg、静态工作台、本机模型与独立 VoiceStudio；MCP 官方 SDK 按 D3 独立验证后可选加入。

**Spec:** [国内电商运营套件设计](../specs/2026-10-28-domestic-ecommerce-expansion.md)。日期 2026-10-28；本清单最初为规划，D0 实施与验收见 [D0 记录](../../DOMESTIC_D0_ACCEPTANCE.md)。D1–D6 已完成候选实现、安装/升级及工程回归，最终独立复核和用户实际验收仍待处理。后续授权改为连续推进到 D6，见[执行计划](2026-10-28-domestic-d2-d6-execution.md)。真实账号实接、客户听审和发布继续待办。已完成的六动态预览是复用基线，不重复立项。

## Global Constraints

- 保留现有 UI 风格与制作入口；新增运营选择、连接状态及交接包，技术字段默认折叠；不是再建另一套桌面应用。
- 本机模型优先；云模型/配音沿用明确授权和计费确认；缺本机能力不能偷偷改用云服务。
- 不使用 Computer Use，包括以第三方 MCP 作为绕道的浏览器操作；Remotion 的离线渲染浏览器按既有用途保留，不访问平台账号。
- 不自动发布、投放、调价、回复评论或私信；人工发布/投放与平台只读数据分开。
- 事实、文稿、风格/最终分镜、听核、逐镜与成片审核绑定实际版本；工程夹具不得作为客户签收。
- 旧任务、新旧 `ContentBrief`、历史审批、源素材、备份均须兼容；schema 只增量迁移，回滚用独立目录的升级前备份。
- 首次发布验收覆盖藏蓝软壳衣（私有授权素材）与另一许可实拍品类；公开 README 只能使用明确允许公开的媒体。
- 实际速度报告分别给出冷启动、已有缓存、Agent/固定工作流路径的实测；同款、主体可见、动作完整的门槛不能降低。

## Review Focus

1. 中文无空格、型号和数值单位：不能使用葡语空格词数估算正式配音时间，旧图示不能显示修改前文稿；D1/D2 测试。
2. 客户素材不足、混款/混色、未知动作：只能提示缺口，不得用参考片或 AI 外观代替客户实拍证据；D1/D2 测试。
3. Agent 中断、重复提交、取消后迟到结果：不得重复渲染/采用、不丢版本、不得继续派发；D0/D2 测试。
4. MCP 宣称只读、文档注入及错误账户：能力提示不能代替本机白名单，外部内容不能自动增加权限；D3 测试。
5. 累计量/日增量、自然/付费、缺失/零混用，以及恢复后审批串版：必须拒绝混算并保留来源；D4/D6 测试。

## 阶段总览与先后依赖

| 阶段 | 优先级 | 可交付成果 | 依赖/开始条件 |
| --- | --- | --- | --- |
| D0：Fork 与共同底座 | P0 | 国内方法资源包、兼容协议、来源锁定与迁移基线 | 现在可开始；不需要客户平台账号 |
| D1：国内定位与内容方案 | P0 | 单一核心卖点、平台稿/封面方案、六个可解释方向 | D0 契约通过；直接复用既有六预览 |
| D2：视频 Agent 接通与兜底 | P0 | 从方向到 20–30 秒作品、失败恢复、逐镜修改 | D1；客户按版本确认，声音沿用现有配置 |
| D3：平台与 MCP 接入 | P1 | 可选连接器、官方只读/人工导入、发布交接包 | D0 后可做隔离验证；真实接口由账户获批决定 |
| D4：数据与评论闭环 | P1 | 冻结表现、评论问题→新版假设→对比 | D2+D3；真实数据不足时工程样例与实数分开 |
| D5：七模块业务扩展 | P2 | 市场研究、商品策略、图文封面与内容矩阵 | D1–D4 的主链路可用后逐模块发布 |
| D6：Mac 交付与试用 | 发布门槛 | 单安装包、客户指南、两品类验收、升级回滚 | 全部纳入发布范围的阶段通过；未过项禁用 |

最初拟分批发布；后续用户要求连续完成 D1–D6，全部保留本地候选，最后统一由用户验收发布。每个版本都执行 D6 的打包/回归门槛，不等全部功能写完才验证安装。此表是工作依赖，不是未经实测的工期承诺。

## 文件边界与接口（拟新增）

| 位置 | 职责 |
| --- | --- |
| Fork：`Domestic/{01_Market,02_Positioning,03_Content,04_Image,05_Video,06_Performance,07_Comments}/` | 各模块 `SKILL.md/prompts/templates/references/examples`；国内适配与来源声明，保留原 `Agents/` |
| 本库：`resources/domestic-toolkit/`、`docs/third-party/domestic-toolkit.lock.json` | 可分发资源快照与锁；不自动更新或执行上游代码 |
| `ecom_video/operations/contracts.py`、`resources.py`、`api.py` | 严格公共协议、资源读取与来源检查、薄 HTTP 适配 |
| `operations/positioning.py`、`content.py`、`media_pack.py` | 定位、中文内容和封面交接；复用原 facts/creative/renderer |
| `operations/tools.py`、`planner.py`、`execution.py` | 工具白名单、有限任务计划、桥接既有 Agent Runtime；不另开模型执行池 |
| `ecom_video/connectors/{contracts,registry,mcp_client,douyin_readonly,xhs_import}.py` | 固定连接器配置、只读/文件导入与标准输出 |
| `operations/observations.py`、`comments.py`、`research.py` | 保留观测口径、评论分类及确定性聚合、已授权市场资料分析 |
| `ecom_video/web/operations.{html,js,css}` | 沿用现有组件/样式的运营入口，链接原创意与剪辑工作台 |
| `scripts/accept_domestic_suite.py` | 各期隔离验收；每次写仓库外专用目录，禁止生产 `var/` |
| `tests/test_operations_*.py`、`tests/test_connectors_*.py`、`tests/web/operations.test.cjs` | 契约、状态、兼容和 DOM 状态机测试，不进行平台浏览器操作 |

新 API 前缀 `/api/operations`；保留旧 `/api/agent`、`/api/idea-plans` 和客户接口。各期数据库脚本在实施时取“当前下一个空闲迁移编号”，禁止预先固定 016 与其他开发冲突。业务对象以 ID/版本/哈希互相引用，不复制审批表。

验收脚本公共契约：`--stage foundation|content|video|connectors|review|expansion|mac --workspace ABS_DIR --manifest FILE --mode engineering|customer`。工程模式只能用带专用标记的独立数据，审批明确写 `AUTOMATED FIXTURE`；客户模式在真实人工关卡停下，不能替人批准。下列命令/测试已按阶段提供；工程与客户模式分开，具体覆盖和限制见各期验收记录。

```sh
# 后续执行时先设置：仓库外新目录；manifest 只引用已核对使用范围的本机素材。
ACCEPT_ROOT="$(mktemp -d /tmp/jianxu-domestic.XXXXXX)"
MANIFEST="/absolute/path/to/authorized-acceptance-manifest.json"
```

manifest 字段固定为 `cases[{id,category,asset_paths,asset_sha256,source_refs,usage_scope,product_id,color_policy,expected_actions}], legacy_backup_path`。标杆藏蓝与另一品类分组；五段识别基准另记 `benchmark_group_id`，不得换片宣称加速。

---

## D0：Fork、资源锁定与兼容底座

**输入/输出：**输入上游固定提交与本库基线；输出资源快照、`SuiteBrief.v1/SuitePlan.v1/ToolSpec.v1/OpsResult.v1` 的严格模型。`load_resources(lock_path) -> ResourceBundle` 只读并校验 SHA。

**涉及文件：**Fork `Domestic/README.md`、`Domestic/manifest.json`；本库 `operations/{contracts,resources}.py`、资源目录、lock、`tests/test_operations_contracts.py`、`scripts/accept_domestic_suite.py`。

- [x] 先写契约失败测试：旧 `ContentBrief.v1` 和 P13 命令原样解析；未知字段/工具/路径/非法引用拒绝；资源哈希变更拒绝；重复请求只有一条业务效果。
- [x] 运行上述测试确认因新契约缺失而失败；原 `test_agent_contracts.py/test_idea_plans.py` 仍通过。
- [x] 使用用户 GitHub 账户 Fork 上游，保留 upstream 指向；记录实际 Fork URL 与 SHA。仅下载选定文本/脚本，逐文件保留 MIT；不引入原始 PDF/案例媒体或执行安装脚本。
- [x] 实现协议适配与资源校验；区分“参考/已适配/已实测”；建立工具效果白名单和能力开关，默认不调用新模型/平台。
- [x] 从升级前备份恢复到独立目录，记录旧表、文件、审批指纹，完成只增量迁移；旧运行和预览可读且指纹未变。
- [x] 测试通过后单独提交；产出来源清单、数据指纹和 D0 验收 JSON。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_contracts.py tests/test_agent_contracts.py tests/test_idea_plans.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage foundation --workspace "$ACCEPT_ROOT/D0" --manifest "$MANIFEST" --mode engineering`。

**通过标准/不做：**Fork 可追溯、旧协议完全兼容、审批不新增；不搬迁客户目录、不改渲染器、不启动外部连接器。关闭新增入口即可停止使用；数据库回退只用升级前备份另目录恢复。

## D1：国内商品定位、平台内容与六方向

**输入/输出：**`ProductContext` 引用当前已确认事实、SKU/配色、素材证据；`plan_content(brief, evidence, resource_bundle) -> SuitePlan`；`make_publication_copy(plan, platform) -> {titles,body,tags,cover_brief,source_refs}`。产物都是待确认草稿。

**涉及文件：**Fork `Domestic/02_Positioning/03_Content/05_Video`；本库 `operations/{positioning,content,planner}.py`、`content_plan.py` 的兼容适配、`spoken_copy.py`、`operations/api.py`、原 `/ideas` 的增量字段、`tests/test_operations_content.py`。

- [x] 先写测试：无空格中文、品牌型号、带条件数字、未知人群、混色/缺镜头不误判；改商品/人群/气质会改变选择理由与内容；不新增无依据性能、使用经历和对比结论。
- [x] 运行新增测试确认缺少实现而失败；保留旧预览测试基线。
- [x] 适配上游“一个核心卖点、钩子候选、输入/输出、自检”结构；先使用既有本机模型/规则路径。中文预估只用于预算，正式字幕时间不使用上游葡语词速算法。
- [x] 输出六套联合方向：默认商品展示/场景分享/证据讲解各两种视觉结构；每套包含钩子、全文、实拍依据、动效与声音建议、缺口及预计时长。检测仅换色/同稿重复；素材不足的方向明确标“需补拍/仅图示”。
- [x] 给出抖音与小红书不同的标题/正文/封面建议；平台规则记录来源、适用内容类型、核对日期，不把创作建议当硬性平台限制。自然表达复用 `spoken_copy.py` 与已核对 Humanizer 方法。
- [x] 接回原六预览和采用入口；当前 24 秒 v1 不变，新增时长使用显式新版本适配。真实预览依然 6–8 秒，声音预览未听核即待审。通过测试并单独提交。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_content.py tests/test_idea_plans.py tests/test_idea_adoption.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage content --workspace "$ACCEPT_ROOT/D1" --manifest "$MANIFEST" --mode engineering`。

**通过标准/不做：**两品类分别产生六套可解释方案；每组至少三种叙事、两种视觉结构，用户能说明区别；每条卖点可回到事实/素材；无资料不造数据。自动差异检查加人工判断，不能以模板 ID 不同冒充审美验收。本期不承诺自由生成商品图/真人，也不自动批准文稿或方向；回滚保留旧 v1 页面路径与规则方案。

## D2：视频 Agent 执行与确定性工作流兜底

**输入/输出：**`compile_plan(SuitePlan, approval_refs) -> ExistingRuntimeProposal`；`execute_step(tool_id, input_refs, idempotency_key) -> OpsResult`；`safe_fallback(error, checkpoint) -> resume|needs_human|stop`。共享既有计算租约、缓存和取消，不另建第二支渲染队列。

**涉及文件：**`operations/{tools,execution}.py`，`agent_runtime.py/agent_worker.py` 的桥接，`customer_planner.py/delivery_plan.py`，`content_plan.py/idea_renderer.py`，`tests/test_operations_execution.py`、验收脚本 video stage。

- [x] 先写测试：运行超时、进程中断、同请求重入、取消后迟到结果、引擎升级、依赖缺失、低质量素材；所有路径都不能绕过人工关卡或自动调用云。
- [x] 运行新测试见失败，再将方案编译为已有白名单识别/选段/准备分镜/渲染步骤；额外规划重试最多 2 次，总步骤/模型/时长预算沿用已有 Policy 上限，不放宽全局门槛。
- [x] 只对幂等本机步骤恢复；校验当前文稿、方案、素材和审批哈希。`needs_human` 显示缺口/编辑入口；`unknown` 留证并停止。回退改变内容需新版本和重新确认，不静默换素材或风格。
- [x] 扩展时长为选定 20–30 秒，统一整稿配音/停顿/语义拍/关键词字幕；原速完整动作、主体可见、同款配色与单镜缓存继续执行。镜号、进度等工程标记只留诊断页。
- [x] 用藏蓝和另一许可实拍品类分别制作三条完整作品；真实文稿/听核/分镜/成片确认逐版等待人操作。单镜改后核对其他镜头哈希、未改声音、字幕与旧审批。
- [x] 同机同素材对比 Agent 和固定工作流：端到端、中间计算、人工等待分别统计；冷/暖分开，交错至少 3 轮。若改识别后端，必须另外使用固定五段强制重推。测试通过单独提交。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_execution.py tests/test_agent_runtime.py tests/test_agent_recovery.py tests/test_idea_adoption.py tests/test_delivery_reviews.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage video --workspace "$ACCEPT_ROOT/D2" --manifest "$MANIFEST" --mode engineering`，再用 `--mode customer` 进行实际客户流程验收。

**通过标准/不做：**两品类三种完整片可审阅；故障注入可恢复/可取消且无重复效果；只改一镜时无关镜头与 PCM/SRT 保持（确有时长/转场依赖则先告知）；旧任务读取/修改/恢复均通过。速度是否提升报告实际中位数、峰值内存及质量，不预报百分比，不以换低清/抽少帧提速。关掉新桥接即可用既有工作流；新对象保留，勿降 schema。

## D3：平台只读连接器、可选 MCP 与发布交接

**输入/输出：**`ConnectorSpec` 固定来源/版本/能力/许可/传输；`read_observations(account_ref, range) -> list[Observation]`；`export_pack(job_version, platform) -> PublicationPack`。API `GET /api/operations/connectors`、`POST .../connectors/{id}/read` 与 `POST .../publication-packs`。

**涉及文件：**`connectors/{contracts,registry,mcp_client,douyin_readonly,xhs_import}.py`、`operations/media_pack.py`、`operations/api.py`、原配置/交付页面的增量、`tests/test_connectors_policy.py/test_connectors_import.py`。

- [x] 先写测试：MCP 的 `readOnlyHint` 造假、工具声明更改、Prompt 注入要求开权限、任意 URL/命令、跨账户、token 过期、限流、未获批、导出包密钥泄漏；默认全部拒绝新增平台写能力。
- [x] 运行失败测试；独立环境评估官方 MCP SDK v2.3.0 的锁依赖、Python 兼容和空闲资源；合格再做 optional extra。协议使用官方 SDK，业务检查复用已有边界，不写自制 MCP 协议栈。
- [x] 抖音只做已获批且用户授权的本人作品数据，具体 scope/回调在实施时按官方契约确认。OAuth state、凭据 Keychain、错误脱敏、限流与断连保留；无权限可先人工导入，不阻塞视频制作。
- [x] 小红书先交付授权导出文件/链接登记，内容数据 API 未证实可用则保持 `unavailable`；登记 xpzouying MCP 为“浏览器依赖，当前禁用”，不下载浏览器、不搬运 Cookie、不把其发布工具暴露给 Agent。
- [x] 将已审/待审成片、封面、平台标题正文话题、SRT、来源及操作清单导出；客户自行发布后登记内容 ID。已有千川广告数据与抖音自然数据使用不同连接器/数据集。
- [x] 工具按语义白名单（包括合法的只读 POST）、固定协议/版本/地址、输出大小及凭据隔离执行。n8n 仅保留外部触发样例，非本期安装依赖；通过测试后单独提交。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_connectors_policy.py tests/test_connectors_import.py tests/test_qianchuan_api.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage connectors --workspace "$ACCEPT_ROOT/D3" --manifest "$MANIFEST" --mode engineering`。真实只读验收单列账户、获批 scope、请求时间、脱敏回执；无凭证只能写“模拟通过/实接待验”，不能宣称已联调。

**通过标准/不做：**离线导出/导入完整可用；不存在发布、删除、评论、私信、投放路由；外部内容无法新增权限；平台断网仍能制作。撤销连接/禁用可选依赖即可回退，文件导入保持可用。

## D4：冻结复盘、评论洞察与下一版假设

**输入/输出：**`freeze_observations(batch_refs, metric_contract) -> snapshot_ref`；`analyze_comments(import_ref, product_ref) -> CommentInsights`；`suggest_iteration(snapshot_ref, insight_refs) -> HypothesisDraft`，人工选择后关联父片和新方案。

**涉及文件：**`operations/{observations,comments}.py`；`reporting.py/review_snapshots.py/experiments.py` 的增量适配，`creative_features.py`；Fork `Domestic/06_Performance/07_Comments`；`tests/test_operations_observations.py/test_operations_comments.py`。

- [x] 先写测试：零/缺失、累计/每日、自然/广告、归因窗口/币种/时区冲突、重复导入、抽样偏差；评论提示注入及无昵称输入不会损坏流程。
- [x] 运行失败测试；复用既有冻结与假设表，必要字段通过新增引用/表扩展，不把历史账户×素材×日快照改成另一口径。
- [x] 冻结平台×账户×内容×日期/观测时间、来源文件 SHA、指标定义和缺失原因；只有确认口径一致才计算比例。累计快照差值若不能排除删除/回填，则不能标为日增量。
- [x] 参考上游评论分类/误解识别，由本机模型给候选分类，确定性脚本计数；保留原文证据与样本范围，个人标识默认去除，不自动回复、抓取或把意见当产品事实。
- [x] 将钩子、镜头/字幕结构、商品证据、评论疑问写入迭代假设；人工选择后生成下一版，绑定父片/冻结快照/实际变更。两期可比与不可比分开，保留未知，不做因果归因。
- [x] 两份脱敏导出完成导入→冻结→假设→制作草稿→下一轮比较；真实数据不足时标记工程案例。测试通过单独提交。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_observations.py tests/test_operations_comments.py tests/test_reporting.py tests/test_review_snapshots.py tests/test_experiments.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage review --workspace "$ACCEPT_ROOT/D4" --manifest "$MANIFEST" --mode engineering`。

**通过标准/不做：**冻结后原报表变更不改结果；每个结论能追到行/指标定义与成片版本；未知不补零，下一版由人决定。无自动预算调整、跨平台 ROI 排行或“某动效导致成交”结论。关闭新诊断层，原冻结/实验继续可读。

## D5：补齐七模块，扩展商品与内容业务

**输入/输出：**`analyze_market(import_refs, declared_scope) -> ResearchDraft`；`propose_positioning(product_ref, research_ref) -> StrategyDraft`；`plan_images(confirmed_content_refs) -> ImagePackDraft`。模型只组织/解释，数值由已验证计算代码完成。

**涉及文件：**Fork `Domestic/01_Market/02_Positioning/04_Image`，`operations/{research,positioning,media_pack}.py`，`web/operations.*`，`tests/test_operations_research.py/test_operations_media_pack.py`。

- [x] 先写测试：样本过少/缺来源、跨平台价格币种、未填成本、过期费率、型号冲突、图片与卖点不符；从事实中移除依据后相关建议必须失效。
- [x] 运行失败测试；逐模块核对上游脚本与现有实现，能直接复用的纯计算保留许可并封装，缺失补零或跨境硬编码不直接带入。不得为复用又增加常驻服务。
- [x] 市场模块分析客户合法导出的样本/自主提交参考，输出样本覆盖与未知；不宣称全平台市场容量、真实搜索热度或自动抓取竞品私有数据。
- [x] 商品策略输出人群/场景/核心卖点/证据/拍摄需求；只有成本、费率、生效日、币种等齐备才展示确定性毛利试算，不自动改价。
- [x] 图片模块先复用实际帧与 Pillow/Remotion 生成封面、信息图、图文页；无商品照片用标记图示，不伪造真实外观。生成式图片/视频作为独立可选 Provider，需另行核验资源、权重和内容一致性，未过验收不列为已支持。
- [x] 七模块输入/输出通过公共引用串联，发布内容矩阵草稿（平台/主题/版本/所需素材），不自动定时发布；逐模块通过测试再提交，不一次上线全部实验功能。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_research.py tests/test_operations_media_pack.py tests/test_operations_content.py`；`.venv/bin/python scripts/accept_domestic_suite.py --stage expansion --workspace "$ACCEPT_ROOT/D5" --manifest "$MANIFEST" --mode engineering`。

**通过标准/不做：**同一商品可产出定位稿、封面/笔记、视频和复盘引用；每模块有输入示例/限制/证据；缺资料明确说明。保留知识/想法代码视频入口，不扩展为 ERP、客服机器人或多人 SaaS；各模块独立开关回滚。

## D6：Mac 客户交付、验收与发布

**输入/输出：**固定版本的程序/国内资源包/可选依赖清单 → 可安装 Mac 包、升级包、SHA256、客户指南、能力矩阵、验收与回滚说明。

**涉及文件：**`customer_launcher.py/customer_setup.py/maintenance.py`，`scripts/install_customer.py/launch_customer.py`，现有打包入口（先定位真实文件，不另造平行脚本），`docs/MAC_WORKBENCH_GUIDE.md`、README、许可清单，`tests/test_operations_delivery.py` 与 Mac stage。

- [ ] 先写测试：备份缺文件、断电/磁盘不足、升级包与资源版本不匹配、历史审批与恢复串版、可选 MCP/模型未装；故障时保留旧目录并给可执行处理指引。
- [ ] 运行失败测试；沿用既有一键启动/配置/维护流程，将运营入口与资源包纳入发行；不打包项目、Cookie、Secret、未经公开许可素材、AGPL 应用或 n8n。
- [ ] 全新 Apple Silicon 目录安装、检查模型和本机声音、创建两品类项目、六预览、各三条作品、单镜改/比较/恢复、审核导出、报表冻结/新版假设走通；首次下载与就绪耗时分别记录。
- [ ] 升级前备份；新目录恢复后核对资料/声音/项目/历史审批/文件哈希。验证原安装可继续打开，禁止直接覆盖生产数据或修改旧迁移版本号。
- [ ] 更新客户指南与能力矩阵，分别列出“实测可用/需账号权限/可选未装/未支持”；README 展示真实工作台与许可媒体，示意图和工程预演明确标识。
- [ ] 完成全套非 CU 回归、资源/许可/泄密检查和客户实际看听；发布包含版本说明、SHA、回滚包和已知问题。发布范围及客户素材公开授权分别核对，不能把既有样片使用权当公开展示权。

**验收命令：**`.venv/bin/python -m pytest -q tests/test_operations_delivery.py`；`node --test tests/web/*.test.cjs`；`render/remotion/node_modules/.bin/tsc --noEmit -p render/remotion/tsconfig.json`；`.venv/bin/python scripts/accept_domestic_suite.py --stage mac --workspace "$ACCEPT_ROOT/D6" --manifest "$MANIFEST" --mode customer`。

全回归沿用项目当前非浏览器执行集合：`.venv/bin/python -m pytest -q -k 'not test_focus_frame_contains_requested_media_point_in_actual_browser_layout'`；该布局测试需真实浏览器，报告其排除原因及全部跳过项。若后续新增其他浏览器操作测试，也须移出此非 CU 集合并明确报告，不能静默声称全测。生产 Remotion 离线渲染不属于平台浏览器自动化。首次依赖/模型下载、声音付费调用按已有配置/授权操作，不在验收脚本中自动追加。

**通过标准/不做：**客户用一个 Mac 包即可制作和回滚；全部人工确认真正在界面执行；平台无写入；Windows 原生和互联网多租户不列入本轮验收。保留升级前程序/备份，独立目录启动旧版本即可回退；恢复旧库会失去升级后的新数据，因此始终保留新目录供导出。

## 实施状态与验收限制

D0–D5 的实现与隔离工程证据见 DOMESTIC_D0/D1/D2/D3/D4/D5_ACCEPTANCE.md；D6 总记录见[交付验收](../../DOMESTIC_ACCEPTANCE.md)。本计划中的勾选表示工程实现/验证，不表示真实客户审批或平台联调。

D2 三轮性能验收从准备好的分镜开始，冷/暖渲染分别记录；不含首次识别、人工等待与完整上传到交付的端到端计时，没有稳定的整体提速，默认后端不切换。六条20–30秒作品是明确标记的工程分镜重放；另有真实六方向采用→Runtime→成片链路，均保留待审。

D4 使用规则候选回退，不新装语义模型；自然内容另存追加型对象，未改变原广告表。真实评论/账号/下一轮数据尚未提供，不捏造真实平台对照。D6 候选包不发布，由用户最终实际确认后决定发布。
