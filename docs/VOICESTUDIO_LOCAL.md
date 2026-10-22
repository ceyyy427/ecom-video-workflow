# VoiceStudio 本机配音 · 开发分支

这是独立服务的可选入口，尚未加入已发布的0.17.0 Mac安装包。现有火山配音与上传声音继续使用；停用本服务不影响剪序启动。

## 已验证的组合

- Apple Silicon，8GiB内存的本机；Python3.11.17。
- 官方VoiceStudio `v0.5.6`，官方锁文件隔离环境；MLX-Audio0.5.0 / MLX0.32.1。
- Kokoro-82M-bf16 固定revision `a71e4d38b236d968966a2002c4c895dbd12b1c3c`，中文女声 `zf_xiaobei`。
- 中文处理需额外安装 `misaki[zh]==0.9.4`；本轮补齐的固定版本为cn2an0.5.24、jieba0.42.1、ordered-set4.1.0、proces0.1.7、pypinyin0.55.0、pypinyin-dict0.9.0。只安装到VoiceStudio独立环境，不改剪序依赖。

应用为AGPL-3.0，具体模型与依赖许可另行核对；默认OmniVoice权重的非商业限制不适合直接作为客户商用默认项。本轮Kokoro及MLX转换标注Apache-2.0。采用依据见[来源记录](third-party/concat-lemo-voicestudio-n8n.md)。

## 在独立环境启动

先从[官方发布](https://github.com/debpalash/VoiceStudio/releases/tag/v0.5.6)取得Apple Silicon包或对应源码，安装其锁定依赖，并按[MLX官方说明](https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/kokoro.md)补齐中文扩展。下载模型时固定上述revision，核对文件哈希；不要手动修改模型配置文件。

在剪序仓库根目录，用VoiceStudio独立环境中的Python执行：

```sh
/path/to/voicestudio-env/bin/python -m ecom_video.voicestudio_bridge \
  --backend /path/to/official-voicestudio/backend \
  --cache /path/to/verified-model-cache \
  --data /path/to/separate-voice-data \
  --port 3900
```

以上是路径占位示例。`cache`需采用Hugging Face标准缓存布局，其中Kokoro的`refs/main`指向指定revision；启动器校验权重SHA，并固定离线模型查找。首次水印模型可能由上游另外下载，不能把首次启动耗时算作稳定合成速度。

专用服务沿用上游实际合成入口，生成前检查实际缓存后端，音色张量使用同一已下载Kokoro仓库；只开放本机状态、契约和语音入口，拒绝WebSocket、浏览器Origin、远程Host、其他引擎和克隆参数。它不会打开或重配用户原有VoiceStudio桌面应用。

剪序默认连接`http://127.0.0.1:3900`。端口不同则在启动剪序前设置`ECOM_VOICESTUDIO_URL`；如独立服务启用认证，仅在本机设置`ECOM_VOICESTUDIO_API_KEY`。不把密钥写进方案、报错或客户导出。

## 页面操作

1. `/create`保存商品资料并由人确认事实与文稿。
2. 风格与声音→配音方式→VoiceStudio；点“检查本机服务”。
3. 选择语速，核对模型和本机配置后勾选确认，生成首句试听。
4. 实际听取；满意后合成整稿，沿用既有字幕对齐及人工听核。
5. 换声会保留历史，新的声音、分镜与成片仍须分别确认。

“已连接但未通过具体模型绑定”通常说明启动的是原生通用服务；请用上述固定模型启动器。状态超时可能是上游首次导入，稍后再检查；不要连续点击合成。合成失败不会自动重试或转用付费API。

## 实测与限制

工程稿7.85秒；首次成功请求37.907秒（包含首次水印权重下载），模型就绪后同稿2.549秒。上述两次均真实合成，不是缓存音频；非视觉识别性能对比，也不代表所有文稿时延。

中文ASR识别内容对应，有一个同音字差异。自然程度、品牌读音和长稿停顿仍须人听核。本轮客户标杆片继续使用已经认可的火山声音；测试音频不等于客户审核。

回退：页面改选火山或上传配音，或停止独立服务；已有声音、工程和审批不删除。模型/完整应用不随本轮源码改动自动分发。
