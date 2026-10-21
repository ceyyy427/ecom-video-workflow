# 首次识别提速：采用的开源实现

本轮先读上游再定位，本机实际使用 Ollama 0.35.0、其自带 llama-server 与原 Qwen3-VL-4B Q4_K_M；没有另写推理引擎、下载替代权重或修改 vendor/。来源固定信息见 provenance.json（历史记录或本机文件，未随公开版分发），三份 MIT 声明保存在同目录。

| 项目 | 读到的能力/问题 | 采用情况 |
| --- | --- | --- |
| [Ollama](https://github.com/ollama/ollama) | GPU层放置、keep_alive 生命周期、模型调度 | 直接使用现有本机 API；已验证小上下文的指定4B模型可请求全部层驻留；明确OOM仅一次退回原放置，仍计入Agent调用预算 |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | 连续请求可复用相同图片/文字前缀；宿主提示缓存默认8192MiB | 通过自带后端使用。四帧各自比较后按时序逐帧核对状态，让同一参照前缀连续；未合并判断，未复用近似图。小内存Mac每八次请求用原生生命周期释放一次模型及宿主缓存 |
| [MLX-VLM](https://github.com/Blaizzy/mlx-vlm) | Apple Silicon推理、VisionFeatureCache、前缀缓存与连续批处理 | 已研究，未安装。切换需另换转换权重并验证JSON约束与输出质量；本轮先修现有后端的放置/缓存增长，不扩大依赖或悄悄换模型 |

## 调查证据与适配边界

本机日志事实：原放置只将32/37层放到GPU；明确请求后为37/37。单纯提高num_batch并无稳定收益，因此保留原128/512、原640像素抽帧、原3072/8192上下文及输出上限，不做激进参数缩减。

另一本机事实：长序列宿主缓存从0累计到约1.8GiB，随后请求变慢。这与 [Ollama #18264](https://github.com/ollama/ollama/issues/18264) 和 [#18099](https://github.com/ollama/ollama/issues/18099) 所述机制吻合；“它造成全部历史慢耗时”是推测，本轮不作此结论。缓存限额参数定义可查 [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)。

本轮采用 [Ollama原生keep_alive](https://docs.ollama.com/api/chat)，不更改用户全局Ollama环境：已验证4B digest、Darwin arm64、内存至少8GB、小上下文才用驻留配置；8–16GB且位于识别作用域时每八个请求释放一次，任务结束时也释放不足八次的尾部状态，避免连续短任务累积。释放只丢掉运行缓存，下一次仍用原模型、原图片和完整问题重新判断。不是缩短上下文，也不是清除客户素材或识别历史。

每四帧的appearance仍是四次独立请求；随后依原顺序检查motion、至多两次目标局部复核和动作前后证据。不确定不放行；明确异款仍提前终止。预取结果绑定参照与该帧的实际SHA，变化则停止发布。强制重推仍跳过完整结果及函数缓存；后端复用数学前缀不等于读取旧判断。

`ECOM_VISION_ACCELERATION=off`可回退原放置、原调度顺序和原keep_alive，不需要迁移数据库。其他系统和模型保持原GPU放置；前缀友好的请求排序仍可使用，逐帧标准一致。未知/新模型digest不会自动套用本机验证过的驻留参数。

本轮新增代码是业务调度、参数边界和错误适配；没有拷贝上述项目的模型/缓存算法。上游main参考提交不等于本机发行构建，运行日志、请求选项、实际模型digest和同素材实测才是本次采用是否生效的依据。
