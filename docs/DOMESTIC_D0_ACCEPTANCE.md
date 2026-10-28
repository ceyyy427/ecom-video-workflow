# 国内电商运营 D0 · 验收记录

日期：2026-10-28。范围仅 D0；D1–D6 未实施。代码在 `codex/domestic-d0` 工作分支，原工作台、识别/渲染后端、生产数据与模型配置保持。

## 已交付

1. 用户 Fork：[ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit)。
2. 国内方法分支：[codex/domestic-d0/Domestic](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/codex/domestic-d0/Domestic)，提交 `705c0a905bc14c4312e8aa1f0ca7cdd03b58f2f1`；原上游目录未改。
3. 本机 27 份参考文本，共 147,594 字节；上游固定 `cec98a9cab382d28dfe5b4ed0de444f33c455cb5`；MIT 原文、逐文件来源/大小/SHA 随包保留。
4. `SuiteBrief/SuitePlan/ToolSpec/OpsResult` 四个 v1 严格协议，旧创作输入完整保留；原四项本机读取的默认关闭桥接，复用旧回执事务。
5. 隔离验收 CLI、契约/资源/兼容测试及[检查指南](DOMESTIC_D0_USAGE.md)。没有新数据库迁移、运行时依赖或平台连接器。

## 实际旧备份恢复

所有恢复只写仓库外全新目录，不覆盖旧数据。表指纹不包含业务原文；迁移登记表单独报告，不能把它的新增行误称为业务变更。

| 检查 | schema 14 历史生产备份 | schema 15 已有预览备份 |
| --- | --- | --- |
| 初始化 | 沿用既有 14→15 迁移 | 15→15，无新迁移 |
| 旧表 | 49 张非迁移登记表行指纹不变 | 52 张非迁移登记表行指纹不变 |
| 原文件 | 510 份 SHA 不变 | 107 份 SHA 不变 |
| 旧内容读取 | 48 个任务可读 | 9 组预览方案可读，完整项文件有效 |
| 再次初始化 | 全表指纹不变 | 全表指纹不变 |
| 新审批/模型/云/平台写入 | 均为 0 | 均为 0 |

schema 14 副本仅新增原六预览版本就已存在的三张表：`idea_uploads/idea_plans/idea_adoptions`；D0 不新增表。原生产库仍为 schema 14，不在本轮升级。

读取幂等：4 个并发同 request_id/内容返回同一原回执，只有 1 条 Agent run、2 条事件；工程读取库中制作任务、审批、执行和千川写任务均为 0。该例故意查询不存在项目，`NOT_FOUND` 是预期回执，不是客户失败或签收。

## 自动验证

- 新增 D0 测试及相关旧契约/预览：修复后 65 passed（新增 D0 用例 35 项）。
- Node 工作台状态回归：44 passed。
- Ruff 与差异空白检查通过。
- 完整 Python 回归：最终修复后 `1045 passed, 4 skipped, 1 deselected in 237.13s`。复核前保持唤醒复跑为 `1038 passed, 4 skipped, 1 deselected in 237.43s`。

首次全回归为 `1 failed, 1037 passed, 4 skipped, 1 deselected`。失败项：`test_worker_registers_frozen_reports_and_keeps_final_human_review`，停留 `rendering`。日志和电源记录证实：任务于 01:39:07 -0700 开始，01:39:25 发生 Clamshell Sleep，02:03:56 唤醒；心跳挂起导致租约失效。同项醒来后独立重跑 `1 passed in 36.33s`。未延长租约或更改渲染代码；保持唤醒重跑全套，首轮失败日志仍保留。

四项既有跳过已单独用 `-rs` 核对：私有历史配音证据未随公开源码分发、Windows DPAPI、Windows Job Object、需要显式启用的临时 OS Keychain 集成。浏览器布局测试按原非 CU 验证范围排除，不能声称覆盖。所有人工确认逻辑保留，工程验收不代表客户成片听审。

## 独立复核

独立只读复核没有 Critical 或 Minor，发现 1 项 Important：`OpsResult` 外层对象/检查点可与原回执矛盾。已加入对象 ID、版本、SHA、输出缺失、错误运行 ID、检查点缺失、原回执无运行 ID 七类复现；修复前 7 项失败，修复后相关回归 65 项通过。规范化输出引用及运行检查点现在必须与原回执完全一致；修复后完整 Python 回归 1045 项通过。没有遗留 Critical/Important 或暂缓 Minor；修复采用失败复现与完整回归验证，未再次派发复核。

## 实施取舍与复用

- **不增加持久化表**：D0 只定义协议和只读桥接，复用原回执；代价是 D1 如需新业务存储，须另行增量迁移。
- **总清单 D0 单独形成执行 brief**：便于明确截止范围，未实施后续阶段；没有扩大产品功能。
- **GitHub CLI 回退**：连接器不可用，使用已登录 ceyyy427 的 CLI，未重新登录或获取明文密钥；Fork 分支已核对远端 SHA。
- **工程与生产隔离**：已有备份用于兼容验证，不能把历史备份当作当前生产数据的完整最新副本；当前生产另做只读指纹对照。
- 开源采用/未采用及本机开销见[复用记录](third-party/domestic-toolkit-reuse.md)。本轮没有新增推理性能测量或提速结论。

复核未判定项的处理：D1–D6 明确留待后续验收；上游脚本仅作参考，实际执行前须另审；平台/模型实接未测，不能宣称可用；本期不作视频速度、声音或新成片质量承诺；私有备份由主执行方恢复校验，复核者未独立复跑，保留这一证据限制；工程验收不能代替客户人工签收。

## 检查位置及回滚

原始验收与诊断位于本机 `/Users/mac/Documents/ChatGPT/ecom-domestic-d0-20261028/`，其中备份/恢复副本含私有资料，不提交 GitHub。资源分支已发布；主应用仅本机工作分支，未发布新安装包或合并主线。

当前生产只读对照：schema 14、50 张表全部指纹不变，原 HEAD 不变，177 个已有改动/未跟踪文件内容保留。原安装及其 UI、识别/渲染与审批未迁移。

回滚继续运行原安装即可；D0 开关默认关闭。源码升级前提交为 `54dbfc06b40624e937a5053771549ecd84f752f8`。恢复备份必须另选新目录，禁止覆盖旧库或降低数据库版本号。
