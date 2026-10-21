# 剪序 · 客户试用交付说明

本包是本机单用户试用源码包。项目自身的使用与交付范围依双方约定，不因第三方参考项目采用MIT而将本项目全部代码自动声明为MIT。

入口：`docs/CUSTOMER_INSTALL.md`。包内不含客户资料、旧数据库、私钥、平台令牌、模型权重或系统字体；独立配置后才能制作带配音作品。开源依赖由锁文件安装，其许可随相应依赖提供。

字幕布局和语音文字匹配参考 MoneyPrinterTurbo，保留 `docs/third-party/MoneyPrinterTurbo-LICENSE`。动效参考 Shotcraft / mg-styles，保留相应 `vendor/*/LICENSE`；本包只带许可文本，不包含这些仓库的示例素材、字体或品牌画面。

Remotion使用其专用许可，见`docs/third-party/Remotion-LICENSE`；正式客户使用资格与范围须按该许可核对，不因参考项目采用MIT而改变。

内置安装演示素材由本项目代码原创生成，标注为合成示例，仅验证链路，不代表真实商品外观、材质、功效或识别准确率。自动化演练确认均标为fixture，不是客户审批。客户自己上传的文字、图片、视频、声音需另行取得使用授权。

平台投放由客户操作；客户模式强制关闭平台写入和自动Agent执行。事实、文稿、风格、听核和成片审核继续人工。不承诺销售效果、自动合规或因果归因。

0.13.1 增加Windows 11 x64兼容入口、锁/进程/语音凭据保护与验收脚本；当前交付记录仍须区分macOS实际验收与Windows待真机验收。Windows自动画面文字OCR尚不可用，应人工补检，不能作为自动合规通过依据。

视频精修说明：新增代码只借鉴 video-use / agent-caption 的 MIT 代码方法和 HyperFrames 的 Apache-2.0 制作规则；许可证在 docs/third-party。未使用其字体、媒体或 MMS_FA 等模型权重，未把其安装器和云服务接入运行。标题字体取自客户操作系统，不随包分发。客户商品素材、品牌授权和原有依赖许可仍须按既有清单核对。

Huashu Motion方法参考：固定提交的MIT方法文档用于本机产品方向与节奏规则，许可证见docs/third-party/huashu-motion-LICENSE。未复用其引擎、字体、音色采样、模型、媒体或作者卡通角色；代码不读取或执行上游Prompt。
