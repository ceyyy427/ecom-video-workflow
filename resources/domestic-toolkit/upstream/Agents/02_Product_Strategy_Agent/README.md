# 02 · Product Strategy Agent

**产品策略智能体** · 把市场分析的结论，翻译成**可直接交给采购、上架、作图、定价用的产品规格单**。

> **Skill 化（v0.4）**：新增定价算术脚本与 Agent 入口 [`SKILL.md`](SKILL.md)。
>
> ```bash
> # 单 SKU：净利率 / 盈亏平衡价 / 目标价 / 优惠券余量
> python scripts/sku_pricing.py calc --cost 935 --price 2199 --commission 14 --ad 5
> # 多 SKU 矩阵：净利率表 + 价格阶梯 + 结构提醒
> python scripts/sku_pricing.py matrix --file examples/sample-skus.csv --target-margin 32
> ```
>
> 公式与税费口径见 [`references/pricing-rules.md`](references/pricing-rules.md)。**含巴西税费项。**

---

## 一、它解决什么问题

SOP 1.7 说这一步的定位：

> 这一步是市场分析的最终输出，**不是单纯总结**，而是要形成可以指导采购、上架、作图、定价和推广的**产品需求**。

这正是执行时最容易掉链子的地方：市场分析做得很细，最后落到"要做什么产品"时又变成一句模糊的话。

| 痛点 | 表现 | 本模块怎么解 |
|---|---|---|
| **结论不能落地** | "建议做 500W 款" —— 采购不知道要什么规格 | 输出六项完整需求：类型/配置/价格/SKU/卖点/风险 |
| **定价拍脑袋** | 看着竞品价格减一点 | 用定价公式反算 + 逐 SKU 验算毛利 + 算盈亏线 |
| **SKU 乱加** | 想到什么加什么 | 按「引流/主推/高配/套装」四角色设计，每档有明确职责 |
| **卖点没收敛** | 十个卖点并列，等于没有卖点 | 从市场分析的 `opportunity_config` 收敛成一句主卖点 |

**产出物**：《产品需求表》—— 推荐类型 / 核心配置 / SKU 结构 / 价格区间 / 主推卖点 / 风险规避 / 后续执行需求。

---

## 二、覆盖的 SOP 章节

| SOP | 内容 | 落在哪 |
|---|---|---|
| **1.7** | 主推产品确认：产品类型 / 核心配置 / 目标价格 / 核心卖点 / 风险规避 / 后续执行需求 | `prompts/01_product_decision.md` |
| **1.9** | 定价：大件 30–35%、小件 25–30%，前期可略低养权重 | `prompts/02_pricing_and_sku.md` |
| **3.1** | 单品上架前准备（8 个必答问题） | `prompts/01_product_decision.md` |
| **3.2** | 定价与 SKU 策略（四角色结构） | `prompts/02_pricing_and_sku.md` |

---

## 三、工作流

```text
输入：01 Market Research 的输出（target_price_range / recommended_config /
      opportunity_config / cost_structure / competitor_weakness）
                         ▼
        ┌────────────────────────────────┐
        │ prompts/00_system.md           │  角色 + 定价规则 + 合规守卫
        └──────────────┬─────────────────┘
                       ▼
        ┌────────────────────────────────┐
        │ 01_product_decision.md         │  Step 1  产品类型定位
        │                                │  Step 2  核心配置确认
        │                                │  Step 3  主推卖点收敛（一句）
        │                                │  Step 4  风险规避清单
        │                                │  Step 5  上架前 8 问自检
        └──────────────┬─────────────────┘
                       ▼
        ┌────────────────────────────────┐
        │ 02_pricing_and_sku.md          │  Step 6  定价模型 + 逐 SKU 验算
        │                                │  Step 7  SKU 四角色结构
        │                                │  Step 8  盈亏线 ROAS（交 06）
        └──────────────┬─────────────────┘
                       ▼
        输出：《产品需求表》→ 交 03 Listing / 04 Image / 05 Video / 06 Advertising
```

---

## 四、核心规则（SOP）

### 定价

