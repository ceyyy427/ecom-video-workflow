# 05 · Product Video Agent

**商品短视频生成智能体** · 从一句卖点，到一条能直接录的分镜脚本。

> **v0.4 Skill 化**：新增 [`SKILL.md`](./SKILL.md)（Agent 入口）+
> [`references/video-specs.md`](./references/video-specs.md)（平台视频规范卡）+
> [`scripts/video_timing.py`](./scripts/video_timing.py)（**时长与字幕的确定性校验**：
> 词数→时长换算、逐句时间轴、字幕行长、钩子检查、总时长 vs 15s/30s 目标 ±15% 容差）。
> 时长校验实测：65 词 ÷ 2.5 词/秒 = 26.0s，与案例文档记录完全一致。

---

## 一、它解决什么问题

视频是三个创意模块里**门槛最高、最容易半途而废**的一环。

| 痛点 | 表现 | 本模块怎么解 |
|---|---|---|
| **不知道前 3 秒放什么** | 开头是"大家好，今天给大家介绍…"，观众已划走 | 强制钩子规则：前 3 秒必须是产品/结果/痛点，不是自我介绍 |
| **写不出分镜** | 只有一段文字描述，到拍摄/剪辑时无从下手 | 输出结构化分镜表：镜号 / 时长 / 画面 / 运镜 / 文案 / 音效 |
| **AI 视频 Prompt 没效果** | 丢一句话给视频模型，出来的画面不能用 | 按镜头输出结构化 Prompt：主体 + 动作 + 镜头运动 + 光线 + 风格 |
| **配音文案像书面语** | 念出来很生硬，TTS 效果差 | 强制口语化改写 + 预估朗读时长 |

**产出物**：15s / 30s 双版本脚本 + 分镜表 + 逐镜头 AI 视频 Prompt + 配音稿 + 字幕。

---

## 二、覆盖的 SOP 章节

SOP 里没有独立的"视频"章节——**这是本仓库的延伸模块**，SOP 只提供了素材侧基础：

| SOP 来源 | 提取的内容 | 怎么用 |
|---|---|---|
| **3.3 详情页内容框架** | 7 段结构（欢迎语 / 卖点 / 场景 / 参数 / 售后 / 注意 / 关键词） | 转成视频叙事骨架：钩子 → 卖点 → 场景 → 参数 → 信任 → CTA |
| **3.3 标题写法** | 核心词 + 人群 + 参数 + 功能 + 场景 | 视频结尾 CTA 与标题保持一致 |
| **1.6 评论分析** | 买家真正关心什么 | 决定视频里优先讲哪个卖点 |
| **2.3 差异化** | 多店铺同款需差异化 | `variant` 模式下输出多套不同切入角度的脚本 |

> **诚实说明**：视频模块的方法论有较大比例来自通用短视频实践，而非这份 SOP。SOP 提供的是**素材和约束**（卖点、参数、场景范围、禁用词），本模块负责把它组织成视频语言。

---

## 三、工作流

```text
输入：03 Listing Creative 的输出 + （可选）04 Product Image 的 hero_visual
        ▲
        └── 【阻塞规则】core_selling_point 或 forbidden_words 为空 → 拒绝执行
                         ▼
        ┌────────────────────────────────┐
        │ 00_system.md                   │  角色 + 平台视频规范 + 字幕合规守卫
        └──────────────┬─────────────────┘
                       ▼
        ┌────────────────────────────────┐
        │ 01_script_and_storyboard.md    │  Step 1  15s / 30s 脚本
        │                                │  Step 2  分镜表
        └──────────────┬─────────────────┘
                       ▼
        ┌────────────────────────────────┐
        │ 02_ai_video_and_voice.md       │  Step 3  逐镜头 AI 视频 Prompt
        │                                │  Step 4  配音稿 + 字幕 + 时长核对
        └──────────────┬─────────────────┘
                       ▼
        输出：output_video_pack.yaml  →  交给 VideoGen / 即梦 / Runway / 可灵 / 剪映
```

