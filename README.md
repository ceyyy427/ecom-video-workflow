# 剪序 · ecom-video-workflow

**本地运行、可追溯的 AI 电商短视频制作与投后复盘工作台。**

从商品资料或已有文稿出发，辅助完成事实整理、脚本编排、三个风格推荐、实拍选段、配音字幕、分镜与成片，再关联投放后的报表、创意假设和下一版作品。

本项目面向本机单用户受控使用。事实、文稿、风格、人工听核和成片审核由人确认，平台投放由客户执行。公开仓库包含程序、测试与使用文档，不包含客户资料、原始素材、商业样片、数据库、密钥或模型权重。

## 工作流程

```mermaid
flowchart LR
  A[商品资料 / 已有脚本] --> B[来源与事实人工确认]
  B --> C[文稿确认与三风格选择]
  C --> D[本机素材识别与选段建议]
  D --> E[配音 / 字级对齐 / 人工听核]
  E --> F[分镜与版本化渲染]
  F --> G[内容预检与人工审片]
  G --> H[客户自行投放]
  H --> I[报表导入与冻结快照]
  I --> J[创意假设 / 人工选择 / 下一版]
  J --> C
```

## 核心能力

- **来源驱动的脚本：**读取文档或可访问的商品链接，保留原件、定位与哈希；根据确认事实与制作要求编排三份备选稿，不自动采用或编造卖点。
- **素材理解与自动选段：**本机视觉模型分析同款外观、主体可见度及有限动作区间，检查重复与素材缺口；支持严格复用、强制重推和逐镜人工调整。
- **三个制作方向：**结合商品、受众、目的与气质推荐三个方案；38张版本化项目Prompt卡，另有124张参考卡的本地索引，参考库不等于全部可执行模板。
- **配音与字幕：**上传现成配音或主动使用火山语音，支持试听、语速/语气、字级对齐、插值提示、单句重做及人工听核。
- **视频与局部修改：**Remotion与FFmpeg完成实拍剪辑、图片运镜、动效、转场、字幕及混音；单镜/单句修改形成新版本，保留父片和审核链。
- **受控工具执行：**严格工具契约、CLI/API、持久化运行事件、结构化错误、有界执行、暂停恢复与取消；不会替用户确认事实或放行成片。
- **描述性复盘：**账户×素材×日报表、缺失与口径保留、冻结证据、成片版本关联、创意假设与下一轮对比。不进行因果归因或自动投放。
- **本机交付：**双击启动、首次配置、环境自检、备份校验、新目录恢复与升级前备份。Windows提供兼容入口，实际机器仍需独立验收。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端与契约 | Python 3.11+、FastAPI、Pydantic、Uvicorn、HTTPX |
| 网页工作台 | 原生HTML / CSS / JavaScript，无前端框架构建依赖 |
| 视频渲染 | Remotion 4、React 19、TypeScript、FFmpeg / ffprobe、Pillow |
| 本机视觉 | Ollama / llama.cpp、Qwen3-VL；可选后端实验保留质量门槛与回退 |
| 配音与对齐 | 火山引擎语音、FireRed ASR CTC、sherpa-onnx |
| 持久化与任务 | SQLite WAL、本地文件、任务状态机、Worker租约、版本与SHA-256 |
| 工程验证 | pytest、Node Test / VM、Ruff、TypeScript检查 |

React用于独立视频渲染模块，网站本身使用原生JavaScript。没有把Redis、Celery、LangChain或LangGraph列为本项目依赖。

## 快速开始

先准备 Python 3.11+、uv、Node.js 22或24、FFmpeg / ffprobe及可用中文字体。初次安装需要网络下载锁定依赖和渲染浏览器；模型、语音服务需另外配置。

```sh
git clone https://github.com/ceyyy427/ecom-video-workflow.git
cd ecom-video-workflow
python3 scripts/install_customer.py
uv run python -m ecom_video --customer --data var --port 8765
```

打开 `http://127.0.0.1:8765/setup` 检查环境与配置，再到 `/create` 创建商品项目。macOS也可双击 `启动剪序.command`，Windows使用 `启动剪序.cmd`。

