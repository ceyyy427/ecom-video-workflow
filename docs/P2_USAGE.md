# P2：巨量千川 / 巨量引擎投放交接与复盘

## 使用顺序

打开 `http://127.0.0.1:8765/distribution`（首页右上角也有入口）。

1. 添加平台账户，粘贴完整广告主 ID。所有平台 ID 都按字符串处理，不接受科学计数法。账户记录不可变，不能通过改账户绕过已有确认。
2. 完成 P0/P1 剪辑和人工成片审核后，在投放页选择成片、计划名称、意向预算和目标 ROI。
3. 查看冻结的账户、参数、成片 SHA256 与快照 SHA256；再次观看视频，填写确认人/核对说明，勾选后生成投放包。审批本身不花费、不上传。
4. 下载 ZIP：视频、字幕、审核、技术 QC、镜头清单、产品事实来源（若有）、人工确认与投放说明。
5. 在相应巨量平台人工上传并创建计划，核对商品、授权、预算周期、排期、出价和平台审核结果。回工作台登记计划 ID、核验人、依据。先登记 submitted，再登记 active/paused/rejected/completed。此状态来源为人工，不冒充 API 自动查询。
6. 使用所选账户和日期导入完整素材日报快照，或使用千川 Ocean Watch 只读同步。将平台素材 ID 与本地已审核成片关联。平台素材 ID、抖音作品 ID、计划 ID 不是同一种 ID。
7. 看板查看花费、支付金额、支付 ROI、CTR、CPA、CPM、完播率和逐日/逐素材数据；下载复盘 JSON 与来源文件。

## 平台能力（本版真实边界）

| 能力 | 巨量千川 | 巨量引擎 |
|---|---|---|
| 人工确认、导出投放包、人工回执 | 可用 | 可用 |
| 标准 CSV 导入与复盘 | 可用 | 可用，需转换为相同支付口径 |
| 固定版 Ocean Watch 素材日报接口 | 已实现，只读，需用户配置授权 | 本版未接原生报表 |
| 自动上传 MP4、自动创建广告/修改预算 | 未开放 | 未开放 |
| 真实账户联调 | 未完成，没有提供凭据 | 未完成 |

没有后台自动加预算、自动优化投放、自动重投。投放模板仍需用户在平台设置商品、素材授权与预算周期，不把意向预算冒充已执行预算。

## Ocean Watch 项目内安装与授权边界

已经下载到 `references/ocean-watch/`，固定 commit `9b05b3b51c1dba8a8f95937976e95162b5e748e3`，版本 `1.0.9+codex.20260924172936`，MIT。锁文件为 `ecom_video/platforms/ocean_watch.lock.json`，许可证保留在 `docs/third-party/ocean-watch-LICENSE`。

重建开发环境时运行：

```sh
uv run --locked python scripts/install_ocean_watch.py
```

安装器不覆盖已有目录，不运行下载脚本，不全局安装插件。API 每次启动 CLI 前校验固定二进制 SHA；不使用会热更新的 launcher。

独立配置位置：`<数据目录>/integrations/ocean-watch/config.json`。独立状态根：`<数据目录>/integrations/ocean-watch/`。我们的 CLI 调用显式传入 `--config`，并设置 `OCEAN_WATCH_HOME` 为该状态根。请在同一状态根按上游文档配置应用凭据与 OAuth 授权，避免在不同状态根重复授权同一 refresh token。不要将密钥填入网页、账户别名、Git、截图或报表。

上游入口：[Ocean Watch](https://github.com/westng/ocean-watch)，[CLI 文档](https://github.com/westng/ocean-watch/blob/9b05b3b51c1dba8a8f95937976e95162b5e748e3/docs/cli.md)，官方 SDK：[Ocean Engine Go SDK](https://github.com/oceanengine/ad_open_sdk_go)。本项目不代替用户创建应用、登录或授权。界面“固定版本已校验”只表示本地运行文件校验通过，不表示账户授权通过。

只读调用固定为 `qc-reports materials`，每天分别查询，`--top 0 --page-size 100 --max-pages 50`，最多连续 7 天。官方接口路径 `/v1.0/qianchuan/report/material/get/`。账户、日期、返回字段、行数、截断标记必须一致；某天失败则整批不入库。每条命令最多 55 秒，stdout 最多 5 MiB。上游任意诊断/原始字符串不回显；证据只保留白名单数值、请求 ID、范围与版本。

## CSV 与指标口径

下载模板，UTF-8（支持 BOM），≤5 MiB、5000 行，日期范围最多 31 天。列及顺序：

```csv
date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views
2026-10-01,1234567890123456789,100,1000,40,4,300,500,100
```

以上仅示例，不是真实业绩。日期按 Asia/Shanghai，金额 CNY；spend 为花费，orders/revenue 为支付订单/支付金额。金额最多 6 位小数；计数必须为非负整数。空白表示未知；不要把平台缺失值转换为 0。API 映射 `stat_cost/show_cnt/click_cnt/pay_order_count/pay_order_amount/total_play`，不根据 `play_over_rate` 反推完播次数。

每次导入声明的是所选广告主、完整日期范围、全部素材的日报快照。该范围内新批次替换旧批次，包括不再出现的素材；不做累加。范围内没有数据的日期仍有“收到完整快照”记录，但空数据指标保留未知。完全相同文件和范围再次导入是幂等操作，返回原批次，不重排批次优先级；若要修订，导入内容应实际改变。

计算：先合计有效范围数据，再计算比率，保留 6 位小数。支付 ROI=支付金额/花费；CTR=点击/展示；CPC=花费/点击；CPM=花费/展示×1000；CPA=花费/支付订单；完播率=完播次数/播放次数。分母为 0 返回未知。订单/点击为描述比值，不能视作严格点击归因转化率。支付 ROI **不是 ROI2，也不是利润率**。

只要某指标存在缺失，就不输出该指标的完整合计；缺少自然日时区间所有完整合计未知，但 JSON 保留 `observed_totals` 和素材表已观测合计。素材级汇总不代表单广告计划归因，不能用它推断多条计划的独立效果。不要混合不同账户、币种、自然日时区或指标口径。

## 状态与恢复

- 本地导出：awaiting_approval → queued → exporting → awaiting_manual；人工回执：submitted → active/paused/rejected/completed。
- awaiting_approval/queued 可以取消；已导出任务需在平台人工处理，网页不会撤回真实广告。
- 导出租约 300 秒；中断过期转 failed，不自动重试。新建投放任务必须重新人工确认。
- 报表：queued → fetching → completed/failed；同步租约 600 秒，中断时不应用半批数据，可人工重新同步。
- 所有写接口继承本地同源与会话 token；仅适用于可信单人本机环境，不提供多用户身份认证。
- 数据库 v3 在启动子进程前迁移。P1 备份 `var/backups/p1-before-p2/`。需要回滚时先停服务，用备份 DB 与 source.zip 成对恢复；不能用旧程序直接读 v3。

## 其他参考项目

本次针对 P2 下载并实际集成 Ocean Watch。TiktokVideo、ClipForge、vidcraft 尚未下载/安装；现有 P0/P1 工作台、解析和 FFmpeg 剪辑继续保留，避免为平台接口工作替换已运行部分。
