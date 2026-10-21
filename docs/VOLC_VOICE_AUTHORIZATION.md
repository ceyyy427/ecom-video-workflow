# 火山语音授权与三版换声 · 2026-10-17

## 已核实的授权情况

- 初次SSE短句：HTTP200，`45000030`，包含 `requested resource not granted`，无音频；官方当前HTTP路径初次诊断403，无音频。
- 用户确认 `default` 项目的“语音合成2.0”已开通、同项目语音Key启用；随后一次SSE复测仍拒绝。再经只读控制台核对，服务已开通、运行中，按字数计费，有可用额度。未点击购买、开通、权限变更、创建/显示Key等按钮。
- 本机检查：`~/.zshenv` 中该变量有1条简单赋值，与实际加载值一致；环境变量与私有文件的语音Key一致，且不同于ARK Key。只输出布尔结果，未输出凭据或片段。
- 随后官方当前HTTP返回音频块及成功结束码；原SSE短句也完整成功，实际音频2.832秒，ffprobe通过：成功回执（历史记录或本机文件，未随公开版分发）。未更改Key、资源`seed-tts-2.0`或生产SSE地址。
- “控制台授权稍后生效”与这些现象相符，属于推测；客户端无法证明后台的具体生效时间或为何先拒绝。不能把所有45000030一概当未开通，不能把内部资源名改进请求绕过权限。

实际需要的服务：**豆包语音合成大模型2.0 / 语音合成2.0字符版**，Key与服务同项目且启用。不需要为此开声音复刻、ASR、RTC或广告平台权限；不需要创建千川应用、OAuth回调或另购方舟Agent Plan。后者是专属Key及另一接口路径，不能混用。

