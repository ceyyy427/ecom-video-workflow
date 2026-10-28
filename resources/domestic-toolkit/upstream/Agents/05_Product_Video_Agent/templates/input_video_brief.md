# 输入模板 · 视频生成简报

> **前置要求**：本模块**依赖 03 Listing Creative Agent 的输出**；有 04 的输出则效果更好（风格统一）。

---

## 0. 任务配置

```yaml
platform*: shopee              # shopee | mercadolivre | amazon | tiktokshop | shopify
target_market*: 巴西
durations*: [15, 30]           # 可选 [15] / [30] / [15, 30]
mode*: standard                # standard | variant
production_mode*: mixed        # ai_generated | real_shoot | mixed
prompt_language: en            # en | zh
```

---

## 1. 上游字段 · 03 的交付（阻塞项）

```yaml
# ── 从 03 输出的「交付给下游模块的字段」区块直接粘贴 ──

core_selling_point*: ""        # 视频钩子与主线

secondary_points*: []          # 卖点段内容

spec_table*: {}                # 参数段

forbidden_words*: []           # 字幕硬拦截

usage_scope_confirmed*: []     # 场景镜头范围

title_final*: ""               # 结尾 CTA 必须与之一致
```

## 2. 上游字段 · 04 的交付（可选但建议）

```yaml
# ── 从 04 输出的 handoff_to_video 区块粘贴 ──

visual_tone_confirmed: ""      # 全片风格统一
hero_visual: ""                # 首帧参考
key_visual_moments: []         # 分镜优先项
```

> 有了这两个字段，视频的画面风格会和 9 图保持一致。**跨模块视觉统一是这套流程的专业度体现**——图是一种风格、视频是另一种风格，买家会觉得是拼凑的。

---

## 3. 产品信息

```yaml
product_name*: ""
category*: ""
appearance:
  color: ""
  material: ""
  key_features: []
```

---

## 4. 钩子来源（强烈建议填）

> SOP 1.6：**评论是最接近真实买家需求的地方。** 钩子的最佳来源就在这里。

```yaml
hook_material:
  pain_points: []              # 来自差评抱怨，例：
    # - "买家抱怨充电宝在包里压到就断电"
  satisfaction_points: []      # 来自好评满意点，例：
    # - "买家反复提到屏幕显示剩余电量很实用"
  competitor_weakness: []      # 竞品短板，例：
    # - "竞品普遍 18W，本产品 45W"
```

---

## 5. 制作约束

```yaml
constraints:
  has_real_product: true       # 是否有实物可拍
  can_shoot_people: false      # 是否能拍真人出镜（false 则全部走不露脸或全 AI）
  available_props: []          # 可用的道具
  location_available: []       # 可用场地
  budget_level: ""             # low | medium | high（影响分镜复杂度）
```

---

## 6. 配音偏好（可选）

```yaml
voice_style:
  gender: ""                   # 男声 / 女声 / 不限
  tone: ""                     # 亲切 / 专业 / 活力 / 沉稳
  accent: "Português (Brasil)"
  reference: ""                # 想模仿的广告风格描述
```

---

## 7. mode = variant

```yaml
variant_angles: []             # 留空则由 Agent 自动分配
  # 例：["痛点切入", "结果切入"]
```

---

## 填写自检

- [ ] 六个阻塞字段已从 03 粘贴
- [ ] `title_final` 已填（否则 CTA 会与标题脱节）
- [ ] `production_mode` 与实际情况一致
- [ ] `can_shoot_people` 填了真实情况（false 会触发不露脸方案）
- [ ] 我理解：**真人镜头不会生成 AI Prompt**，改为拍摄指令（肖像合规）
- [ ] 我理解：**BGM / 音效素材需自行解决版权**
- [ ] 我理解：分镜时长是建议值，实际需按配音音频对齐
