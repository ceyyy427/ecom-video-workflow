# 国内电商运营适配 · D0

面向抖音、小红书，采用“运营方法资源＋剪序本机执行器＋人工审核与复盘”。

本分支仅建立 D0 资源与契约映射及 D1 内容规划适配，D2–D6 尚未实施。原始上游 `Agents/` 保留；运行应用以[剪序](https://github.com/ceyyy427/ecom-video-workflow)为准。

## 维护边界

- 上游固定在 `cec98a9cab382d28dfe5b4ed0de444f33c455cb5`，来源与许可保留。
- 国内资源由 `manifest.json` 管理；剪序交付包只同步选定文本，校验哈希，不执行本仓库脚本。
- 共用协议为 `SuiteBrief.v1`、`SuitePlan.v1`、`ToolSpec.v1`、`OpsResult.v1`；定义与严格验证由剪序维护，避免两套协议实现。
- 视频模块先交给已有本机识别、字幕、声音时钟、Remotion/FFmpeg；不会凭空增加商品实拍。
- 事实、文稿、风格、听核、成片审核仍由客户按版本确认；没有自动发布、投放或互动工具。
- 中文不能直接套用葡语空格词数/词速；国内平台规则、费率和权限需要分别核验。
- 原始内部 PDF、示例媒体、跨境平台费率不进入剪序资源包。

## 模块

- [市场资料](01_Market/README.md)：D5，待实施。
- [商品定位](02_Positioning/README.md)：D1，待实施。
- [平台内容](03_Content/README.md)：D1，待实施。
- [封面图文](04_Image/README.md)：D5，待实施。
- [商品视频](05_Video/README.md)：D1–D2，待实施。
- [数据复盘](06_Performance/README.md)：D4，待实施。
- [评论洞察](07_Comments/README.md)：D4，待实施。

上游资源的 MIT 声明见[LICENSE](../LICENSE)。其他平台、模型、渲染组件的许可独立核对。

## D1

国内内容策略见 [content-policy.json](content-policy.json)。02/03/05 已接入剪序编排，仍是待人工选择的草稿。预览不合成声音或代表客户签收；完整自动执行与平台连接留在 D2/D3。
