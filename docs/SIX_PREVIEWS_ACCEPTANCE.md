# 六方向动态预览 · 一期验收

日期：2026-10-25。Apple Silicon Mac；未新增依赖、模型下载、云调用或平台写入。

## 结果

| 项目 | 实测 |
| --- | --- |
| 鲜橙实拍 | 6条真实MP4，每条7秒／210帧，360×640；单条27.809–30.770秒，总177.690秒 |
| 无素材图示 | 6条真实MP4，每条7秒／210帧；单条14.263–15.991秒，总88.569秒 |
| 动态与差异 | 12条严格解码通过；每条镜内抽帧有变化；每组六个输出SHA不同，并离线检查两组画面 |
| 复用 | 相同输入再次请求不新增渲染、不改文件或审批；取消后保留有效项，损坏项可重做 |
| 制作入口 | 选择后创建独立待确认项目；原文稿、素材、配色、镜头ID和配方沿用共同计划 |
| 整片工程回归 | 两类各24秒／4镜；实拍修改第1镜入点，图示修改第1镜运镜；其余3镜文件SHA相同，音轨PCM与SRT相同，缓存命中3／重渲1 |
| 恢复 | 切回历史活动版；原参数、素材、成片、审核记录保留，只增加恢复操作事件 |
| 旧库迁移 | 升级前真实库备份包含510份文件；在独立恢复副本由schema14升级15，48张旧表内容指纹保持，只新增3张idea表 |
| 自动检查 | Python 1010通过、4跳过；按约束排除1个浏览器布局测试。前端Node 44通过；TypeScript、Ruff、diff检查通过 |

耗时是本轮新方案的实际渲染记录，未复用已完成预览；依赖和字体可能已有热缓存，并与测试共享本机资源。**不是本机视觉模型首次推理的性能比较**，没有改变现有模型默认后端或质量阈值。

实拍来源与许可见 [复用依据](third-party/six-previews-reuse.md)。实际素材仅14.3秒；24秒工程片用于验证制作、修改和缓存，包含源画面复用，不作客户标杆片或商品事实证明。知识主题为观察方法的工程预演，不冒充已经核验的承载原理讲解。

## 人工门禁

实际预览运行库没有客户事实、文稿、风格、听核或成片审批。工程整片测试先把数据恢复到单独目录，以 `AUTOMATED FIXTURE` 标记测试确认；两条片均停留待审，未记录客户签收，也未作为实际听核。

已核对：空受众／气质仍可采用六个方向；过期输入和异步旧响应不能重新启用采用；旧身份声明降为待核对来源。改稿后的旧图示、未确认图表数值被拦截。原素材删除后冻结副本与备份有效。

自动选段的安全素材与入点不被展示方案覆盖。已有当前分析及人工完整动作声明可复用；未知不变成已验证。单段、多段都检查源可见范围和完整动作；已知动作保持原速，保护窗映射到对应镜头。

## 执行方式

```sh
.venv/bin/python -m pytest -q --deselect tests/test_shotcraft_render.py::test_focus_frame_contains_requested_media_point_in_actual_browser_layout
node --test tests/web/*.test.cjs
(cd render/remotion && node_modules/.bin/tsc --noEmit)
.venv/bin/python scripts/accept_six_previews.py --workspace /tmp/six-preview-check --source /path/to/authorized-13107467.mp4 --stage previews
.venv/bin/python scripts/accept_six_previews.py --workspace /tmp/six-preview-check --stage regression --simulate-confirmations
```

脚本固定核对既有鲜橙素材SHA，不能替换文件后仍冒用许可记录。客户自己的素材从页面制作。验收目录须独立于仓库，实际客户目录不能用来模拟审批。

本机留存：`preview-acceptance.json`、两组contact图、`regression-latest.json`及工程子目录、`production-migration.json`、升级前schema14备份目录和可在维护页导入的ZIP。文件位于本轮指定的仓库外验收目录，不提交媒体或客户备份到GitHub。

## 使用与回退

操作见 [六预览指南](SIX_PREVIEWS_USAGE.md)。首期适配6个结构，其余53种仍是参考资料；预览静音。复杂图示、任意画风、全自动知识核验、配音重做不在本期新增范围。既有本机模型、逐镜编辑及听审入口保留。

- 不满意的方案可以保留旧版并重新生成；修改后的制作版本仍按原门禁审核。
- 当前主库未被本轮工程运行改写，已另存升级前备份。主库启动新版时只追加schema15三表。
- 需要软件回退时，使用升级前Mac交付包，在新目录通过维护页导入schema14备份；核对项目、音频和审核后再切换。源码基点为 `f264e89dcde52a938ee12f5cb69efcec2ca92b45`。
- 不把15库强行改成14，不覆盖当前数据目录，不删除新版本或旧成片来回退。
