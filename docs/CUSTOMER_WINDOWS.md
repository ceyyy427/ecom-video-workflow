# Windows 安装与验收

目标环境：Windows 11 x64、Python 3.11/3.12 x64、Node.js 22/24、uv、FFmpeg/ffprobe、中文字体（默认微软雅黑）。Windows ARM64 尚未承诺兼容；不要把 macOS 的 .venv 或 node_modules 复制过来。

1. 从各软件官方站点安装基础依赖，勾选 Python launcher 和 PATH。FFmpeg 完整解压后把 bin 加入用户 PATH；重开启动窗口。首次准备依赖仍需要网络。
2. 解压整个可信交付包到本机 NTFS 目录（例如文档中的“剪序工作台”）。不要在ZIP内直接运行，也不要放OneDrive同步/共享盘或需要管理员权限的目录。
3. 双击 `启动剪序.cmd`。启动器自动检查并安装项目依赖，完成后打开 `/setup`。不要求管理员，也不修改 PowerShell 执行策略；窗口是服务生命周期，保持打开。
4. `/setup` 选择本机 Ollama 视觉模型，点击ASR安装/校验，按需要输入火山语音Key。模型缺失也可先人工选段，配音可上传成品。Windows网页保存的Key由当前登录用户DPAPI加密；不接受macOS明文配置直接迁移，换电脑/用户需重新配置。环境变量仍优先。
5. 创建商品并上传资料和素材，按页面完成事实、文稿、风格、逐句听核和成片审核。自动识别不等于事实确认；平台写入和自动Agent执行默认关闭。
6. “数据与版本”页创建/校验/下载备份，恢复到独立目录；升级先核对SHA和代码来源，再勾选确认。打开新目录双击 `启动恢复副本.cmd` / `启动新版本.cmd`，默认8770；原数据保留。关闭候选后可回原目录启动。

## 常见错误

- `py`不存在：从 python.org 安装 Python 3.11/3.12 x64，包含 launcher；重新双击。不要使用仅指向微软商店的别名。
- uv/node/npm/ffmpeg 缺失：按安装提示补齐用户PATH并重开窗口。npm通过Node自带JS入口执行，不需要放宽脚本策略。
- PowerShell禁止脚本：正常启动不依赖PowerShell。可请IT审核验收/本地语音脚本；本程序不会绕过系统策略。
- 模型安装失败：检查磁盘/网络和页面错误；禁止跳过模型摘要校验。Windows原生轮子如不适用会明确失败，不会回退云推理。
- 中文乱码：使用本包双击入口（已启用UTF-8）；不要用旧版源码或自行复制非UTF-8配置。
- 45000030：语音服务资源授权问题，按配音指南在同项目开通语音合成2.0；Key不等于已验证调用权限。
- OCR：当前自动画面文字OCR仅macOS Vision可用；Windows综合审核须人工核对画面文字，不能把“未检测”视为合规通过。

## 本机技术验收

双击 `验收剪序.cmd`（先完成依赖、ASR和本机视觉模型配置）。会在文档下创建随机新目录，使用原创合成圆罐素材与Windows本机中文语音，跑实际模型、渲染、备份恢复。测试确认有明确标记，最终停在待人工审片，不签收、不云调用、不投放。

没有经典zh-CN语音时，先安装系统中文语音包；高级方式可传入与生成的 `script.txt` 完全相同的成品配音：`.venv\Scripts\python.exe -X utf8 scripts\customer_smoke.py --workspace <新目录> --simulate-confirmations --voice-file <WAV文件>`。预录异稿会停止，不能假装对齐成功。

开发仓库提供 `.github/workflows/windows-customer.yml` 的手动Windows原生契约测试入口；运行后下载证据。它不代替有本机模型、中文语音和人工审片的Windows完整验收。

实现依据：[Windows LockFileEx共享/排他锁](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)、[当前用户DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。锁随进程句柄关闭释放，凭据未使用全机可解密模式。锁文件中存在x64版sherpa-onnx/core轮子的摘要记录，但不等于已在Windows加载成功；原生库缺少运行时时需安装微软官方VC++ x64运行库，不能下载不明DLL。
