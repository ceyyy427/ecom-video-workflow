# 本机推理进程优化：开源调查与采用

本轮先查上游实现，再在同一台M2/8GB机器测量。没有下载新模型、替换权重、复制模型算法或修改vendor/；Ollama与llama.cpp继续使用本机已安装的同一二进制。完整许可证沿用 [已有MIT声明](recognition-runtime/)，本轮来源/二进制SHA见 决策（历史记录或本机文件，未随公开版分发） 与 程序指纹（历史记录或本机文件，未随公开版分发）。参考源码main提交不等于安装构建，实际行为用本机探针验证。

| 开源项目 | 采用/不采用 | 依据 |
| --- | --- | --- |
| [Ollama](https://github.com/ollama/ollama) | 同一CLI启动按任务隔离的loopback服务；原API、模型注册和结构化输出保持 | 支持Flash Attention和禁云环境项；进程专用环境不继承方舟/语音Key，不改用户全局服务 |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | 使用内置后端FA=on、host prompt cache=0；保留单slot的相同前缀复用 | 本机实际日志确认37/37 GPU层、Flash Attention enabled、prompt cache disabled；避免宿主缓存积累及每八次重载 |
| [MLX-VLM](https://github.com/Blaizzy/mlx-vlm) | 研究VisionFeatureCache/APC，未安装或切换 | 需要另一套转换权重、量化及依赖；当前先采用无需模型变化的方案，不把上游性能宣称当本机结果 |

## 本机实验与保留标准

直接llama-server两请求探针：batch128与512没有稳定差距，因此保持原128。最终采用相同Ollama API的独立进程探针：首个外观约20.49秒，第二外观约9.43秒，两次状态约11.49/10.64秒；这不是五段总验收。原始探针（历史记录或本机文件，未随公开版分发）。

不减少640抽帧、原1024图像最小tokens、3072上下文/输出上限；不改同款永久特征、主体4%门槛、有限crop预算、动作前后证据、重复区间和人工门禁。图像tokens不能为了提速随意缩小；[上游grounding说明](https://github.com/ggml-org/llama.cpp/issues/20418)也是保持原值的理由。

仅已验证4B模型digest、Darwin arm64、小内存范围及两个精确安装程序SHA启用；其他平台/程序版本/长上下文保留原服务。已有共享模型驻留时不卸载它、不另开大模型；本scope退回shared且不反复启动。私有服务没有通用URL/命令输入，仅127.0.0.1随机端口，禁云、单模型、单并发；任务结束/取消只终止自己创建的进程组。已有结果全部复用时不会启动模型进程。

本轮新增兼容仅限正式上一版固定源码指纹且有完整payload/帧SHA清单的旧结果；既有LEGACY精确指纹和重抽帧验证路径保持，未知版本不放行。强制重推不读取这些缓存。ECOM_VISION_PROCESS=shared可回到上一轮路径；不迁移数据库或改变旧成片审批。

源码差异属于进程管理、边界和配置适配，不是重写推理/缓存算法。完整五段真实时钟、选段/字幕/单镜及人工待审记录以本轮验收报告为准。
