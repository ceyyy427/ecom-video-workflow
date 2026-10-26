# Six Direction Previews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 当前用户已授权直接实施，按任务顺序执行并在末尾作独立复核。

**Goal:** 六套7秒真实预览、可追溯共用方案与进入客户制作的完整入口。
**Architecture:** 复用SQLite/Worker/资源租约、Remotion与FFmpeg；受控图示组件和六套既有风格适配，冻结计划后渲染，再带入待确认客户项目。
**Tech Stack:** Python3.11/FastAPI/SQLite、Remotion4.0.519/React、FFmpeg、本机字体，无新依赖。
**Spec:** docs/superpowers/specs/2026-10-25-six-direction-previews-design.md

## Global Constraints
- 保留现有UI与旧任务；事实/文稿/风格/听核/成片均人工确认。
- 不使用Computer Use、不调用云模型或TTS、不自动投放、不执行Prompt代码。
- 先查成熟开源/官方实现，固定版本及许可；不复制上游示例媒体。
- 计划预览7秒，实际帧率30fps；6–8秒范围内不以占位图冒充动态视频。

## Review Focus
- 未给事实/数值：不发明产品承诺、数据或人物经历。
- 用户修改输入或文件：旧预览不能被当作新输入的结果。
- 未确认/异款素材：保留缺口与阻断，不以预览通过替代同款/动作审核。
- Worker退出/重复请求：无重复采用/无限渲染，局部完成可校验复用。
- 一镜修改/恢复：共享方案不能覆盖其他镜头或继承新审批。

### Task 1: 共用协议、六方向规划与持久状态
**Files:** content_plan.py、idea_plans.py、migrations/015_idea_plans.sql、db.py；tests/test_idea_plans.py。
**Interfaces:** ContentBrief → build_plan(brief, materials) → CreativePlan；IdeaPlans(root,store).create/get/enqueue/cancel/claim/progress/finish。
- [x] 写未给数据不造数字、六方向/四镜结构、受众气质变化、哈希绑定、排队/取消/过期/复用的失败测试并运行。
- [x] 实现协议与只新增表迁移；保存不可变计划和有界状态。
- [x] 运行测试，固定旧schema14升级与旧任务保留用例，提交。

### Task 2: 素材与真实预览执行
**Files:** idea_media.py、idea_renderer.py、idea_worker.py、worker.py、render/remotion/src/CodeVisual.tsx、现有媒体组件；tests/test_idea_render.py。
**Interfaces:** material_refs→冻结素材；render_option(plan,option,root,directory,check)→MP4/PNG/manifest；Worker无旧任务时消费预览队列。
- [x] 写图片/视频边界、已知身份冲突、保护动作、短素材、取消/失败/复用、图示无伪数据的失败测试并运行。
- [x] 复用现有媒体检查/渲染器与清理逻辑；六适配和生成图示；输出严格核验后才ready。
- [x] 运行相关测试/TS；提交。

### Task 3: 选择后进入客户制作，保留人工门禁
**Files:** idea_adoption.py、customer.py、customer_directions.py、creative.py、customer_planner.py、products.py；tests/test_idea_adoption.py。
**Interfaces:** adopt(plan_id,option,basis)→新customer_id；apply_script(pid,revision)→待确认文稿；读取同一plan驱动方向/分镜。
- [x] 写幂等采用、stale拒绝、事实未审不能带入、确认后仍待文稿/风格/听核、逐镜修改/恢复旧任务兼容的失败测试并运行。
- [x] 实现资料/素材复制与来源映射；无自动审批；只有关联项目消费新的方向提示，旧任务指纹不变。
- [x] 跑客户/版本相关回归并提交。

### Task 4: 页面与API接线
**Files:** idea_api.py、api.py、web/ideas.{html,js,css}、web/customer.js；tests/test_idea_api.py、tests/web/ideas.test.cjs。
**Interfaces:** 使用设计中的/api/idea-plans与既有会话校验；轮询只读，所有变更由按钮发起。
- [x] 写实际JS事件、重载恢复、表单变化废弃旧选择、仅ready采用、上传/跨目录/伪造basis的失败测试并运行。
- [x] 保留现有页面外观，加入素材、事实折叠区、六视频播放器/状态/采用与制作链接。
- [x] 跑API/DOM/TS测试并提交。

### Task 5: 真实实拍与图示验收、文档与复核
**Files:** scripts/accept_six_previews.py、docs/SIX_PREVIEWS_{USAGE,ACCEPTANCE}.md、docs/third-party/six-previews-reuse.md。
**Interfaces:** 隔离验收目录→真实渲染/严格解码/多帧/差异/耗时/复用/进入制作证据；不写客户审批。
- [x] 用许可明确的本机鲜橙实拍与无素材知识主题各生成六预览，实际抽帧检查并修复。
- [x] 隔离夹具验证采用→事实/文稿确认→分镜→修改/恢复；审批标记fixture，真实样片保持待人审。
- [x] 全量非浏览器pytest、前端测试、TS/Ruff；按复核技能作独立只读复核并修复。
- [x] 更新操作、采用依据、验收结果/限制与回退，提交并把变更合回原仓库，保留原UI/未提交文档。
