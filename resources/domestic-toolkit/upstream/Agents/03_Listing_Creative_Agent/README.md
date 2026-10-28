# 03 · Listing Creative Agent

**商品内容生成智能体** · 从一堆散乱关键词，到一套可直接上架的 Listing。

> **Skill 化（v0.4）**：新增发布前合规校验脚本与 Agent 入口
> [`SKILL.md`](SKILL.md)。**字符数是 `len()` 实测值**（PT-BR 的 `á` 是 2 字节，
> 按字节算会误判超限）：
>
> ```bash
> # 标题合规（超限/禁用词/促销词/堆砌/核心词覆盖）
> python scripts/title_lint.py "标题" --platform shopee --forbidden "iPhone,Samsung"
> # 参数一致性（文案里每个数字必须溯源到 spec_table）
> python scripts/spec_consistency.py --spec examples/spec_table.csv --text 详情.md
> ```
>
> 规则卡见 [`references/platform-title-rules.md`](references/platform-title-rules.md)。

---

## 一、它解决什么问题

SOP 3.3 说 Listing 的目标是"让商品页面具备点击和转化能力"。但真实场景里，运营卡在三个地方：

| 痛点 | 表现 | 本模块怎么解 |
|---|---|---|
| **关键词不会分类** | 三榜扒回来 90 个词，全塞进标题，堆词反而降权 | 强制七类分词，风险词单独隔离 |
| **标题没有结构** | 想到什么写什么，主关键词埋在中间 | 固定五段公式，前 30 字符强制放主词 |
| **详情页写不出卖点** | 抄竞品、写形容词、参数漏项 | 7 段结构 + 卖点真实化映射 + 参数一致性校验 |

**产出物**：2–3 个备选标题、完整详情页、卖点清单、参数表、关键词分类表、合规扫描结果。

---

## 二、覆盖的 SOP 章节

| SOP | 内容 | 落在哪个 Prompt |
|---|---|---|
| **1.8** | 关键词表：三榜提取 → 高频词 → 七类分词 → 组合标题 | `01_keyword_to_title.md` |
| **3.3** | Listing 打造：标题注意事项 + 详情页结构 | `01_keyword_to_title.md` / `02_description_builder.md` |
| **2.3** | 新店冷启动：多店铺同款必须差异化 | `01_keyword_to_title.md`（变体模式） |
| **3.4** | 单品多链接启动：多套标题/主图/详情页测试 | `01_keyword_to_title.md`（变体模式） |
| **3.6** | 广告"有曝光没点击" → 回改标题 | `01_keyword_to_title.md`（迭代模式） |
| **全章** | 合规红线 | `03_compliance_guard.md` |

---

## 三、工作流

```text
┌─────────────────────────────────────────────────────────┐
│ 输入：input_product_brief.md（产品资料 + 关键词三榜）      │
└────────────────────────┬────────────────────────────────┘
                         ▼
        ┌────────────────────────────────┐
        │ 00_system.md                   │  角色 + 平台规则 + 合规守卫
        └────────────────┬───────────────┘
                         ▼
        ┌────────────────────────────────┐
        │ 01_keyword_to_title.md         │  Step 1  关键词七类分词
        │                                │  Step 2  标题生成（2–3 个备选）
        └────────────────┬───────────────┘
                         ▼
        ┌────────────────────────────────┐
        │ 02_description_builder.md      │  Step 3  详情页 7 段
        │                                │  Step 4  卖点清单 + 参数表
        └────────────────┬───────────────┘
                         ▼
        ┌────────────────────────────────┐
        │ 03_compliance_guard.md         │  Step 5  合规扫描 → 硬拦截
        └────────────────┬───────────────┘
                         ▼
        输出：output_listing_pack.md
              ├── core_selling_point     ──► 交付给 04 / 05
              ├── secondary_points[]
              ├── spec_table
              ├── keyword_classified
              └── forbidden_words[]
```

> **Step 5 不是可选项。** 合规扫描的输出（`forbidden_words[]`）是 04 和 05 的硬拦截清单，跳过这一步等于把风险传给下游。

---

## 四、使用方法

### 最小可用路径（3 步）

```text
1. 复制 templates/input_product_brief.md，填产品资料 + 关键词三榜
2. 依次执行：00_system → 01_keyword_to_title → 02_description_builder → 03_compliance_guard
3. 用 docs/04_Result_Checklist.md 的 B 段逐条自检
```

