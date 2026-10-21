# MLX Phase 1–2 上游采用记录

本轮范围：隔离安装、完整视觉特征缓存验证、同五段素材交错强制推理。正式后端/UI/客户数据不参与试验；没有完整速度与质量证据不得切默认。

最终采用结论：官方库仅用于隔离实验，缓存完整数值验证通过；候选模型/版本组合不切生产默认。A1/B1/B2/A2为20.66/29.00/23.46/22.39分钟，两B三段正样本同款证据不足、4个实际选段资格均丢失。失败单例关闭缓存亦复现，不能简单归咎于热缓存或认定普遍根因。实测、限制与回滚（历史记录或本机文件，未随公开版分发）。

## 固定来源与许可

- [MLX-VLM](https://github.com/Blaizzy/mlx-vlm)：PyPI `0.7.9`，MIT；官方 wheel `mlx_vlm-0.7.9-py3-none-any.whl`，3,345,948 字节，SHA-256 `bc6e4575369fb2470a8b84c97729a5da8b141ecf9625f9a3a028d41b9c8d3054`。本轮完整 SHA 和 ZIP CRC 校验已通过，见 wheel 证据（历史记录或本机文件，未随公开版分发）。
- [候选模型](https://huggingface.co/mlx-community/Qwen3-VL-4B-Instruct-4bit/tree/2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b)：固定修订 `2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b`，模型卡 Apache-2.0；权重 3,093,767,283 字节，预期 SHA-256 `90eeb02604181dbcccd0a30a1f550a4a8928ca7dcbee4aee1449239306cfdfca`。配置/分词器等 14 文件已逐一对照固定树 Git blob/LFS 哈希；权重必须另行完整校验后才加载。
- [MLX](https://github.com/ml-explore/mlx/releases/tag/v0.32.4)：`0.32.4`，MIT；本机 macOS 26 / arm64 对应官方 `mlx-metal` wheel。依赖在仓库外 Python 3.11 环境安装，73 个包的版本及官方 PyPI 哈希已锁定，不加入项目运行依赖。
- 隔离安装已完成：73 个 wheel 均核对官方 PyPI 文件 SHA-256 并通过 ZIP CRC，安装后逐个核对 RECORD 中的文件哈希；`uv pip check` 与真实 M2 Metal 矩阵运算通过。见 完整 wheel 清单（历史记录或本机文件，未随公开版分发） 和 运行环境证据（历史记录或本机文件，未随公开版分发）。MLX 报告本机推荐 GPU 工作集为 5,726,633,984 字节；这不是本轮模型峰值，峰值仍须实测。
- 本机 Apple M2 / 8 GiB；权重约 2.88 GiB 不代表峰值内存。分别记录进程树 RSS、MLX 设备分配峰值与系统交换量，不将它们相加当真实物理总占用。

## 采用与不采用

| 上游能力 | 本轮决策与原因 |
|---|---|
| 官方 Hub/Xet 下载和 curl HTTP Range | 先用官方 Hub；连接中断后采用有界分块续传，保留字节及最后完整 SHA。部分下载不得加载或分发。 |
| 下载链路替代 | 采用 [curl 原生连接池](https://curl.se/docs/manpage.html) 复用连接，HTTP/1.1、有界并发、校对 Content-Range 并保留有效断点；包文件临时经 [TUNA](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/) 传输，最终信任依据仍为官方 PyPI SHA，不修改系统镜像配置。HF-Mirror 测试仍跳回原官方 CDN，无收益而未采用。 |
| `load`、图像处理器、`generate` | 隔离复用官方实现，使用相同源图、提示词、schema 和输出预算；实际记录 grid，至少保持原 1024 图像 tokens 下限。 |
| `VisionFeatureCache` | 不将“传入空缓存”算作命中：固定版 Qwen3-VL 没有生成入口所检测的 `encode_images/encode_image`。 |
| `cached_image_features` | 不直接采用：该条件分支令 `deepstack_visual_embeds=None`，与冷路径不同。 |
| 完整视觉塔返回值 | 仅实验包装原视觉编码器，缓存主特征和全部 DeepStack；处理后像素/grid/模型/处理器参与键，最多 256 MiB。先验证冷/热与批量/逐图数值关系。 |
| 物理缓存计量 | 采用 [get_array_buffer_size](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.get_array_buffer_size.html)，评估后的数组按实际底层 buffer 计量，防止视图 `nbytes` 低估。 |
| JSON 输出 | 复用官方 [structured.py](https://github.com/Blaizzy/mlx-vlm/blob/9527f2da3b42ffb4a9613b2a5c38935c27b81039/mlx_vlm/structured.py) 与 MIT `llguidance`，每请求新约束处理器；不自动改事实或放宽 schema。 |
| MLX 专用预处理/预填充 | 实装发现官方 torch-free 处理器使用 `min_pixels/max_pixels`，不是 Transformers 通用 `size` 字段；仅在隔离适配中使用其实际接口，逐请求核对实际图像 tokens≥1024。先保留128预填充试验，再评估官方 `DEFAULT_PREFILL_STEP_SIZE=2048`；这是推理分块参数，不减少图像、抽样或输出预算，仍需完整质量验收。 |
| APC、量化 KV、降低抽样/分辨率 | 本轮不引入，避免归因混杂、兼容风险或检查标准下降。 |

## 已核对的问题

- [DeepStack 旧问题 #1020](https://github.com/Blaizzy/mlx-vlm/issues/1020) 与本轮条件缓存分支不同，不能把旧修复当成本轮缓存等价的证明。
- [结构化输出处理器状态 #1574](https://github.com/Blaizzy/mlx-vlm/issues/1574)、[#1555](https://github.com/Blaizzy/mlx-vlm/issues/1555)：本轮单请求顺序执行、每次新建约束器，不做批处理或 APC。
- [thinking 与 JSON #1294](https://github.com/Blaizzy/mlx-vlm/issues/1294)：关闭 thinking 并验证实际输出，不以问题已关闭代替实测。
- 真实重推出现 `same + permanent_features=[]`，原同款门禁正确拒绝。检索 [llguidance 官方格式说明](https://github.com/guidance-ai/llguidance/blob/main/docs/toolcalls.md)：约束语法不能代替清晰的格式上下文。输出格式/提示适配是否导致本例空数组，目前仅为待验证假设；不能认定为 MLX 框架、量化或缓存的确定根因，更不能补填特征让验收通过。为保留同输入交错对照，本轮冻结候选后不临时改提示词。

以上“已校验”仅指明确列出的文件。实际安装、特征和交错识别验收状态以本轮执行报告为准；没有 MLX 实测时不得宣称其更快或质量已通过。
