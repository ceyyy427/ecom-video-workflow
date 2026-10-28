# D1 开源复用与采用依据

核对日期：2026-10-28。D1 不安装新运行时或模型，继续当前 Apple Silicon / FFmpeg / Remotion / Pydantic / SQLite 环境；未改变本机识别后端及资源门槛。

| 来源 | 固定版本/许可 | 采用 | 未采用与理由 |
| --- | --- | --- | --- |
| [运营工具箱上游](https://github.com/heqiangdiao-wq/AI-Cross-Border-Ecommerce-Agent-Toolkit) | `cec98a9cab382d28dfe5b4ed0de444f33c455cb5`，MIT | 单一核心卖点、输入→产物→自检、事实与来源分离的方法 | 海外平台假设、葡语空格词速不适合中文；不执行上游参考 Python |
| [国内 Fork D1](https://github.com/ceyyy427/AI-Cross-Border-Ecommerce-Agent-Toolkit/tree/fffa8b71747cd0b45ac53c64b330cfcad8884e10/Domestic) | `fffa8b71747cd0b45ac53c64b330cfcad8884e10`，保留 MIT | 三种叙事×两种视觉、国内定位/文案方法、版本化策略 JSON | 提示文档不当作系统指令运行，不增加账户或云权限 |
| 既有 `spoken_copy.py` / Humanizer 信息保留方法 | 沿用仓库已记录来源与许可 | 完整原文+受控连接、型号和条件保护 | 不声称规则替代自由口语创作或语义等价验证 |
| 既有六预览管线及 Lemo 视觉适配 | 沿用 [既有来源记录](six-previews-reuse.md) | 原六个可执行结构、七秒预览、计算租约、素材冻结、采用与逐镜编辑 | 不新增第二套队列/数据库，不复制未核对媒体，不将风格 ID 差异当审美通过 |

资源锁共31份文本，逐份保留仓库、提交、路径、字节数、SHA 与 MIT；新策略和三份方法提示绑定本机编排器适配路径，其余仍是参考。运行时只读取数据策略；不执行其中脚本或提示文档，不自动联网替换资源。损坏即停止，能力接口不宣称可用。

## 国内平台依据

- [抖音开放平台协议](https://open.douyin.com/platform/resource/docs/operation-standard/agreement-protocol)：参考一般内容真实性原则，不作为特定广告资质、字数、时长或尺寸规则。
- [小红书商品推广内容规则](https://school.xiaohongshu.com/rule/detail/3439)：用于商品描述与实际一致的核对提示。具体品类、账号及规则有效状态仍由客户发布前核对；已失效的规则页不作为硬限制。

平台标题/正文的不同写法是创作建议，不代表平台审核通过；本期没有平台登录、发布或投放接口调用。

## 实拍样例使用范围

两个不同品类分别使用 [Maksim Semashko 的鲜橙实拍](https://www.pexels.com/video/cutting-orange-with-knife-13107467/) 和 [Tima Miroshnichenko 的滴管瓶实拍](https://www.pexels.com/video/person-opening-a-bottle-of-a-beauty-product-7607242/)。2026-10-28重新核对 [Pexels许可](https://www.pexels.com/license/)：允许修改/剪辑，不暗示人物或品牌背书；不作为客户 SKU、产地、营养或护肤功效依据。仅使用本机已留存的原片，SHA 与来源另存隔离验收清单，不把客户参考视频公开提交。
