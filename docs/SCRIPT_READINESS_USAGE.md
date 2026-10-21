# 商品脚本、制作前素材检查与综合审核

本轮在既有客户流程上增加三项能力；本机优先，不新增云模型、不改投放接口。事实、文稿、风格、配音听核与成片审核继续人工；没有自动合规放行。

## 客户怎么操作

1. `/create` 上传商品资料和许可素材，保存类别、人群、气质与片种，人工核对事实。首次确认事实后生成本机定向稿；有原稿时优先保留原稿和配音。
2. 点击“按已保存的人群与气质生成新版文稿”，得到开头、事实顺序、逐句镜头目的/素材建议、结尾。旧稿和旧片保留，新稿待确认。商品陈述直接引用已确认事实，不自由扩写功效或杜撰体验；目前是有限模板编排，不是通用营销创作模型。已有配音不会被偷偷替换，新稿需要对应配音。
3. 保存稿件和素材修改，点击“检查当前文稿与素材缺口”。报告逐句显示：缺口、未知、候选待回看，附来源、观察与候选区间。未配音时是时长估算；本版对齐/分镜有效时用实测时间。报告只读，不产生确认。
4. 缺口：补拍/上传、调整文稿后重新确认，或关闭自动选段后人工安排。未知：先完成识别，或人工核对。候选：必须回看同款、连续性和真实动作，不能把“可折叠/倒水后”当正在操作。一句多个肯定动作全部检查；不要/无需等否定句不要求演示该动作。
5. 确认文稿→选择三推荐中的一个→配音/本机对齐→人工听核→分镜→生成。自动选段在规划前阻止已知素材缺口；手动模式仍允许人工安排，旧任务不后台重编排。
6. 生成后客户页显示综合审核范围与问题，可跳到具体时间核对，下载审核JSON/HTML。审核意见和勾选仍由人填写；不满意继续单镜改画面/单句换声，新版重新听审。

## 检查范围

| 项目 | 本轮实际检查 | 不代表什么 |
|---|---|---|
| 脚本文字 | 既有版本化有限规则、行号/镜头/时间 | 未命中不等于合规 |
| 来源与商品依据 | worker校验来源/素材字节；冻结事实引用与确认身份 | 不证明来源真实、引用充分或商品功效 |
| 素材覆盖 | 有限商品/场景词表、所有肯定动作、候选连续时长、源哈希与识别版本 | 不是通用语义理解、完整分配或SKU鉴定；未知品类明确未知 |
| 实际选段 | 对照冻结源区间与观察交集；动作只有带时间证据覆盖所选范围才可作为该处线索 | 整段标签不能证明所选局部发生动作；无时间证据标未知、人工回看 |
| 画面文字 | macOS Apple Vision，逐镜中点最多12帧，风险词定位到采样时间 | 不是全帧OCR或完整视觉内容审核；截图可能漏字、错字、跨框拼接误报 |
| 实际口播 | 本机FireRed重新识别最终音轨（最多120秒），规则词及与确认稿的文字差异定位 | 不自动纠错或改稿；识别相似度不是准确率、事实或合规判定 |
| 时间与质量 | 既有本版字锚点/听核、编码尺寸/帧数/时长、完整解码 | 不证明主观美术、声音自然或字幕语义都正确 |
| 未覆盖 | 人物/音乐/字体/素材授权、平台最新规则与资质、全部视觉语义 | 明确未检查，仍需人工；不以OCR替代同款或危险内容识别 |

所有区段显示 `checked/sampled/partial/needs_review/not_checked/error/not_applicable`，没有自动pass状态。OCR/ASR识别出的风险标待核对，保留原规则严重性；原脚本阻断规则继续在渲染前生效。纯展示未声明口播时，不自动对音乐等音轨做语义识别。

## 接口和运行

- `POST /api/products/{pid}/scripts/generate`，旧 `extractive/model` 保留；新 `mode=directed` 可带严格 `brief={format,category,audience,tone}`，仍须当前产品revision。模式为本机，无外部同意或云请求；返回待确认新稿，场景新增可选intent/visual_hint，首镜brief记录输入，旧场景结构兼容。
- `GET /api/customer-projects/{pid}/preflight` 只读，无模型调用；最多30句、100素材，每素材最多40个识别段。返回当前草稿、时间依据、指纹、逐句状态及制作前阻碍，不冻结审批。相同输入稳定；输入/识别/时间改变后重查。
- worker生成 `audit.json`（schema2）和 `audit.html`，登记 `audit/audit_html` 产物，绑定job、snapshot哈希和成片SHA。报告来自提交冻结输入，不从后来编辑的项目重算；重复下载不改旧记录。旧版只有文字预检时明确提示。
- `ECOM_MEDIA_AUDIT=1` 启用本机成片OCR/ASR；未启用、依赖未就绪或失败均明确标注。macOS需Swift和系统Vision；其他系统本轮不安装替代OCR。ASR沿用现有 `var/models/firered`。不读取或展示密钥，不自动下载模型。
- OCR进程限90秒，最终ASR限120秒，取帧每次20秒；继承worker原30分钟和Agent总预算/取消。媒体依赖错误留待人工，取消或预算异常必须传播，不能作为检查失败被吞掉。
- 属于Agent的审核继承原执行scope，OCR每个采样帧/ASR一次先预留本机模型预算；预留按尝试计数，失败不返还。不属于Agent的普通人工提交保持原流程，没有启动额外Agent消费者。

## 复跑示例

```sh
.venv/bin/pytest -q
.venv/bin/ruff check ecom_video tests scripts
npm --prefix render/remotion run check
# 新的项目外隔离目录；以下均不调用云合成，确认均为AUTOMATED FIXTURE。
.venv/bin/python scripts/accept_script_readiness.py --data /tmp/ecom-readiness-new --stage intake
.venv/bin/python scripts/accept_script_readiness.py --data /tmp/ecom-readiness-new --stage scan
.venv/bin/python scripts/accept_script_readiness.py --data /tmp/ecom-readiness-new --stage produce
.venv/bin/python scripts/publish_readiness_sample.py --data /tmp/ecom-readiness-new
.venv/bin/python scripts/check_readiness_ui.py --data /tmp/ecom-readiness-new
```

示例重新上传既有许可耳机两条实拍，真实本机扫描、Tingting声音、ASR和渲染；模型建议与人工回看区间分开保存，不把校正算自动准确率。发布脚本只更新新增示例目录，不往正式库导入假审批。

本轮不迁移数据库，schema仍14，不改vendor和渲染引擎。关闭媒体开关可停额外OCR/ASR，结构化报告和历史片保留。硬回退源码前备份新文稿与产物；旧程序不认识新增场景提示和新中性模板，勿交旧编辑器重存新稿。

OCR采用项目自写适配器，参考 [Apple Vision官方接口](https://developer.apple.com/documentation/vision/vnrecognizetextrequest)，不复制外部实现。实际结果见 验收记录（历史记录或本机文件，未随公开版分发）。
