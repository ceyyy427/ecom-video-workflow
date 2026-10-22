# P0 客户剪辑工作台：开源采用记录（2026-10-22）

| 来源 | 固定版本 / 许可 | 采用 | 不采用及原因 |
|---|---|---|---|
| [taste-skill](https://github.com/Leonxlnx/taste-skill) | `6010f91a9935f1c167dfc500fb1a475681892e6b`，MIT | 已下载到 vendor/taste-skill；安装 design-taste-frontend；固定 framed-sheet / builder 方向（seed 1222365105）；中性框架、素材/预览/检查器/时间线、次要报告折叠 | 不整站推倒重建，不复制示例的虚假波形或审批；保留原 DOM 控件与业务接口。技能安装后新对话可发现 |
| [NarratoAI](https://github.com/linyqh/NarratoAI) | `dcdb819e893a3f95b01d68e7e815540ac3522d24`，MIT | 直接复用 `app/services/subtitle_text.py`，附来源/完整 MIT；生产模块 ecom_video/narrato_subtitle_text.py；字幕 BOM/编码/行尾兼容，用于真实 SRT 时间线 | 不引入整个 Streamlit/MoviePy/云 SDK 栈；不采用去标点方法或按字数猜时间，保留型号小数、原稿和 ASR 锚点 |
| [Cut 界面案例](https://ui.oiloil.org/works/editor/) | 仅交互参考，未取得可复制代码/媒体许可 | 学习素材库、预览、轨道和即时定位的结构 | 未复制页面代码、媒体及收费组件 |
| [LinkeDOM](https://github.com/WebReflection/linkedom) | 0.18.12，ISC | 仓库外测试环境 W/dom-tools，使用真实 customer.html 做 DOM 事件测试 | 不增加产品依赖；不把 DOM 测试称作浏览器截图或布局验收 |
| Remotion | 继续锁定现有 4.0.519 | 现有 React 叠字与字幕组件；小字可逐镜编辑并绑定审批版本 | 不换渲染引擎、不添加远程字体与素材，不改变本机模型优先策略 |

- 两仓库为参考下载，客户运行不需要加载其完整依赖。声明保存在本目录 `taste-skill-LICENSE`、`NarratoAI-LICENSE`。
- 新运行依赖：无。模型、GPU/内存要求沿用原版本。测试用 LinkeDOM 在仓库外安装。
- 新界面无自动审批请求，拖动只修改本地草稿；实际写入仍经过影响预告及原有保存按钮。
- 未使用 Computer Use。Remotion 的无头视频渲染属于原生产渲染流程，没有进行浏览器操作或 UI 截图验收。

- 导出误判依据：[Pydantic 官方 fields 文档](https://docs.pydantic.dev/latest/concepts/fields/#validate-default-values)说明默认值默认不验证。实际定位为 MotionPlan 的 int 0 默认值经再次校验成为 float 0.0；只在分镜绑定比较中按现有 Board 模型规范化，不改历史审批/快照/视频。原样匹配仍保留旧 schema 兼容，真正改字或时机仍不相等。
