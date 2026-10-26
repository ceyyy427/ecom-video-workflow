# 六方向预览的复用依据

核对日期：2026-10-25。以本仓库已固定的来源为基础，不新增依赖，不修改 vendor。

| 来源 | 采用 | 未采用及原因 |
| --- | --- | --- |
| [Lemo Opuscar](https://github.com/lemomo-ai/lemo-opuscar/tree/3961ddb3d24d8876e0e2754f7790d66908acee51) | 固定提交的MIT风格文档；swiss-motion、blueprint、dataviz、paper-popup、dark-keynote、kino-montage的编排意图，来源跟随方案 | 不复制演示媒体或整套应用；59份资料不等于59个可执行模板 |
| [Remotion renderMedia](https://www.remotion.dev/docs/renderer/render-media)、[selectComposition](https://www.remotion.dev/docs/renderer/select-composition)、[Sequence](https://www.remotion.dev/docs/sequence) | 沿用已安装4.0.519；frame驱动、inputProps、每批复用渲染browser、H.264输出、退出清理 | 不升级到文档中较新的交互API，不另起视频引擎；适用许可沿用仓库既有声明，不能把Remotion整体称作MIT免费商用 |
| [Shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | 沿用本仓库已适配的有限配方、动作避让和来源记录；原Apache-2.0声明保留 | 不把Prompt当可执行代码，不下载并运行未审阅脚本 |
| FFmpeg、Pillow、SQLite、Pydantic | 复用既有入库、取段、解码、字体排版、状态与事务 | 不新增转码/动画/队列框架，避免占用Apple Silicon小内存机器的额外常驻资源 |

原始Lemo资料位于 `vendor/lemo-opuscar/2026-10-reference/`，SHA记录在SOURCES.json，catalog读取时校验。新增图示由项目内代码画出，只消费有限schema中的文字和数值，未复制上游图片、视频、声音。

## 本机成本与边界

- 沿用Node、Remotion、Python和FFmpeg环境，无新的模型或权重下载。
- 预览与正常制作共用SQLite计算租约；每次一个预览组，每方向两个镜头，现有渲染并发为2。完整制作任务优先。
- 预览为7秒、30fps、360×640，逐方向完成、可取消、可恢复有效项；总运行上限30分钟，队列最多8组。
- 缓存绑定冻结方案、素材SHA和真实渲染版本。相同文件复制到新安装目录不改变渲染版本；代码/字体变化仍产生新版本。
- 六结构由规则与已适配配方组织，不宣称调用大模型自由生成任意艺术风格或自动验证知识结论。

## 实拍使用

实测沿用[Maksim Semashko：Cutting Orange with Knife](https://www.pexels.com/video/cutting-orange-with-knife-13107467/)及[Pexels许可](https://www.pexels.com/license/)。源SHA：`60298358830713740127118ff7bb7a893cbd0a82f006b1127fbb5f506aeb1779`，与仓库2026-10-22既有许可记录一致。仅演示实拍剪辑，不作客户SKU、产地、口味或营养依据；原件不提交GitHub。知识主题为明确标记的工程预演，观察方法不冒充结构承载结论。

## 复核后修复

独立只读复核发现的八个重要接缝已纳入回归：空可选输入、改稿后的旧图示、原素材删除、损坏预览重试、引擎混用、选段/动作范围、异步旧选择、身份审批继承。修复复用了现有attach/current_context、visible_ranges、complete_events和cut_records；未知状态仍保留未知。
