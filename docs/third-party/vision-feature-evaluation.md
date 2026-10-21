# 视觉特征与本机推理缓存评估 · 2026-10-20

本轮先核对上游，再做本机探针和五段强制推理。当前界面、模型权重、检查算法与人工门禁保持；实验不接触正式客户数据，不修改vendor/。

## MLX-VLM：优先调查，尚未进入模型实测

- 来源：[MLX-VLM](https://github.com/Blaizzy/mlx-vlm)，固定审阅提交 `9527f2da3b42ffb4a9613b2a5c38935c27b81039`，MIT；仓库仍维护、未归档。PyPI候选为0.7.9，两者不能当成已验证的同一安装构建。许可证与来源（历史记录或本机文件，未随公开版分发）。
- 候选模型：[mlx-community/Qwen3-VL-4B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit/tree/2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b)，修订 `2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b`，模型卡标注Apache-2.0。权重3,093,767,283字节（约2.88GiB），与原Q4_K_M GGUF量化不同，需要独立质量验证。
- 本机M2/8GB，还需容纳视觉编码器、图像张量、KV、DeepStack、应用与桌面。不能由权重大小推断实际峰值一定可用。隔离Python3.11环境不污染项目；0.7.9依赖包含mlx≥0.32.4、transformers≥5.14.0及音频/数据/服务依赖，未直接加入产品依赖。
- 下载实测：官方权重链接180秒超时，只取得33,900,922字节；独立包解析超过5分钟未完成后停止自有进程。两个不完整下载均标为`.partial`，不加载、不分发。没有MLX本机推理、峰值内存、速度或准确率结果，不能据此宣称MLX慢或不适用。完整预检（历史记录或本机文件，未随公开版分发）。

## 缓存调用链的实际限制

[VisionFeatureCache](https://github.com/Blaizzy/mlx-vlm/blob/9527f2da3b42ffb4a9613b2a5c38935c27b81039/mlx_vlm/vision_cache.py)提供LRU，处理后像素和grid参与键。[生成入口](https://github.com/Blaizzy/mlx-vlm/blob/9527f2da3b42ffb4a9613b2a5c38935c27b81039/mlx_vlm/generate/dispatch.py)在模型实现`encode_images/encode_image`时填充；固定版本的[Qwen3-VL模型](https://github.com/Blaizzy/mlx-vlm/blob/9527f2da3b42ffb4a9613b2a5c38935c27b81039/mlx_vlm/models/qwen3_vl/qwen3_vl.py)未定义这些方法。因此，仅传入空缓存不能证明本模型会复用视觉编码。

若手工填充`cached_image_features`，该模型分支会将`deepstack_visual_embeds`置空，冷路径则保留多层视觉特征；这是条件性质量风险，尚未复现为自动缓存故障。不能为追求命中率直接套用，也不能只缓存最后一层特征。

该模型预处理文件的最短像素配置为65,536，不能直接当作原后端1024最小图像tokens的等价配置；需记录并匹配实际grid/token数，不能用默认降采样制造速度优势。

多图请求的组合键还需区分图片顺序、尺寸与grid；“参照图+每张新帧”整组不同，并不等于可逐图复用参照编码。后续须测完整DeepStack保留、逐图缓存键、内存字节上限及同图换文稿的结果，区分视觉编码命中与LLM实际新推理。APC是另一层前缀缓存，不等于复用业务判断。原模型与转换模型的缓存不能共用身份。

## 当前后端的可验证试验

继续使用已验证的Ollama0.35.0及内置llama.cpp，许可证沿用[MIT声明](recognition-runtime/)。不新增推理依赖。

参照上游[宿主提示词缓存](https://github.com/ggml-org/llama.cpp/pull/16391)，增加仅本机受信任环境可选的固定256MiB实验值；未设或值无效仍为0，拒绝上游8192MiB默认和无限值。只在既有程序SHA/4B/小Mac/短上下文的私有进程路径生效；不改用户全局服务。取消、预算、进程所有权及原共享服务回退保持。

同输入六次探针：原0MiB共76.53秒，256MiB共78.28秒，结构化结果全等；小样本没有收益。同五段完整强制推理实际1228.8776秒，对历史1262.3579秒减少2.65%；72次新推理、0业务缓存，输入/响应/区间/动作和最终选段保持。未本轮重测完整0MiB基线；没有稳定加速依据，不切换默认。详见本轮报告，不能把局部探针或旧缓存当完整首次识别。

未重做批大小128/512试验：上一轮同权重探针已经没有稳定差距；本轮保持128。未使用`cache-reuse`任意KV搬移：[上游多模态实现](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-context.cpp)会禁用该模式。未通过缩小模型、图像tokens、抽样或输出预算换速度。

验收结果、局限及回滚见 本轮报告（历史记录或本机文件，未随公开版分发）；质量保持不等于速度收益已证实，默认未切换。
