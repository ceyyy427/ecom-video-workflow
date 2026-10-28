# 国内电商运营套件 · D0 检查指南

D0 已建立 Fork、参考资源锁、共用数据契约和只读工具桥接。本阶段不增加制作页面或运行新的运营 Agent；原来的创意实验室、客户工作台、逐镜修改和全部审核继续原流程。

## 查看本次成果

- [国内资源分支](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/codex/domestic-d0/Domestic)：七模块的职责与后续阶段；其 `planned` 状态表示未实现。
- [固定国内资源提交](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/705c0a905bc14c4312e8aa1f0ca7cdd03b58f2f1/Domestic)：本机资源包对应的版本。
- [资源锁](third-party/domestic-toolkit.lock.json)：上游/国内 Fork 提交、每份文件的大小、SHA256、来源和许可。
- [验收记录](DOMESTIC_D0_ACCEPTANCE.md)：真实旧备份、当前预览备份及自动回归结果。
- [总执行清单](superpowers/plans/2026-10-28-domestic-ecommerce-expansion.md)：下一期仍须检查通过后单独开始。

## 共用方案结构

| 契约 | 用途 | D0 边界 |
| --- | --- | --- |
| `SuiteBrief.v1` | 平台、目标、人群、气质、商品/配色、证据和素材引用、目标时长 | 仅数据；不替人确认事实，跨项目素材必须后续解析归属 |
| `SuitePlan.v1` | 六个候选、依赖任务、缺口、成本约束、来源版本和冻结依据 | 验证唯一性、依赖环、引用类型与内容摘要；不生成/执行方案 |
| `ToolSpec.v1` | 固定工具 ID、输入/输出模型、效果、人工前提与预算元数据 | D0 只登记原四项本机读取；时限等是契约描述，未新增执行器 |
| `OpsResult.v1` | 读取结果、结构化错误、证据及原回执 | `completed` 仅指读取完成，不表示制作/审核通过；错误/不明状态不得互相矛盾 |

旧 `ContentBrief` 和 P13 命令保持原样。旧创作请求适配时，`content_brief` 完整保留想法、事实来源、数值、素材 origin/所属项目及入点；不把旧素材 ID 冒充新项目已经确认的素材。

`SuitePlan.basis` 为 `creative.signature(plan.model_dump(exclude={"basis"}))`，即规范 JSON 的 SHA256；引用中的可空属性也保留，生产者应先按模型规范化引用。它用于检测内容变化，不是人工批准或数字签名。

## 默认开关与人工关卡

`ECOM_OPERATIONS_ENABLED` 默认关闭。D0 没有注册新 HTTP 页面、制作接口或连接器；验收进程只在独立目录临时启用读取桥接，不修改用户环境文件。旧 `ECOM_AGENT_ENABLED` 开关语义不变。

桥接只接受 `project.read`、`project.check`、`creative.recommend`、`reports.dashboard`，复用原 `AgentService` 的事务回执。同 request_id/内容返回原结果，内容冲突沿用原错误；不能通过 D0 请求识别、模型、配音、渲染、发布或投放。方向读取仍要求已有事实/文稿确认。

参考包只有 27 份文本、147,594 字节，全部登记为 `reference`。资源读取会检查固定仓库/提交、来源路径、文件大小/哈希、MIT 声明、重复字段、路径和软链接，校验失败即停止；不会执行其中的 Python 脚本，也不会联网拉取替代文件。

## 重新执行隔离验收

使用已由维护页面或维护 CLI 导出的有效备份。新建清单文件（路径按本机实际填写）：

```json
{
  "cases": [],
  "legacy_backup_path": "/absolute/path/to/verified-backup"
}
```

D0 不跑素材推理，`cases` 可为空；后续阶段再填写授权素材。指定一个**尚不存在、位于仓库外且父目录已存在**的目录：

```sh
.venv/bin/python scripts/accept_domestic_suite.py \
  --stage foundation \
  --workspace /absolute/path/to/new-d0-check \
  --manifest /absolute/path/to/d0-manifest.json \
  --mode engineering
```

脚本恢复备份到新目录，校验旧业务表/文件、读取旧任务与预览，验证重复初始化及读取回执幂等。工程读取夹具另建空库，请求不存在的项目返回 `NOT_FOUND` 是预期验证，不是客户项目失败。

输出为 `acceptance.json` 和不含原始业务内容的 `table-fingerprints.json`。不会启动服务/worker、合成视频、调用模型或新增人工审批；`customer_signoff` 始终为 false。其他 stage 会明确拒绝。

## 回滚

本期不修改原生产数据目录、不增加迁移或模型依赖；未发布新的 Mac 安装包。继续使用原安装即可。开发者可切回升级前提交 `54dbfc06b40624e937a5053771549ecd84f752f8`；新资源分支保留用于检查，不需要删除 Fork。

验收恢复副本使用现有迁移将 schema 14 升至 15；若要检查旧程序，应把升级前备份再次恢复到另一个新目录，不能降低 schema 版本号或覆盖原数据。