操作入口：[新版控制台概览](https://console.volcengine.com/speech/new/overview?projectName=default) → 左上选择Key所属项目 → **开通管理**查看服务与额度；同项目 **API Key管理**核对启用。具体步骤与本机换Key方式见 配置指南（历史记录或本机文件，未随公开版分发）。

## 本机修复

- `VoiceError`采用固定脱敏分类；明确资源拒绝提示同项目的2.0字符版与Key，HTTP401提示凭据，普通403保留原因不确定，429提示频率/配额，网络异常单独提示。
- API保留旧版字符串`detail`，增加`X-Voice-Error-Code`；不回显原始响应、Key、请求ID。不自动重试、换Key、切产品或降级成本机声音。
- 新命令 `scripts/volc_voice_check.py` 默认仅本机检查、0次云调用。显式`--probe`只发一次固定短句，需完整终止成功和真实音频检查才能返回`live_verified=true`，临时音频清理、不写业务库或审核记录。
- 修复非200错误体按1024字节聚合导致90秒预算延迟检查；真实HTTPX传输接口的纯内存滴流回归由模拟9216秒降至99秒上界。大小预算仍8192字节，未知/截断错误回退固定消息。
- `synthesize`新增内部keyword-only语气/语速参数：语气≤300字、语速整数[-20,20]；按官方`req_params.additions.context_texts` JSON字符串传递，语气不混进朗读文稿。页面API仍只允许原有字段，不开放任意地址或模型资源。
- 样片缓存签名及`voice-source.json`包含实际音色、语气、语速；本机旧声音缓存签名保留兼容。新声音不自动取得人工听核通过。

## 三版制作记录

三份原稿不变。Cinema轻声克制（Vivi、-5），Social朋友分享（Vivi、+5），Lab自然讲解（高冷御姐、0）。实际云端整稿音频长17.760 / 18.744 / 24.696秒；本机FireRed逐字识别后，20个语义句本次匹配均1.0，按每镜停顿重排到26 / 27 / 28秒。匹配分数不代表真人核听。

旧成片、声音、分镜、来源回执与目录备份：本机回退目录（历史记录或本机文件，未随公开版分发）。备份不在样片API公开范围。云合成全部完成后才启动三版重渲染；新版已更新到 [样片对比页](http://127.0.0.1:8765/samples)，刷新即可观看、下载、试听。镜头坐标、语气、语速同步保存在 配方（历史记录或本机文件，未随公开版分发）及每版`voice-source.json`/`preview-job.json`/manifest。

种草版切回工作画面16.400秒，对应“再”16.410秒；细节版“放”16.529秒，放杯选段从16.300秒接入，改用原片0.2–1.8秒的放杯/松手画面。最终这次画面修订复用原配音缓存，未新增TTS；仅重渲1镜、复用6镜。切点是逐字锚点和人工素材观察后的近似编排，不声称自动检测动作已被真人确认。

本轮实际TTS请求：5次有界短句诊断（其中2次成功返回音频），3次完整稿件合成，共8次；无自动重试，无广告平台请求。成功调用可能按账户计费，以平台用量为准。

## 验收与边界

全量 **405 passed / 1 skipped，77.45秒**：最终日志（历史记录或本机文件，未随公开版分发）。跳过项为未opt-in的macOS Keychain。针对语音的29项测试通过；覆盖真实脚本人工确认、并发拒绝、SSE完整性、实际MP3探测、脱敏、错误分类、零网络默认、滴流预算与语气参数。测试仅HTTP传输模拟，未用真实Key或计费；真实成功另由上述回执证明。

| 成片 | 长度/帧 | 综合响度 / 真峰值 | 人工状态 |
|---|---|---|---|
| 一杯的空白（历史记录或本机文件，未随公开版分发） | 26秒 / 780帧 | -16.01 LUFS / -1.39 dBTP | 待听核、待审片 |
| 把日常接上（历史记录或本机文件，未随公开版分发） | 27秒 / 810帧 | -15.98 LUFS / -2.34 dBTP | 待听核、待审片 |
| 先把外观看清（历史记录或本机文件，未随公开版分发） | 28秒 / 840帧 | -16.03 LUFS / -1.50 dBTP | 待听核、待审片 |

- 新片均1080×1920/30fps/H.264/AAC48k；全部真实视频资产、SRT时间在成片范围内。三份新视频/声音SHA、来源回执、字幕结束时间、ASR分数及缓存：交付记录（历史记录或本机文件，未随公开版分发）。`approvals=[]`、`human_reviewer=null`、`human_listening=pending`。
- 媒体和浏览器验收（历史记录或本机文件，未随公开版分发）：三条实际播放、Range下载、附件下载、互斥播放、1440/390px，0 pageerror、0越界或业务写请求。执行者回查了 Cinema（历史记录或本机文件，未随公开版分发）、Social（历史记录或本机文件，未随公开版分发）、Lab（历史记录或本机文件，未随公开版分发）新片抽帧，不把自动检查当真人听核或客户审美验收。
- Ruff（历史记录或本机文件，未随公开版分发）、格式（历史记录或本机文件，未随公开版分发）通过；Remotion实现未改动，三版同一渲染器代码哈希。HyperFrames使用量查询本轮可用，但沿用既有Remotion，未迁移框架或安装模型。
- 主库与备份核对（历史记录或本机文件，未随公开版分发）：45张业务表行哈希不变，外键检查空、integrity=ok；旧三版备份视频SHA正确。确认无活跃制作/对齐/执行后刷新loopback API，保留P13–P16开关、平台写入关闭，未新启动任何worker。SQLite备份于`var/backups/volc-authorization-before.sqlite`。

独立只读审查提出1项Important（聚合读取延迟检查）和1项Minor（空白绕过语气长度），已先复现再修复；回归记录见 滴流RED（历史记录或本机文件，未随公开版分发）、长度RED（历史记录或本机文件，未随公开版分发）、GREEN（历史记录或本机文件，未随公开版分发）。

需要回退展示时，先备份当前云版，再从上文备份恢复三个style目录、`library.json`及`recipes.json`。若要继续本机版制作，须显式用`--local-voices --prepare-only`重新准备一致的工作目录后再渲染，不直接拿旧快照配当前工作素材。按现行配方重制不保证旧视频字节一致；备份里的MP4可精确恢复。无需回滚或清空业务库。

复跑（`--probe`和`--generate-voices`会显式使用云服务，可能计费；其他命令不合成云音频）：

```sh
.venv/bin/python scripts/volc_voice_check.py
.venv/bin/python -m pytest tests/test_volc_voice.py -q
.venv/bin/python scripts/volc_voice_check.py --probe
.venv/bin/python scripts/build_client_samples.py --generate-voices --prepare-only
.venv/bin/python scripts/build_client_samples.py --render-only
.venv/bin/python scripts/check_client_samples.py
```

只读配置状态不等于在线验证；短句成功不保证其他音色/长稿成功。三条样片依然是示例杯子的待审预览，不是客户SKU验证或性能证据；事实、文稿、风格、听核、成片均保留人工确认。无vendor修改、schema迁移、自动投放、提交或外网部署。

## 官方依据（本轮读取）

- [新版控制台：开通管理、API Key与项目隔离](https://docs.volcengine.com/docs/DoubaoVoice/QuickStartNewConsole?lang=zh)
- [当前HTTP：Key入口及seed-tts-2.0资源](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)
- [SSE V3：结束码、语速与语气指令字段](https://docs.volcengine.com/docs/DoubaoVoice/HTTPChunkedSSEUnidirectionalStreaming-V3?lang=zh)
- [Agent Plan专属Key和专用路径](https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh)