`--customer` 强制关闭平台写入和自动Agent执行，保留交互制作、CSV冻结复盘与创意迭代。Agent开发入口与显式启用方式见P13/P14文档。不要把此本机服务直接暴露到公网。

没有视觉模型时可手动选段，没有语音Key时可上传成品配音。Key只在自己的本机配置，勿提交到Git或聊天。公开版样片页初始可为空；用自己的授权素材制作，或按安装指南运行明确标注为模拟确认的隔离合成示例。

## 页面入口

| 地址 | 用途 |
| --- | --- |
| `/create` | 商品、资料、文稿、三个方向、声音与制作 |
| `/` | 完整分镜与已有任务 |
| `/studio` | 风格、品牌、口播字级时间与听核 |
| `/samples` / `/prompts` | 本机已生成样片 / 固定版本镜头参考 |
| `/distribution` / `/experiments` | 冻结复盘 / 创意假设与下一轮对比 |
| `/setup` / `/maintenance` / `/guide` | 配置 / 备份恢复与版本 / 操作指南 |

## 目录

```text
ecom_video/             API、状态机、Agent、素材识别、配音、渲染与复盘
ecom_video/web/         本机网页工作台
ecom_video/migrations/  SQLite版本迁移
ecom_video/data/        固定镜头参考索引与相应许可
render/remotion/       React / TypeScript视频合成模块
scripts/               安装、启动、校验与隔离演练工具
tests/                 单元、接口、状态机、媒体及DOM契约测试
docs/                  架构、使用与第三方许可
```

## 验证

安装锁定依赖后，在临时测试数据上运行：

```sh
uv run pytest -q -rs -k 'not test_focus_frame_contains_requested_media_point_in_actual_browser_layout'
node --test tests/web/*.test.cjs
uv run ruff check ecom_video scripts tests
npm run check --prefix render/remotion
```

媒体测试需要FFmpeg及中文字体，原生Windows和显式授权钥匙串测试在不满足条件时跳过。私有历史客户证据不随仓库发布，对应的一项历史回归在缺少该证据时明确跳过。测试通过不等于真人听核、客户作品签收或所有模型场景准确。

本公开快照在现有macOS开发机上验证：836项Python测试、20项Node/VM测试通过；4项因私有证据或平台条件跳过，1项真实浏览器用例按约定排除。Ruff与Remotion类型检查通过。

公开快照的实际验收范围见 [公开版说明](docs/PUBLIC_SOURCE.md)。性能说明见 [固定素材阶段测试](docs/BENCHMARK.md)。

## 文档与边界

- [首次安装](docs/CUSTOMER_INSTALL.md) · [Windows](docs/CUSTOMER_WINDOWS.md) · [备份恢复](docs/CUSTOMER_RECOVERY.md)
- [架构](docs/ARCHITECTURE.md) · [状态机](docs/STATE_MACHINE.md) · [能力与限制](docs/CAPABILITY_MATRIX.md)
- [统一工具入口](docs/P13_USAGE.md) · [有界执行](docs/P14_USAGE.md) · [冻结复盘](docs/P15_USAGE.md) · [创意迭代](docs/P16_USAGE.md)

这是本机辅助制作工具，不是无人值守广告系统；复杂遮挡、同款判断、文稿说服力和实际画面质量仍需人工检查。报表接口框架和模拟验收不代表已完成所有客户账户联调。页面和模型的工程检查不构成平台合规认证。

## 许可与致谢

本项目代码暂未授予统一开源许可证；公开展示不自动授予本项目代码的商业使用许可，见 [现有交付说明](CUSTOMER_NOTICE.md)。第三方内容适用各自许可：MoneyPrinterTurbo / Huashu Motion等MIT方法参考、Shotcraft参考库的Apache-2.0，以及Remotion专用许可。许可文本位于 `docs/third-party/` 与对应参考目录；模型与客户素材另行核对授权。

完整第三方仓库、字体、音色样本、品牌画面和模型权重不随本仓库分发；相关Skill方法没有被当作可执行的任意远程指令加载。
