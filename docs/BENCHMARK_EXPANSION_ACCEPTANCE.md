# 标杆片与扩展入口 · 2026-10-22验收

## 实际交付与人工确认

藏蓝软壳衣A版29.766667秒，1080×1920、30fps、893帧。用户看听两个开头后选“动作先行”，实际试听并确认文稿/声音/最终分镜，再实际看听主片并回复“已完整看听，认可这版主片”。确认仅绑定此主片，不延伸到工程测试版、本机声音或其他新版本。

主片SHA-256：`153f7b3f6cb4ed7b06e002ab1c36ad5d8e1f22d98e898c4fbb6b61142a36c203`。

私有交付ZIP含MP4、文稿说明、真实人工确认及工程核验记录，SHA-256：`2e5e0746c6dd8556dbfbb39a283dd636e92dfdaf48095de2fe6b2ebc4579b61d`。文件位于仓库外本机评估目录，未公开到GitHub。原29.1秒版本及原项目不覆盖。

## 成片与单镜验证

- 开头完整泼水之前先作动作预告；保留口袋、上身、袖口/下摆与完整原速泼水观察段，再上身收尾。预告不冒充完整动作。
- 无镜号、进度线或默认工程标题；关键词字幕不对估算字时间作伪精确逐字强调。
- 第3镜品牌/型号换行修正：仅此镜文件变化，其余5镜文件哈希不变；整片解码PCM哈希不变。不是用截图或参数相等冒充实际文件复用。
- 新主片重新严格解码通过；实际帧数、尺寸、帧率及交付ZIP校验通过。没有新增云TTS请求，没有投放。
- 本标杆在仓库外专用制作目录完成，人工收据绑定成片；没有把它伪装成旧客户任务的新审批。普通工作台已接入逐镜客户画面模式，六场景/五段有声的通用编排还需下一阶段产品化。

## 程序修复与兼容

- `presentation`为逐镜可省略字段；历史任务规范化签名不因缺省字段变化。恢复历史样式不删声音或旧文件，更新仍需原有人工确认。
- 客户模式复用NarrativeShot的全部配方与转场，两侧衔接仍走统一边界决策；动作保护继续由已有编排执行。不支持的无计划旧配方明确拒绝，而非静默丢效果。
- 长句无法放入两行时沿用已有分页；不确定句边界保留原时钟；备用PNG也使用白色。型号保护只改排版，不改字词、文稿条件和配音。
- 源码升级改变渲染引擎指纹，重新生成可能使旧缓存失效；“只改一镜其余复用”适用于同一引擎版本内的局部画面修改，不承诺跨升级复用旧缓存。
- VoiceStudio具体模型在生成时验证；原生状态名不充当实际缓存模型证明。固定模型、revision、中文预置音色，拒绝WebSocket/远程Host/浏览器Origin等旁路；状态与音频均有界读取，失败不保存半成品或自动转云。

## 测试证据

全量非浏览器Python回归：**980 passed、3 skipped、1 deselected，250.58秒**。该轮之后补充WebSocket/Origin及冷启动状态回归，相关六个测试文件重新执行32 passed（其中bridge4项）。前端38 passed，Remotion TypeScript及新增Python代码Ruff通过。

第一次裸跑曾因未安装Playwright导致`test_focus_frame_contains_requested_media_point_in_actual_browser_layout`失败；没有安装或调用浏览器工具、没有改测试掩盖失败。按用户不使用Computer Use的约束，后续明确排除此项；不声称真实浏览器布局验收通过。

```sh
.venv/bin/python -m pytest -q --deselect tests/test_shotcraft_render.py::test_focus_frame_contains_requested_media_point_in_actual_browser_layout
.venv/bin/python -m pytest -q tests/test_voicestudio_bridge.py tests/test_local_voice.py tests/test_client_finish.py tests/test_client_render.py tests/test_client_presentation.py tests/test_film_styles.py
node --test tests/web/*.test.cjs
npm run check --prefix render/remotion
```

HTTP验收使用仓库外复制的客户运行目录和loopback8790端口；原客户数据保持原位。新入口不创建审核，测试夹具从未记作客户人工审批。

## 扩展能力的实测边界

- Lemo：59套STYLE与元数据，127个上游文件加本项目SOURCES清单，固定来源与哈希；按主题/受众/气质检索六个方向，实拍模式优先剪辑/实证结构，允许自主指定参考。当前不是六个动态预览或通用自动成片器。
- 本机声音：官方VoiceStudio0.5.6隔离环境、固定Kokoro模型与中文扩展，真实生成7.85秒/24kHz/单声道WAV。首次成功37.907秒包含水印模型下载，就绪后同稿2.549秒；ASR对应中文但有一个同音字差异。自然度待人工听核，客户主片仍用已认可的火山声音。
- Concat：借鉴编辑文档、命令与Agent接口的分工，未复制其AGPL渲染引擎或声称已提速。n8n：仅inactive手动检索样例，未装入客户包或实际导入执行。
- 未新增数据库表或迁移；已发布Mac包仍为0.17.0，本轮是开发分支能力与私有标杆交付。

## 回退与下一步

逐镜选“保留历史样式”，或恢复原制作版本。配音选择火山/上传即可停止依赖VoiceStudio；关闭独立服务不影响剪序启动。`/ideas`独立入口可以停用，不影响原商品三方向及审批。

源码回退使用本轮独立提交的反向提交，先保存当前未提交修改；不要重置整个工作树或覆盖客户数据目录。保留已有MP4/WAV/审核记录，不用恢复数据库来撤销展示功能。

下一步按顺序：六个真实动态预览→通用创作/一致性协议与制作版本→本机配音人工比较及Mac一键交付。来源与采用依据见[开源记录](third-party/concat-lemo-voicestudio-n8n.md)，声音配置见[指南](VOICESTUDIO_LOCAL.md)。