| 项 | 规则 |
|---|---|
| 毛利目标 · 大件 | **30–35%** |
| 毛利目标 · 小件 | **25–30%** |
| 广告成本占比 | 大件 ~**5%** / 小件 **5–10%** |
| 退货损耗 | **2%** |
| 节奏 | **前期可略降毛利养权重，权重起来后再回提** |

**售价公式**（完整推导见 [`Templates/cost_pricing_template.md`](../../Templates/cost_pricing_template.md)）：

```
P = (产品成本 + 尾程物流 + 仓储费) ÷ (1 − 佣金率 − 广告率 − 退货率 − 目标毛利率)
```

### SKU 结构（SOP 3.2）

**核心判断**：SOP 明确说 —— **SKU 不是随便加的，而是为了让买家形成对比。**

| SKU 角色 | 作用 | 毛利定位 |
|---|---|---|
| **低价引流 SKU** | 加快广告效率、提高点击率 | 最薄（可低于目标 5–8 个点） |
| **主推 SKU** | 负责成交 | 目标毛利 |
| **高配 SKU** | 提高客单价 | 更高 |
| **套装 SKU** | **提高利润** | 最高 |
| （配合）优惠券 | **缩小价格差距** | — |

### 上架前 8 问（SOP 3.1）

上架前必须明确，缺一项就算没准备好：

1. 这个产品卖给谁
2. 核心卖点是什么
3. 主要竞品是谁
4. 价格打哪个区间
5. 主推 SKU 是哪个
6. 利润底线是多少
7. 是否适合广告测试
8. 可能的售后风险是什么

---

## 五、文件结构

| 文件 | 作用 |
|---|---|
| [`prompts/00_system.md`](./prompts/00_system.md) | 系统 Prompt：角色 + 定价与 SKU 规则 + 合规守卫 |
| [`prompts/01_product_decision.md`](./prompts/01_product_decision.md) | 任务 Prompt：产品定位 / 配置 / 卖点收敛 / 风险规避 / 上架前 8 问 |
| [`prompts/02_pricing_and_sku.md`](./prompts/02_pricing_and_sku.md) | 任务 Prompt：定价模型 + SKU 四角色 + 盈亏线 |
| [`templates/input_strategy_brief.md`](./templates/input_strategy_brief.md) | 标准输入 |
| [`templates/output_product_requirement.md`](./templates/output_product_requirement.md) | 标准输出：《产品需求表》 |
| [`examples/patinete_eletrico_strategy.md`](./examples/patinete_eletrico_strategy.md) | 真实案例：电动滑板车（接 01 的输出） |

---

## 六、一个重要的设计取舍

**本模块不做"选品决策"，只做"把已决策的产品规格化"。**

区别在哪：

| | 选品决策（人做） | 规格化（本模块做） |
|---|---|---|
| 问题 | "这个产品要不要做" | "要做的话，做成什么样" |
| 依赖 | 公司战略、资金、风险偏好、供应链谈判 | 市场数据 + 成本结构 |
| 能否验证 | 不能（结果要等几个月） | 能（配置对不对、价格算不算得出利润） |

所以本模块的输入里，**`decision_approved` 字段是必需的** —— 需要人明确确认"这个产品决定做了"，Agent 才开始做规格化。**Agent 不会替你说"建议做这个产品"。**

---

## 七、已知限制

| 限制 | 说明 |
|---|---|
| **不做选品决策** | 需人工确认 `decision_approved` |
| **不核价** | 成本结构由人填，Agent 无法验证采购价真伪 |
| **不算税费** | 巴西税费结构复杂，需在成本结构里自行计入 |
| **不含平台活动规则** | 活动价与库存联动（虾皮活动一旦参加无法退出）属运营执行范畴，本模块只给价格建议 |
| **卖点收敛依赖上游** | 若 01 未跑，`opportunity_config` 缺失 → 只能给通用卖点，差异化质量下降 |
| **前期养权重的降幅需人工定** | SOP 说"前期可略低"，具体降几个点取决于现金流与库存，Agent 只给区间 |

---

**返回**：[Agents 索引](../README.md) · **上游**：[01 Market Research](../01_Market_Research_Agent/) · **下游**：[03 Listing](../03_Listing_Creative_Agent/) · [06 Advertising](../06_Advertising_Optimization_Agent/) · **文档**：[定价模型](../../Templates/cost_pricing_template.md)
