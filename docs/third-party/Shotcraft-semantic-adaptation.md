# Shotcraft逐句混合适配 · 2026-10-19

固定来源：vendor/video-shotcraft/2026-10-full，commit43bd349a136651865ecfa6ea1cf012f6e957d304，Apache-2.0；原文/示例只读。完整参考索引124/150/150，不把索引当可执行模板。此前12卡有限适配/112卡仅参考，本轮新增3卡，累计15/109；项目版本卡34→38。

| 来源及依据文件 | 学习 | 本项目实现与舍弃 |
|---|---|---|
| effects/scan-bracket-sweep.md 与 ScanBracketSweep.tsx | 角标错峰收拢、短程扫过、停留 | 用户焦点四角收拢，一段同源媒体持续播放。放弃自动识别/测量外观和完整HUD，不伪造检测结果 |
| ui-entrance/row-embed.md 与 RowEmbed.tsx | 文字行短程立起落位、层级清晰 | 当前句完整引用信息行，数字静态，48字以内。放弃趋势动画、表格补值与片面价格大字；数据缺依据降级 |
| transition/transition-hidden-cut.md 与 InvisibleCut.tsx | 以遮挡掩住切点、保持节奏 | 前景媒体层14帧交接；字幕/声音独立，动作两侧避让。不是空间连续性证明，不照搬LightLeak/强白闪/Versus冲撞 |

新strategy字段包括内容类别、条件状态、完整引用ID、素材缺口说明。新推荐policy5逐句混合，旧1–4保留；未适配卡不会执行。动作/收尾保护、清晰度、镜长、事件预算、重复上限仍执行。手动选卡不能绕过完整数据/销售引用。修改单镜不重新规划其余镜头。

保留原vendor/索引SHA和原34卡内容；源文件、授权记录、实际applied recipe及保护降级可追溯。没有下载上游品牌资产、逐条观看150演示、模型调优或新增生成式云调用。实际许可商品样片和限制见SEMANTIC_MIX_USAGE.md及SEMANTIC_MIX_ACCEPTANCE.md。
