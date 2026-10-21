# Shotcraft 镜头配方接入 · 2026-10-18

在原有 Remotion 制作流程中加入有限、可审计的镜头配方。风格推荐仍由本机规则根据商品、类别、人群与气质匹配；逐句文稿决定开场、操作、细节与收尾的编排。本次没有新增模型、云调用或平台写入。

## 如何操作

1. 在 `/create` 上传资料、图片/实拍/配音，人工确认事实与文稿，保存商品类别、人群和希望气质。
2. 三张推荐卡同时显示“镜头组合”与配音建议。选定方向，配音完成本机对齐和人工听核后生成分镜；纯展示无需配音。
3. 每镜选择“动效配方”，展开说明可读本项目 Prompt 及上游卡片链接。字卡最多8字，必须摘自本镜已确认文稿。
4. “静止留看”关闭该镜额外图形动作；“保留历史编排”使用原有布局和效果。细节框使用水平/垂直焦点，必须看实际商品位置后调整，它不识别或测量商品。
5. 草稿可改转场。已生成版本的单镜修改保留转场，避免连带修改相邻镜头；保存后生成新版，父片保留。只改视觉配方不会重新合成声音。
6. 生成后仍需人工听核和审片。样片入口 `/samples#motionExamples` 可比较同文稿、同配音、同实拍选段的升级版与此前版本，并下载分镜、字幕和仅第三镜关闭动效的对照。

## 首批支持

| 配方 | 实际适配 | 使用限制 |
|---|---|---|
| 关键词冲击 | 标题6帧急推、5帧回收 | 默认用于有足够时长的利落开场；不放大裁掉实拍商品、不震屏 |
| 手绘划线 | 标题落定后延迟6帧，10帧写出一笔 | 只强调已确认标题，不新增卖点 |
| 词组浮现 | 按中文词组上移、清晰入场 | 人声词锚点驱动；图片与实拍均可 |
| 细节聚焦 | 扫描线与焦点框 | 焦点为人工可调构图点，不是自动目标框或事实证据 |
| 分阶段展开 | 完整实拍→标题→进度标记 | 操作句保持原实拍动作；没有虚构价格、折扣或商品拆解 |
| 底边推叠 | 整章与品牌底色向上接力 | 适配为两半品牌底色桥，不是上游两段素材同时重叠的26帧演示 |
| 线条接力 | 上镜延伸的线在下镜收回 | 默认全片一次；适配为短边界衔接，不是上游6.3秒连续世界运镜 |

收尾默认静止留看；不足时长的镜头使用轻量配方，靠后的人声锚点不提前或伪造字幕时间。新动效不能补出缺失的商品动作或提高同款识别精度。

## 数据与兼容

- `Shot.shot_recipe` 为有限枚举，缺失/null 保持旧渲染；`none` 表示使用新布局但关闭额外动效。
- `transition` 增加 `push-stack` / `line-carry`。入口/出口转场、字幕配色使用一致的渲染分派条件；旧任务不会被自动写回或升级。
- 客户规划说明保存逐句选择理由；`shotbook.json` / `manifest.json` 的 `scenes[].motion_recipe` 保存配方版本、已确认原句/标题、本地 Prompt、来源卡、commit 与许可。Prompt 是可审阅的数据，不作为命令、代码或网络请求执行。
- 缓存键包含引擎源码、配方、入口/出口转场、局部词锚点与素材 SHA。只换配方会使该镜失效；草稿修改转场可能使前镜失效；更换引擎实现会使旧缓存失效，但旧成片保留。
- 无数据库迁移，schema 仍为14。回退时恢复本次源码并重启；新配方 JSON 需保留备份，旧程序不能直接编辑包含新枚举的新版分镜。

## 来源与许可

[官方库](https://vincentwei1021.github.io/video-shotcraft/library.html) 的当前目录远多于本轮适配范围；没有宣称全部效果已接入。参考源码 Apache-2.0，来自 Vincentwei1021/video-shotcraft。

- 新增只读参考固定 commit `43bd349a136651865ecfa6ea1cf012f6e957d304`，位于 `vendor/video-shotcraft/2026-10-motion/`：5份镜头卡、5份对应TSX及LICENSE；每份原文件 URL/SHA256 保存在 `SOURCES.json`。
- 旧 BlurSlide / Scanline 参考继续固定 `5ddbf521038b0a7accfb6dc1e0a9eb29c67277ab`，见 `docs/P6_SOURCES.md`。历史 vendor 文件未覆盖。
- 本项目 `RecipeShot.tsx` 为竖屏、人声锚定的改写，标明修改与来源；保留许可证。没有使用上游演示中的品牌图片、价格、字体、音乐或成片素材。
- 两商品实拍沿用 `examples/category-demo/LICENSE-SOURCES.md` 中的 Pexels 许可记录，公开的仅是加工后样片；原始stock没有下载入口。

## 核验与复跑

轻量：`.venv/bin/pytest tests/test_shotcraft.py tests/test_shotcraft_render.py tests/test_sample_library.py -q`；完整：`.venv/bin/pytest -q`；`npm --prefix render/remotion run check`。

交互：`.venv/bin/python scripts/check_shotcraft_ui.py`。只用隔离fixture，故意中断风格帧请求以检查失败时仍能选方向，不宣称这些截图是实际商品风格帧。

实际渲染需已有跨品类冻结任务及原素材目录。以下参数为本次本机隔离路径，可换成对应复跑目录；不存在时先按 CATEGORY_VALIDATION_ACCEPTANCE.md 重建，不会自动转云：

```sh
.venv/bin/python scripts/build_shotcraft_samples.py --data /tmp/ecom-shotcraft-final-20261018 --headphones-runtime /tmp/ecom-categories-20261018/headphones-v2/runtime --serum-runtime /tmp/ecom-categories-20261018/serum/runtime
.venv/bin/python scripts/publish_shotcraft_samples.py --data /tmp/ecom-shotcraft-final-20261018
```

发布前检查旧片 SHA、词锚点与实拍区间、单镜修改4次缓存命中/1镜渲染、其余四镜文件和整条原始配音一致；示例保持 `needs_review`。本次结果见 SHOTCRAFT_ACCEPTANCE.md 与 `docs/evidence/shotcraft-integration/`。
