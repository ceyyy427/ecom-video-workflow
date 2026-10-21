# MoneyPrinterTurbo 字幕排版接入

## P12：再次检查配音、字幕与任务链路

检查固定提交 `9e7d8b7efa6b912058156943906542b53b945f0a` 的 `voice.py`、`subtitle.py`、`task.py`、`material.py` 和字幕写入工具后，适合本工作流的部分如下：

| 上游能力 | 本项目采用方式 | 当前状态 |
| --- | --- | --- |
| 实际字体宽度换行 | Pillow 排版进入现有 Remotion 成片与预览 | P11 已接入 |
| 字幕 cue 与原稿比较时规范 Unicode、忽略标点，展示仍保留原稿 | `speech_match.py` 适配 `_match_script_line` 的比较规则，并加入双向覆盖率，供历史文稿匹配建议使用 | P12 已接入 |
| 配音、字幕、素材阶段独立记录错误 | 本机识别的已知不匹配写成诊断结果，保留识别原文；页面明确显示匹配失败，不再误报 FFmpeg 故障 | P12 已实现项目自有适配 |
| 供应商词边界聚合成原稿短句 | 当前继续使用本机 ASR。现有火山响应适配器未保留经过校验的词边界，不能假装已有该数据 | 后续可扩展，尚未接入 |
| 在线素材搜索与批量拼接 | 主题相关素材不一定是同款商品，不能替代当前同款检查与动作选段 | 不启用 |
| Whisper 回退、云模型和配音服务 | 保留现有本机模型及火山独立凭据；此次不增加第二套模型下载和服务 | 不启用 |

上游 `subtitle.correct` 在低相似度时仍可能用原稿替换识别文案、对剩余稿件填入零时间段。本项目没有采用这一部分：不同内容仍会阻止分镜生成，历史文稿建议只载入编辑区，须人工核对和确认。匹配算法不是事实审核或自动听核。

新增适配的 MIT 版权声明在 `speech_match.py`，完整许可继续保留在本目录。中文同音字（如“倒/导”）在既有本机字级匹配中可作为语音锚点，页面仍显示原始识别结果供检查。

## P11：排版实现

固定提交：`9e7d8b7efa6b912058156943906542b53b945f0a`（379 个源仓库文件）。

采用范围：`app/services/video.py::wrap_text` 中的 Pillow 实际字宽测量、字体行高、显式换行、无空格长词/中文拆行、组合附加符与行首闭合标点处理。代码适配在 `ecom_video/subtitle_layout.py`，原项目完整保留在 `vendor/MoneyPrinterTurbo`，来源版本见同目录的 provenance JSON。完整源码通过浅克隆保存，不包含无关历史。

实际调用：

- `ecom_video/remotion_renderer.py::render_remotion` → `prepare_captions` → `layout_captions` → `wrap_text`。
- `ecom_video/remotion_renderer.py::style_previews` 使用同一入口。
- `render/remotion/src/Caption.tsx` 显示本地生成的透明 PNG；`index.tsx` 和 `directions.tsx` 仍按原有短语 start/end 激活字幕，标题的字级锚点与动效不变。
- 字体测量和像素绘制使用现有 `font_path()`，只读取本地系统/用户指定字体；不复制、分发上游字体和音效。
- `engine_hash` 包含新 Python 排版文件和 TSX；字体、算法或渲染组件改变后缓存自动失效。成片 manifest/shotbook 的各镜头保留无图像二进制的 `caption_layout`，包含原始短语、时间、换行、字号和像素尺寸。

边界：字宽最多 912px（1080px 竖版；最窄字幕容器扣除 padding 后的宽度），最多两行，字号在原设置与 40px 之间确定。超出两行且不能保持可读字号时明确报错，不裁切或删字。保留当前字幕容器的底部位置：实拍布局 160px、三种方向布局 245px、旧版布局 280px。这是当前模板安全区，不承诺适配所有平台按钮与遮挡。

未接入上游的脚本生成、云端 TTS/模型、图库搜索、随机素材拼接、自动上传、MoviePy 全链路或依赖安装。本流程仍使用已经确认的产品文稿、用户素材、同产品筛选、逐镜头修订和现有 Remotion/FFmpeg 音画渲染。PNG 仅承载现有字幕文字，不是商品证据图。SRT 导出继续保留原有整镜文稿和时间规则。

## 验证

```sh
.venv/bin/pytest -q tests/test_subtitle_layout.py tests/test_production.py tests/test_creative.py
npm run check --prefix render/remotion
.venv/bin/python scripts/check_mpt_subtitles.py docs/evidence/p11/mpt
```

验证脚本只使用临时目录，不连接数据库、不启动 worker、不读客户素材、不调用云。自动创建几何图与静音 WAV，验证实际 2 秒 H.264/AAC 成片、60 帧、1080×1920、两行中英文字幕、重复渲染缓存命中及三方向静帧预览。人工检查了导出的 `frame-045.png` 与 `frame-059.png`：长词完整显示、随后 1.5L 按短语时间切换、样例声明及底部安全区未被裁切。此结果仅证明离线合成技术路径，未验证真实口播内容或投放效果。
