# D2：方案执行桥接与作品回归

2026-10-28；候选分支 codex/domestic-suite。工程验证不替代客户事实、听核或成片签收。

## 已验证

- 国内已采用方案必须精确匹配方案摘要、方向、项目与当前产品版本，才编译为既有 project.produce；原 AgentService/Runtime 持有幂等、有界预算、暂停恢复、取消与人工关卡。没有第二队列。
- 事实/文稿未确认时返回 needs_human；过时或错项目拒绝；取消后的重复请求返回原回执，不重发或改写。默认仍服从原执行开关。新 UI 只切换提案入口。
- 六条已有工程分镜经当前 Worker/Remotion 实际重渲：藏蓝服装21/24.1/21秒，许可鲜橙26.5/26.5/26.5秒。保留原选段、人声、字幕和动作保护；这是样式回放，不冒充六份新人工审批或自由创作质量验收。
- 第一条仅修改一镜后，其他五镜文件 SHA、解码 PCM、SRT 和父片 SHA 均保持；新片均 needs_review。
- 独立安装可显式设置 ECOM_ASR_MODEL_DIR 复用只读模型缓存；须绝对路径且匹配 docs/P5_MODEL.json 的两个 SHA。不换模型，不经 HTTP 接受任意模型路径。

## 三轮交错实测

同一藏蓝工程输入、分镜、源文件 SHA、已确认的工程字幕时钟；顺序 A/F、F/A、A/F。每单元新目录恢复，冷渲染缓存为空；暖次只修改同一镜的关键词排版。全部原声 PCM/SRT 相同，源片 SHA 与入出点相同。每条人工作业时间未计。

| 路径 | 冷渲染秒（3轮） | 中位数 | 单镜暖渲染秒（3轮） | 中位数 |
| --- | --- | --- | --- | --- |
| Agent 编排＋原渲染器 | 108.000 / 106.596 / 104.172 | 106.596 | 25.552 / 25.922 / 25.277 | 25.552 |
| 固定工作流＋原渲染器 | 110.135 / 107.135 / 108.329 | 108.329 | 23.791 / 23.425 / 23.307 | 23.425 |

Agent 单元进程树峰值 RSS 1.39/1.54/1.47 GiB；固定路径1.43/1.53/1.46 GiB。0.5秒采样，包含 Python/Node/渲染子进程；共享页可能重复计数，且冷暖共用一个单元峰值，不是独占内存或逐次模型峰值。

**结论：**两条路径都复用同一渲染器；没有稳定的整体提速优势，暖次 Agent 略慢。不切换默认后端。此测试从已准备分镜开始，**不是五段素材首次视觉识别测试**，不与之前21.04分钟作百分比对比。

## 证据与复现

本机证据目录：/Users/mac/Documents/ChatGPT/ecom-domestic-d2-20261028/。

- video-acceptance-final/acceptance.json：六条 MP4、SHA、时长与单镜结果；video-manifest.json 锁定来源。客户服装素材只作私有样片，不公开。
- interleaved-render/acceptance.json：12次真实渲染、耗时、缓存命中、内存、PCM/SRT；失败的早期验收目录保留，未纳入统计。
- scripts/benchmark_domestic_execution.py --source ABS_ENGINEERING_DATA --project ID --workspace ABS_NEW_DIR --simulate-confirmations。脚本仅接受 AUTOMATED FIXTURE 项目，绝不写生产数据；预算、原片和权限检查保留。
- .venv/bin/python -m pytest -q tests/test_operations_execution.py tests/test_operations_video.py tests/test_agent_runtime.py tests/test_agent_recovery.py tests/test_idea_adoption.py tests/test_delivery_reviews.py。

## 回滚

设置 ECOM_DOMESTIC_EXECUTION=0 停用新提案桥接；原制作入口和原运行控件可继续使用。ECOM_AGENT_EXECUTION_ENABLED=0 会停止派发自动步骤，暂停/取消仍可用。保留历史回执，不删除数据库或降 schema；要运行旧程序，用升级前备份恢复到另一个新目录。原生产安装未改动。