### 三种工作模式

同一个 Agent 支持三种模式，通过输入模板里的 `mode` 字段切换：

| 模式 | 用途 | 差异 |
|---|---|---|
| `single` | 常规单链接上架 | 输出 1 套完整方案 + 2–3 个标题备选 |
| `variant` | **多链接 A/B 测试**（SOP 3.4） | 输出 2–4 套**差异化**方案，标题/卖点/场景各走一个方向 |
| `iterate` | **广告跑不动时的回改**（SOP 3.6） | 输入现有方案 + 问题症状，只改指定的部分，其余不动 |

### 平台切换

`platform` 字段决定字符限制和结构：

| platform | 标题上限 | 详情页结构 |
|---|---|---|
| `shopee` | 120 字符（前 30 权重最高） | 7 段完整结构 |
| `mercadolivre` | **60 字符** | Características principais + Ficha Técnica |
| `amazon` | 200 字符 | 五点描述 + A+ 结构 |
| `tiktokshop` | 按站点 | 短描述 + 卖点前置 |
| `shopify` | 建议 70 | 长描述 + SEO 段落 |

---

## 五、Prompt 文件

| 文件 | 作用 |
|---|---|
| [`prompts/00_system.md`](./prompts/00_system.md) | 系统 Prompt：角色 + 平台规则 + 语言规则 + 合规守卫（三个任务共用） |
| [`prompts/01_keyword_to_title.md`](./prompts/01_keyword_to_title.md) | 任务 Prompt：关键词七类分词 → 高频词提取 → 标题生成 |
| [`prompts/02_description_builder.md`](./prompts/02_description_builder.md) | 任务 Prompt：详情页 7 段 + 卖点清单 + 参数表 |
| [`prompts/03_compliance_guard.md`](./prompts/03_compliance_guard.md) | 任务 Prompt：独立合规扫描（也可单独对已有 Listing 复核） |

---

## 六、模板与案例

| 文件 | 说明 |
|---|---|
| [`templates/input_product_brief.md`](./templates/input_product_brief.md) | 标准输入：产品资料 + 关键词三榜 + 合规声明 |
| [`templates/output_listing_pack.md`](./templates/output_listing_pack.md) | 标准输出：完整素材包结构 |
| [`examples/powerbank_20000mah.md`](./examples/powerbank_20000mah.md) | 真实案例：Carregador Portátil 20000mAh 45W（Shopee 巴西站） |

---

## 七、已知限制

| 限制 | 说明 |
|---|---|
| **不产生关键词** | 关键词必须由你从虾多拉/平台搜索词工具导出。Agent 只做分类和组合，**不凭空编词** |
| **不做选品决策** | 这是 01 Market Research 的职责 |
| **不做定价** | 这是 02 Product Strategy 的职责 |
| **不校验真实参数** | Agent 只能保证"输出与输入一致"，无法判断输入本身是否真实。**参数真实性由你负责** |
| **平台规则可能滞后** | 仓库里的字数限制是编写时的公开规则，**发布前必须到卖家中心复核** |
| **母语质量有上限** | PT-BR 输出质量取决于模型；高价值 listing 建议让母语者过一遍 |

---

## 八、一个真实例子

见 [`examples/powerbank_20000mah.md`](./examples/powerbank_20000mah.md)。摘要：

```text
输入：20000mAh 45W 充电宝，巴西站，关键词三榜共 84 个词
  ↓
关键词分类：核心词 3 个 / 参数词 11 个 / 人群词 4 个 /
            功能词 8 个 / 场景词 6 个 / 配件词 5 个 / 风险词 6 个（隔离）
  ↓
标题（Shopee BR，115/120 字符，`title_lint.py` 实测）：
  Carregador Portátil 20000mAh 45W Turbo Carga Rápida 3 Saídas
  com Display Digital para Celular iPhone Android Viagem
  ↓
差评归因发现"以为含数据线"是高频误解
  → 详情页第 6 段加入" cabo não incluso "
  ↓
合规扫描：命中 2 条（绝对化用语 1、未授权品牌词 1），已改写
```

---

**返回**：[Agents 索引](../README.md) · **文档**：[SOP 拆解](../../docs/00_Architecture_SOP_to_Agent.md) · [Prompt 规范](../../docs/01_Prompt_Design_Guide.md) · [合规红线](../../docs/03_Compliance_Guard.md)
