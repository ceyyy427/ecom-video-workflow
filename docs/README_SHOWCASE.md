# README 展示素材与页面图

更新：2026-10-22。本轮只更新文档和展示媒体，不改变生产代码、模型、审核或已有客户项目。

## 排版参考

- [NarratoAI README](https://github.com/linyqh/NarratoAI/blob/dcdb819e893a3f95b01d68e7e815540ac3522d24/README.md)：简短介绍后直接展示界面，随后提供功能和启动方式。
- [MoneyPrinterTurbo README](https://github.com/harry0703/MoneyPrinterTurbo/blob/33dde166da7f75287ea727c10e37243f03d167c8/README.md)：预览优先、入口清楚、详细说明分层。
- 沿用已确定的 taste-skill framed-sheet 工作台方向。文字与页面图为本项目原创，没有复制上游截图、品牌、赞助或宣传文案。

## 实拍来源和范围

[Cutting Orange with Knife](https://www.pexels.com/video/cutting-orange-with-knife-13107467/)，作者 Maksim Semashko。2026-10-22复核 [Pexels License](https://www.pexels.com/license/)，允许在项目宣传页面中使用和修改；不表示作者或画面人物背书，不转售原片，不将其作为客户真实SKU、产地、甜度或营养依据。

已有本机源文件 SHA256：`60298358830713740127118ff7bb7a893cbd0a82f006b1127fbb5f506aeb1779`。仅复用已核验的本机文件，不重新下载参考视频或分发原始MP4。

| 文件 | 内容与性质 |
|---|---|
| `readme-real-showcase.jpg` | 现有20.2秒鲜橙工程样片的实际帧：cinema第1.2秒、collage第16秒、evidence第10.8秒。为展示不同镜头，时间位置不同，不能称同帧风格比较 |
| `readme-real-demo.gif` | 三条同源样片开头4.8秒并排片段；无音轨，6fps压缩预览；不是完整动作、配音自然度或客户签收证据 |
| `readme-editor.png` | 根据现有剪辑工作台绘制的页面布局示意，内嵌原视频第2/7.5/11.3秒的许可实拍帧；时间线和控件用于说明操作，不是浏览器截图 |
| `readme-prompts.png` | 参考库布局示意，使用同一许可素材；说明项目/句子选择、规则适配和带回草稿的现有能力 |
| `readme-review.png` | 审核布局示意，内嵌实际样片帧；所有勾选保持待确认，没有制造人工签收或投放数据 |

生成记录和派生文件SHA见 [readme-media.json](media/readme-media.json)。图片中的字体从本机渲染为像素，不分发字体文件。

## 验证和边界

- 本轮未使用 Computer Use，没有浏览器截图或页面像素验收。真实效果帧与页面示意在README和图片内均区分标注。
- 三条微信参考视频仅作参考，不截帧公开；客户软壳衣、人物肖像、私有项目、配音与音乐未进入本轮文档媒体。
- 用 Pillow/FFmpeg 复用已有成片与许可素材，检查图像解码、尺寸、GIF帧数/时长、来源SHA、README本地链接及提交范围。没有新增依赖、云调用或平台写入。
- 程序版本仍为0.17.0，原Mac安装/升级包及其SHA不变。原来的绿色道具媒体从README中撤下，历史文件保留供版本追溯。