---

## 四、双版本策略

| 版本 | 用途 | 结构 |
|---|---|---|
| **15s** | 商品主图位视频、信息流广告、TikTok 首屏 | 钩子(0–3s) → 核心卖点(3–9s) → 场景(9–13s) → CTA(13–15s) |
| **30s** | 详情页视频、商品页嵌入 | 钩子(0–3s) → 卖点 1(3–9s) → 卖点 2(9–16s) → 场景(16–23s) → 参数/信任(23–28s) → CTA(28–30s) |

**为什么必须做 15s 版**：平台主图位视频和 TikTok 首屏对流量的拦截都发生在**前 3 秒到前 15 秒**。30s 版做得再好，前 15s 不成立就是废片——15s 版本质上是在逼你先把最有效的信息压缩出来。

---

## 五、钩子设计（前 3 秒）

SOP 没有直接讲视频钩子，但 SOP 1.6 讲了一件事：**评论是最接近真实买家需求的地方**。钩子的最佳来源就是这个：

| 钩子类型 | 来源 | 示例（巴西 / 充电宝） |
|---|---|---|
| **痛点直击** | 差评里的高频抱怨 | `Seu celular acaba antes do fim do dia?` |
| **结果前置** | 好评里的高频满意点 | `Carrega o celular 4 vezes sem tomada.` |
| **反常识** | 参数里的意外点 | `20.000 mAh e ainda cabe no bolso.` |
| **对比冲击** | 竞品短板 | `45W. Não 18W.` |
| **场景代入** | `usage_scope` 主场景 | `Domingo inteiro fora de casa. Sem tomada.` |

❌ **禁止**：`Olá pessoal, bem-vindos ao meu canal`、`Hoje vou apresentar para vocês`、任何自我介绍。

---

## 六、Prompt 文件

| 文件 | 作用 |
|---|---|
| [`prompts/00_system.md`](./prompts/00_system.md) | 系统 Prompt：角色 + 平台视频规范 + 字幕/画面合规守卫 |
| [`prompts/01_script_and_storyboard.md`](./prompts/01_script_and_storyboard.md) | 任务 Prompt：脚本 + 分镜表 |
| [`prompts/02_ai_video_and_voice.md`](./prompts/02_ai_video_and_voice.md) | 任务 Prompt：逐镜头 AI 视频 Prompt + 配音稿 + 字幕 |

## 七、模板与案例

| 文件 | 说明 |
|---|---|
| [`templates/input_video_brief.md`](./templates/input_video_brief.md) | 标准输入 |
| [`templates/output_video_pack.yaml`](./templates/output_video_pack.yaml) | 标准输出 |
| [`examples/air_fryer.md`](./examples/air_fryer.md) | 真实案例：空气炸锅 15s + 30s 双版本 |

---

## 八、已知限制

| 限制 | 说明 |
|---|---|
| **不渲染视频** | 只产出脚本、分镜和 Prompt，实际生成用视频工具 |
| **SOP 无直接依据** | 本模块方法论部分来自通用短视频实践，已在上方注明 |
| **音画同步需人工** | 分镜时长是建议值，实际需按配音音频对齐 |
| **BGM 版权需自备** | 模块只给"需要什么情绪的音乐"，不提供音乐素材 |
| **不支持真人出镜方案** | 涉及真人拍摄的镜头只给拍摄指令，不生成真人视频 Prompt（肖像合规风险） |
| **无法判断成片质量** | 渲染后的品控需人工执行 D 段清单 |

---

**返回**：[Agents 索引](../README.md) · **上游**：[03 Listing Creative](../03_Listing_Creative_Agent/) · [04 Product Image](../04_Product_Image_Agent/) · **文档**：[平台字段规范](../../docs/02_Platform_Output_Spec.md) · [合规红线](../../docs/03_Compliance_Guard.md)
