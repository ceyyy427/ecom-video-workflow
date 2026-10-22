# 开源采用记录 · 2026-10-22

本机 Apple Silicon / 8 GiB 内存；磁盘核对时余约88 GiB。来源均通过官方GitHub读取，资料下载校验Git blob SHA与SHA-256。下列提交为本轮固定来源，不使用Star数量作为采用依据。

| 项目与固定提交 | 本轮读到的事实 | 采用 | 暂不采用及依据 |
|---|---|---|---|
| [Concat](https://github.com/jub0t/Concat/tree/797c8c707be5f2c798bb99e0fffad20612552510) | AGPL-3.0；本地Rust/Slint编辑器；JSON-RPC入口；文档描述GPU合成、代理和硬件解码；语音为whisper.cpp/sherpa-onnx | 参照编辑文档与命令边界、Agent API、独立模型设置；本轮客户原画模式保持既有编辑/回退协议 | 未复制AGPL引擎或替换Remotion。另维护原生引擎会增加编译和项目格式兼容成本，且没有本机同素材性能对比，不能据其README承诺本项目提速 |
| [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar/tree/3961ddb3d24d8876e0e2754f7790d66908acee51) | 59套现成风格；代码和文档MIT；示例影片及截图CC BY 4.0，部分语音明确排除；上游说明模型间效果可能不同 | 导入59套STYLE与style.json、索引和许可，共127个校验文件；本机六方向关键词检索及受主题约束的Prompt交接 | 未复制上游音轨/影片/第三方图片，未将参考文档作为执行脚本。未声称59套已在现有渲染器完整实现 |
| [VoiceStudio](https://github.com/debpalash/VoiceStudio/tree/28bf2c7a83b8a64836297340c52a45d716684aed) | 应用AGPL-3.0；Apple Silicon macOS≥13.3，安装文档约需10GB空间；本地OpenAI兼容TTS接口；具体模型单独许可 | 独立loopback REST适配、页面选择、文稿版本绑定、试听/声音历史；固定普通合成、不提供克隆 | 不嵌入应用、不自动启动默认NC权重；非本轮许可/中文范围的引擎拒绝合成。接口模拟测试与真实模型实测分开记录 |
| [n8n](https://github.com/n8n-io/n8n/tree/df4bafc400f6013dca215bdebe47faa81a170d7f) | Sustainable Use License；源码可读但存在使用和分发限制；服务器需要独立Node/Docker运行环境 | 手动启动的本机创意检索JSON样例；使用现有HTTP接口和会话校验 | 未装入交付包，未加自动审批/投放节点，无证据将调度器当作推理加速器 |

VoiceStudio 官方稳定版安装包另固定为 `v0.5.6 / VoiceStudio-Electron-0.5.6-mac-arm64.dmg`，GitHub发布资产digest与下载SHA-256一致：`821d011faf255cd6315dba969ce1572ef850ae6159fcc55d94dcb9fe86259834`。应用资源按原样复制到独立评估目录，依赖按其uv.lock隔离安装，不改剪序Python环境。

## 模型筛选

- [VoiceStudio LICENSE-NOTICE](https://github.com/debpalash/VoiceStudio/blob/28bf2c7a83b8a64836297340c52a45d716684aed/LICENSE-NOTICE.md) 区分应用、模型和分词器，默认OmniVoice权重标非商业；未作为客户默认引擎。
- [Supertonic 3](https://huggingface.co/Supertone/supertonic-3) 公开31语言表未含中文，模型为OpenRAIL-M；未将“轻量多语种”推断为中文可用。
- [Kokoro原模型](https://huggingface.co/hexgrad/Kokoro-82M) 与 [MLX转换](https://huggingface.co/mlx-community/Kokoro-82M-bf16) 标注Apache-2.0；原模型VOICES列出普通话声音，也提醒非英语质量与G2P覆盖有差异。初选用于Apple Silicon实测，不据许可标签推断整体音质、全部依赖权利或人物授权。

## 实测中采用的上游修正方式

- VoiceStudio0.5.6的状态接口读取偏好，OpenAI合成接口可能复用另一具体模型的缓存实例。新增小型专用启动扩展校验实际实例，而不是复制整套TTS服务；固定模型/版本/音色、限制HTTP入口并拒绝全部WebSocket。模型名称相同但无生成绑定的原生服务不自动采用。
- 按[MLX-Audio Kokoro官方文档](https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/kokoro.md)补齐`misaki[zh]==0.9.4`；六个新增中文依赖已固定版本并核对PyPI许可为MIT，misaki为Apache-2.0。未扩大到英文/日文等依赖栈。
- MLX-Audio0.5.0的音色查找默认指向`prince-canuma/Kokoro-82M`，导致已有另一仓库权重仍离线失败。参照MIT项目[Kokoro Studio固定源码](https://github.com/darylalim/kokoro-studio/blob/d129be629339439a2a0747e0c322d6f3f8689f10/streamlit_app.py)，将已载入模型及其pipeline的`repo_id`绑定到已校验的Kokoro仓库；不再下载第二套模型，也未复制该应用界面。
- 保留VoiceStudio自带合成水印行为；首次成功合成另下载上游[AudioSeal](https://huggingface.co/facebook/audioseal)约56MB，模型卡标MIT。首次37.907秒包含该下载，就绪后同稿2.549秒；两次耗时分开记录，未把网络初始化算作纯推理速度。
- 独立环境1.8GB，Kokoro缓存380MB；本轮真实7.85秒中文WAV可被本机ASR识别，听感仍待人工确认。未据此切换客户配音默认项或发行新版安装包。

上游README和代码是参考资料，不授予本项目自动审批、任意shell执行、网络访问或公开客户内容的权限。
