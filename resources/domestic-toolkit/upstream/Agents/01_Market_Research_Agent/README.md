# 01 · Market Research Agent

**市场分析智能体** · 输入类目数据，输出**"这个产品该不该做、该做什么价位、做什么配置"**的判断。

---

## 一、它解决什么问题

SOP 第一章有 10 个小节，判断标准非常完整。但实际执行时卡在两个地方：

| 痛点 | 表现 | 本模块怎么解 |
|---|---|---|
| **数据进不来** | 导出表格式五花八门，每次都要手工整理 | **`scripts/` 里有两个脚本**：格式标准化 + 指标计算 |
| **指标算不准 / 每次不一样** | 手工算集中度、画价格曲线、做配置交叉表 | 脚本算（确定性），Agent 只解读 |
| **算完不知道意味着什么** | 一堆数字，不知道哪个说明"可以做" | Prompt 里内置 SOP 的判断阈值与判定规则 |

**产出物**：类目前置判断结论 → 市场容量与集中度判断 → 价格带选择 → 配置组合推荐 → 竞品与评论洞察。

---

## 二、覆盖的 SOP 章节

| SOP | 内容 | 落在哪 |
|---|---|---|
| **1.1** | 类目前置判断（是否适合公司货盘 / 是否高风险类目） | `prompts/01_category_precheck.md` |
| **1.2** | 市场容量与销量分析 | `prompts/02_market_analysis.md` |
| **1.3** | 品牌集中度与卖家集中度 | `prompts/02_market_analysis.md` |
| **1.4** | 价格分析（价格带划分） | `prompts/02_market_analysis.md` + `scripts/market_metrics.py` |
| **1.5** | 产品类型与配置组合分析 | `prompts/02_market_analysis.md` + `scripts/market_metrics.py` |
| **1.6** | 竞品分析与评论分析 | `prompts/02_market_analysis.md`（评论深度分析交给 [`07`](../07_Review_Analysis_Agent/)） |
| 1.7 | 主推产品确认 | → 交给 [`02 Product Strategy`](../02_Product_Strategy_Agent/) |
| 1.8 | 关键词表 | → 交给 [`03 Listing Creative`](../03_Listing_Creative_Agent/) |
| 1.9 | 定价 | → 交给 [`02 Product Strategy`](../02_Product_Strategy_Agent/) |
| 1.10 | 推广计划 | → 交给 [`06 Advertising`](../06_Advertising_Optimization_Agent/) |

> **本模块的边界**：只回答"**要不要做、做哪个价位与配置**"。不回答"做成什么样"（02）、"怎么写"（03）、"怎么投"（06）。

---

## 三、工作流

```text
① 导出类目数据（虾多拉 / 平台后台 / 第三方工具）
              ▼
   ┌──────────────────────────────────────┐
   │ scripts/shaduola_parser.py           │  格式标准化：洗掉货币符号/千分位/
   │                                      │  万单位/空值/日期 → 统一 JSON
   └──────────────┬───────────────────────┘
                  ▼
   ┌──────────────────────────────────────┐
   │ scripts/market_metrics.py            │  指标计算（确定性，非 LLM）：
   │                                      │  容量 / CR3·CR10·HHI / 价格分箱
   │                                      │  + 波谷检测 / 配置交叉表
   └──────────────┬───────────────────────┘
                  ▼  metrics.md + metrics.json
        ┌─────────────────────────┐
        │ prompts/00_system.md    │  角色 + SOP 判断阈值 + 合规守卫
        └───────────┬─────────────┘
                    ▼
        ┌─────────────────────────┐
        │ 01_category_precheck.md │  Step 1  前置判断（能不能做）
        │                         │  → 不适合则**直接停止**，不往下分析
        └───────────┬─────────────┘
                    ▼
        ┌─────────────────────────┐
        │ 02_market_analysis.md   │  Step 2  容量 + 集中度 + 价格带
        │                         │  Step 3  配置组合 + 竞品/评论
        └───────────┬─────────────┘
                    ▼
        输出：交付给 02 Product Strategy 的字段包
```

### 为什么 Step 1 要能"叫停"

SOP 1.1 的核心判断是：

> 如果公司没有供应链、没有售后能力、没有价格优势，**即使市场不错，也不一定适合做**。

所以前置判断的作用是**过滤**，不是"走个流程"。如果某个高风险类目（如易碎、需认证、参数易虚标）没有高利润支撑，Prompt 会直接输出「不建议进入下一步」，而不是继续算容量和价格 —— **避免下游做无用功**。

---

## 四、脚本层：能算的别让模型猜

这是本模块与其他"市场分析 Prompt"最大的区别。

