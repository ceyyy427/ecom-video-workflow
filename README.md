<div align="center">

# 剪序 · ecom-video-workflow

**从商品资料与口播稿，到可修改、可审核的电商短视频。**

本地单用户工作台：商品脚本、实拍选段、配音字幕、逐镜编辑、版本恢复，以及客户投放后的数据复盘。

[Mac 使用指南](docs/MAC_WORKBENCH_GUIDE.md) · [安装与配置](docs/CUSTOMER_INSTALL.md) · [能力矩阵](docs/CAPABILITY_MATRIX.md) · [版本发布](https://github.com/ceyyy427/ecom-video-workflow/releases)

</div>

![剪辑工作台界面示意](docs/media/workbench-illustration.svg)

<p align="center"><sub>依据当前工作台绘制的界面示意，非浏览器截图；未使用客户素材。</sub></p>

## 让商品讲解有画面，让重点被看见

在同一个工作台里选素材、看原片、改一镜，配音、音乐与停顿字幕共用时间轴。改完先看影响范围，生成新版后再听审；旧片和确认记录保留。

![自主选择 Prompt 的页面示意](docs/media/prompt-library-illustration.svg)

**参考卡可以自己选。** 先选商品和那一句，再看人群、气质与原稿如何适配。已有本机变体可带回该镜草稿；待适配卡保留为资料。上图为界面示意，不代表所有参考效果已实现。

| 关键词重拍 | 分词揭示 | 大小字对照 |
|---|---|---|
| 让关键观察点落在人声重音处 | 随语义分组展开，保持字幕稳定 | 用大小层级说明一句话的主次 |

![本机真实渲染的三种文字表现](docs/media/typography-contact.png)

<details><summary>播放文字动效预览</summary>

![本机渲染动效](docs/media/typography-demo.gif)

</details>

预览由 Remotion 在本机实际渲染，商品为本项目绘制的示意道具。此处是无声编排演示；实际口播优先使用可信字锚点，不足时回退句级标题，动作段关闭文字运动。它不是客户成片签收或实拍样例。

![工作流程示意](docs/media/workflow.svg)

## 能做什么

| 环节 | 工作台能力 |
|---|---|
| 商品与文稿 | 上传资料、商品链接或自有脚本；保留事实来源，提供三套备选讲法及素材缺口 |
| 风格推荐 | 结合商品、目标人群、希望气质和可用素材，推荐叙事、画面与声音方向 |
| 实拍剪辑 | 同款/配色约束、主体可见度与动作检查；同句多段实拍、完整动作保护、逐镜人工调整 |
| 配音与字幕 | 上传配音或使用已配置火山语音；本机字级对齐、停顿分页、试听与单句重做 |
| 编辑与版本 | 素材库、成片/源片预览、四轨定位、修改影响预告、版本比较与恢复 |
| 审核与导出 | 事实、文稿、风格、听核和成片逐项确认；冻结导出已审/待审成果包 |
| 投后复盘 | 导入账户×素材×日报表，保留指标口径和缺失值；冻结快照、创意假设与下一版对比 |

主渲染使用 Remotion / FFmpeg，本机模型优先。平台投放由客户操作；工作台不自动投放，复盘提供描述性比较。

## 从素材到成片

1. **上传商品**：资料、图片、实拍，以及已有配音；填写目标人群和希望气质。
2. **确认文稿**：核对事实，选备选稿或粘贴自己的稿件，确认本版。
3. **选定方向**：比较三套方案与素材缺口，试听并确认配音。
4. **编辑分镜**：调整素材、动作、字卡和节奏，确认最终分镜后生成。
5. **看听与交付**：逐镜及整片审核，通过后导出；修改版保留原版。
6. **投后迭代**：客户投放后导入报表，冻结复盘，人工选择下一版假设。

## Mac 快速开始

面向 **Apple Silicon Mac**，基础环境使用 Python 3.11+、uv、Node.js 22/24、FFmpeg/ffprobe 和中文字幕字体。本机模型与依赖需要单独下载；软件包不包含客户项目、密钥或模型。

**客户软件包**：从[版本发布](https://github.com/ceyyy427/ecom-video-workflow/releases)下载 Mac ZIP，核对旁附 SHA256，完整解压后双击 `启动剪序.command`。首次配置和常见问题见[客户使用指南](docs/MAC_WORKBENCH_GUIDE.md)。这是联网安装依赖的源码客户版。

**从源码运行**：

```sh
git clone https://github.com/ceyyy427/ecom-video-workflow.git
cd ecom-video-workflow
python3 scripts/install_customer.py
python3 scripts/launch_customer.py
```

启动后按窗口显示的地址进入工作台。需要自行准备基础工具时，见[详细安装说明](docs/CUSTOMER_INSTALL.md)。Windows 入口及验证脚本保留，原生环境验收另行进行。

## 工作台入口

| 页面 | 用途 |
|---|---|
| `/create` | 商品资料、文稿、三方向、声音与剪辑工作台 |
| `/setup` | 环境自检、本机模型及语音配置 |
| `/prompts` | 自选参考卡、按商品及本句适配，带回镜头草稿 |
| `/samples` | 本机已有样片与效果参考 |
| `/distribution` | 客户投放后的报表导入与复盘 |
| `/experiments` | 冻结复盘、创意假设及版本对比 |
| `/maintenance` | 备份、恢复及独立版本升级 |
| `/guide` | 页面操作与常见问题 |

示意图展示流程，非浏览器截图。实际界面以启动后的本机版本为准；仓库不附客户素材与配音。

## 本版更新 · 0.17.0

- 三种可选文字表现，着重词只摘自确认文稿；测量本机字体，保护字幕阅读和完整动作。
- 参考库接入商品与逐镜选择，适配说明、可执行变体及来源在同一页，返回后仍是待保存编辑。
- 镜头参考页与剪辑工作台采用同一布局体系，来源和实现细节按需展开。
- 保留旧任务、原版文字效果和全部人工审批，未增加模型、云调用或自动投放。

操作见[文字与 Prompt 指南](docs/TYPOGRAPHY_PROMPT_GUIDE.md)，实测和回退见[本轮验收](docs/TYPOGRAPHY_PROMPT_ACCEPTANCE.md)。

## 文档

- [Mac 客户操作指南](docs/MAC_WORKBENCH_GUIDE.md)
- [首次安装](docs/CUSTOMER_INSTALL.md) · [备份恢复](docs/CUSTOMER_RECOVERY.md) · [客户交付清单](docs/CUSTOMER_HANDOFF.md)
- [架构](docs/ARCHITECTURE.md) · [状态机](docs/STATE_MACHINE.md)
- [配音授权配置](docs/VOLC_VOICE_AUTHORIZATION.md)
- [文字动效和手动 Prompt 采用依据](docs/third-party/typography-prompt-reuse.md) · [剪辑工作台参考](docs/third-party/p0-editor-reuse.md)

## 开发验证

```sh
uv sync --locked
npm ci --prefix render/remotion
node render/remotion/setup-browser.mjs
uv run pytest -q -k 'not actual_browser_layout'
node --test tests/web/*.test.cjs
npm run check --prefix render/remotion
```

自动测试里的模拟确认用于工程验收，不能代替客户实际听核或成片认可。

## 参考与声明

感谢 [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)、[NarratoAI](https://github.com/linyqh/NarratoAI)、[taste-skill](https://github.com/Leonxlnx/taste-skill) 及其他已记录的上游项目。采用的代码、方法与许可见 `docs/third-party/`；NarratoAI README 的信息组织方式也用于本页改版。

Remotion、模型和素材分别适用其许可与使用条件。客户原片和授权证明由客户保管；来源哈希用于追溯，不能代替授权证明。
