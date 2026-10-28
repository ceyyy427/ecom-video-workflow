# 国内运营套件 D2–D6 连续执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**授权：**2026-10-28 用户明确选择“连续推进到 D6，真实人工审核保留待审，最后由我验收发布”。替代总计划中逐期等待下一次指令的安排；不替代真实审批，也不授权自动发布。

**Goal:** 完成原 [D2–D6清单](2026-10-28-domestic-ecommerce-expansion.md)，提供可检查的 Mac 候选交付包、真实样例、操作与回滚指南，最终发布留给用户。

**Spec:** [原设计](../specs/2026-10-28-domestic-ecommerce-expansion.md)。

**Architecture:** 既有 Customer/Runtime/渲染/冻结/版本管理继续拥有执行与人工关卡；运营层只做严格参数编译、只读/文件适配、可追溯草稿。自然内容观测与原广告报表分开存储、定义和展示。新增持久对象采用明确增量迁移和既有备份引用校验，不散落任意路径 JSON。

**Tech Stack:** Python/Pydantic/FastAPI/SQLite、原 Remotion/FFmpeg/Pillow、静态页面。可选 MCP 使用经核验的官方 SDK 隔离依赖。无新云调用、平台写能力或常驻 n8n。

## Global Constraints

- 保留现有 UI、旧协议、逐镜编辑、版本恢复及本机模型优先。
- 所有事实/文稿/方向/分镜/听核/成片确认仍由人；工程夹具只存在标记的隔离目录，真实项目保持待审。
- 不修改原生产目录、账户配置、环境文件或已有177处修改；每阶段独立提交，最终再核对指纹。
- 需要账户权限的真实接口明确“待实接”；缺账号不伪造联调、不绕道 Cookie/浏览器抓取。
- 许可证、资源、输出摘要可追溯；依赖与模型按需而非盲目增加；默认无平台发布/投放。
- 使用一轮全分支独立复核覆盖 D1–D6；重要问题先写失败测试再修复。最终客户验收与发布仍待用户。

## Review Focus

- D1冻结方案到原 Runtime 的归属、版本与人工关卡不能串版；不改变默认权限或在失败时暗中换素材。
- 连接器白名单按能力语义，合法只读 POST 可用；外部文档、MCP hints 不能增加权限，令牌不进入报告/包。
- 自然/广告、累计/每日、缺失/零、时区/币种/归因窗口必须可辨；冻结不可被后续原文件更改影响。
- 评论与市场样本不变成商品事实；去个人标识、保留来源、不给因果结论；下一版需要明确人工选择。
- 安装包包含固定资源/全部代码但不含私有媒体、密钥、浏览器 Cookie、模型权重或第三方完整应用；新目录恢复保留旧安装。

### Task 1: 收尾 D1

- [x] 隔离安装 Playwright 1.61.0（Apache-2.0，Python≥3.10），不写共享制作环境；真实页面两视口/播放/重入/输入变更验收。
- [x] 记录两品类各六条真实七秒预览、自动回归、来源与回滚，单独提交 D1。

### Task 2: D2 方案编译、运行桥接与作品回归

**Files:** `operations/execution.py`、`operations/api.py`、`web/customer-agent.js`，`tests/test_operations_execution.py`，既有视频验收脚本的适配。

- [x] RED：方案/采用项目不符、旧版本、缺人工确认、超预算、重复、取消迟到、结果不明等测试；原 Runtime 测试保持。
- [x] `compile_plan(...)` 仅编译为原 P13命令，`propose_execution(...)` 复用 AgentService/Runtime；无第二队列。固定工作流兜底只建议原安全路径，不修改人工输入。
- [x] 客户工作台将国内方案交接到旧有界运行控件；原启用开关不被绕过，默认没有自主云/平台权限。
- [x] 隔离工程样例验证原声时钟、三种视觉、原速动作、单镜缓存与旧版本；实际客户作品保留待审。交错三轮记录 Agent/原工作流耗时与内存，不承诺提速。
- [x] 目标回归后独立提交；更新 `--stage video` 与限制。

### Task 3: D3 只读连接器与交接包

**Files:** `connectors/{contracts,registry,mcp_client,douyin_readonly,xhs_import}.py`，`operations/{records,media_pack}.py`，必要迁移/备份引用，`tests/test_connectors_policy.py/test_connectors_import.py`。

- [x] RED：假只读 hints、任意地址/命令/作用域、跨账户、限流/未获批、秘密泄漏等。
- [x] 核对官方 SDK 固定版本/许可/兼容/空闲资源；可选依赖隔离，不引入自制 MCP 协议栈。
- [x] 抖音官方本人作品只读接口与手工导入；小红书通用笔记 API 未证实则 unavailable，浏览器 MCP 禁用。
- [x] 复用原凭据隔离、OAuth 与导出结构；待审包明确不能发布，已审包仍由客户自行发布。登记内容 ID 不触发平台写入。
- [x] 离线 import/export/恢复验收、独立提交，实接状态与模拟结果分开。

### Task 4: D4 自然内容冻结、评论与下一版

**Files:** `operations/{observations,comments,iterations}.py`，既有快照/实验/创意特征的适配，Fork 06/07，`tests/test_operations_observations.py/test_operations_comments.py`。

- [x] RED：缺失/零、累计/每日、口径冲突、重复源、冻结后改源、注入与隐私、失效父片等。
- [x] 冻结观测及文件 SHA、定义/缺失原因；与广告快照分开，兼容原流程。
- [x] 评论先作有证据候选分类并计数；无可用本机文本模型时明确规则回退与未知，不发送云端。
- [x] 人工选择假设后创建待确认下一版，关联父片/快照/实际变更；下一轮只做可比的描述性对照。
- [x] 两份工程导出完整闭环，原广告复盘回归，独立提交。

### Task 5: D5 七模块与页面

**Files:** `operations/{research,positioning,media_pack}.py`，`web/operations.*`，Fork 01/02/04，`tests/test_operations_research.py/test_operations_media_pack.py`。

- [x] RED：来源不足、币种/费用日期不齐、型号冲突、失效事实、图示冒充照片。
- [x] 复用确定性统计/毛利试算；只解释合法提供的样本；真实帧/Pillow封面与图文建议，未知不造数。
- [x] 原 UI 增量运营入口，七模块输入/输出/状态/限制与内容矩阵；不做 ERP/SaaS 或自动排期发布。
- [x] 模块回归、来源锁更新并单独提交。

### Task 6: D6 Mac 候选交付

**Files:** 现有 `customer_setup.py/customer_launcher.py/maintenance.py` 与既有打包入口，`tests/test_operations_delivery.py`、客户指南、能力矩阵、验收记录。

- [ ] RED：固定资源漏打包/版本错配、可选依赖缺失、备份/升级失败、历史审批或秘密串入。
- [ ] 沿用现有打包器，候选版本不发布；全新 Apple Silicon 目录安装/启动/预览/修改/恢复/导出、冻结/假设链路验收。
- [ ] 升级前备份，新目录恢复核对资料/声音/项目/审批/哈希；旧目录可继续启动。
- [ ] 全 Python/Node/TS、单轮独立复核与问题修复、许可/泄密扫描；整理 Mac 包及 SHA、客户步骤、已知问题、回滚。
- [ ] 最终状态为“工程验收完成、客户实际确认及发布待处理”，交由用户验收，不替用户发布。