| | 交给脚本 | 交给 Agent |
|---|---|---|
| 集中度 CR3/CR10/HHI | ✅ 确定性计算 | — |
| 价格分箱统计 | ✅ | — |
| 波谷检测（价格带边界） | ✅ 带显著性过滤 | — |
| 配置交叉表（四维统计） | ✅ | — |
| "这个市场值得进吗" | — | ✅ 判断 |
| "选哪个价格带" | — | ✅ 结合成本与竞品判断 |
| "推荐什么配置组合" | — | ✅ 结合公司能力判断 |

**判断依据**：结果唯一（算 100 次一样）→ 脚本；需要取舍（依赖公司资源、成本、风险偏好）→ Agent。

详细说明见 [`scripts/README.md`](./scripts/README.md)。

### 快速跑通

```bash
cd scripts
python make_sample.py                                    # 生成样本（合成数据）
python shaduola_parser.py ../samples/sample_patinete_eletrico.csv
python market_metrics.py ../samples/sample_patinete_eletrico.normalized.json \
    --bins 10 --config-fields "功率,承重"
```

产出 `metrics.md`（给人看）与 `metrics.json`（给后续流程消费）。

---

## 五、文件结构

| 文件 | 作用 |
|---|---|
| [`scripts/shaduola_parser.py`](./scripts/shaduola_parser.py) | 格式标准化：脏数据 → 统一 JSON |
| [`scripts/market_metrics.py`](./scripts/market_metrics.py) | 指标计算：容量 / 集中度 / 价格带 / 配置交叉表 |
| [`scripts/make_sample.py`](./scripts/make_sample.py) | 生成样本数据（含脏数据格式） |
| [`scripts/README.md`](./scripts/README.md) | 脚本用法与算法说明 |
| [`prompts/00_system.md`](./prompts/00_system.md) | 系统 Prompt：角色 + SOP 判断阈值 + 合规守卫 |
| [`prompts/01_category_precheck.md`](./prompts/01_category_precheck.md) | 任务 Prompt：类目前置判断（1.1） |
| [`prompts/02_market_analysis.md`](./prompts/02_market_analysis.md) | 任务 Prompt：容量/集中度/价格带/配置/竞品（1.2–1.6） |
| [`templates/input_category_research.md`](./templates/input_category_research.md) | 标准输入 |
| [`templates/output_market_analysis.md`](./templates/output_market_analysis.md) | 标准输出 |
| [`examples/patinete_eletrico_market.md`](./examples/patinete_eletrico_market.md) | 真实案例：电动滑板车类目 |
| [`samples/`](./samples/) | 样本数据与预期结果 |

---

## 六、SOP 给出的判断阈值（Prompt 内置）

| 维度 | 阈值 | 出处 |
|---|---|---|
| 品牌集中度 | **< 50%** → 白牌仍有机会；**> 50%** → 谨慎进入 | SOP 1.3 |
| 卖家集中度 | 看 **CR10**（前 10 卖家销量占比） | SOP 1.3 |
| 价格带选择 | 找**销量高 + 平均销量高 + 有利润 + 竞品不强**的段，不是找最高峰 | SOP 1.4 |
| 价格带划分方法 | 横轴价格区间、纵轴销量，**从波谷到波谷**划分 | SOP 1.4 |
| 配置判断 | 四维：总销量 / 平均销量 / 数量占比 / 单品效率 | SOP 1.5 |
| 数据样本 | 前 **50** 商品；若 50 名之后销量没断崖式下跌，扩到 **100** | SOP 1.4 |
| 高风险类目 | **高风险类目需要高利润才能承载** | SOP 1.1 |
| 新品表现 | 新品能否出单是新链接机会的核心信号（⚠️ 虾多拉该数据不准，需人工核对） | SOP 1.2 |

---

## 七、已知限制

| 限制 | 说明 |
|---|---|
| **不抓数据** | 数据来源需自行导出。V2 接 API 后可自动化 |
| **不算税费** | 巴西税费复杂，不在指标层处理 |
| **"新品销量"精度有限** | SOP 原文即注明"虾多拉数据不准确"，脚本只用 `listing_age_days` 做粗略分层，**必须人工核对** |
| **配置抽取是启发式** | 配置只在标题里时靠正则抽取，抽取率可能偏低（报告会标出失败数） |
| **HHI 无行业基准** | 脚本只给原始值，判断交给 Agent |
| **不做选品决策** | 只输出分析结论。**最终决策必须由人做**——涉及公司资源、供应链与风险偏好，Agent 无法代劳 |
| **竞品评论是浅层** | 本模块只做"竞品靠什么卖"的粗判断；深度归因交给 [`07`](../07_Review_Analysis_Agent/) |

---

**返回**：[Agents 索引](../README.md) · **下游**：[02 Product Strategy](../02_Product_Strategy_Agent/) · **文档**：[SOP 拆解](../../docs/00_Architecture_SOP_to_Agent.md) · [自检清单](../../docs/04_Result_Checklist.md)
