# 客户商品的完整编排

2026-10-18，在既有客户制作流程接入透明杯三片的叙事能力，继续使用 Remotion 和本机识别；不是新增云端Agent、自动投放或上游全库移植。

## 怎么使用

1. 在 `/create` 上传商品资料、真实图片/视频，核对事实与文稿。保存类别、目标人群、希望气质和片种。
2. 确认文稿后显示三个推荐。每个方向同时给出匹配依据、完整叙事、实拍安排、动效组合和语气/语速；选定方向后再试听、合成或上传声音。
3. 开启“自动选段”后，先完成本机内容识别。普通语义选段不强制参照图；同款核对/动作词对齐仍需参照图和原有开关，风格不能替代动作证据。
4. 完成配音对齐与人工听核，再生成分镜。镜头长度跟随已听核声音，不因换风格偷偷变速或改写稿件。
5. 播放核对素材、动作与焦点；可逐镜改入点、画幅、字卡、动效强度、出现时机和保护区间。素材不够时补拍或手动安排，不使用无关片段凑数。
6. 提交生成后保留旧版；可以只重做一句配音，或只修改一个镜头。声音改变仍需重新听核；所有新版都必须人工审片。

## 本轮统一了什么

| 方向家族 | 实拍与信息 | 动效和衔接 | 声音 |
|---|---|---|---|
| 克制质感 | 商品先出现、局部细节、完整收尾 | 轻落标题、留白、语义换章的线条接力 | 既有克制/温暖声音配置，镜长以原声为准 |
| 生活种草 | 清楚商品与使用场景接力，连续动作优先 | 强开头、短大字、语义换章推叠 | 朋友分享/生活语气，先试听再采用 |
| 细节解说 | 整体、局部、实际动作、回到整体 | 观察框与扫描，动作句静态留看 | 清晰自然讲解，不伪称测试结果 |

九种现有样式仍保留各自视觉与声音差异，按已确认商品文稿/类别/人群/气质用本机规则推荐三个；不是每次随机换三种，也不是通用审美模型。没有填写气质/人群时，通用三个方向也显示完整编排，不沿用杯具专用标题。

选段的优先级仍是：商品/动作/时长硬约束 → 文稿相关性 → 稀缺片段预留 → 视频/重用与重叠控制 → 风格景别。风格只在前述条件相同时打破平票，不为种草气氛牺牲商品匹配。细节语句优先细节，不被生活场景替代。

折叠动作句须有明确进行中的动作标签；“可折叠/折叠后”不足以自动采用，缺证据时回看、补拍或人工选段。纯结尾核对提醒可用有限整句模板留看已识别的单一商品整体，保留原模型分与 `local_product_outro` 编辑规则标记；不能用它证明参数、追加性能卖点或混合商品。更多未知措辞仍交给模型建议和人工核对。

新分镜以 `creative.production = narrative-v1` 留档；每镜的实际动效、转场、声音时间与素材选段仍按原契约冻结。旧分镜缺省null，不后台重编排；不迁移数据库，schema仍14。人工覆盖推荐是允许的，已生成成片的单镜调整不能暗改相邻转场。

## 复跑

```sh
.venv/bin/pytest -q
.venv/bin/ruff check ecom_video tests scripts
npm --prefix render/remotion run check
.venv/bin/python scripts/check_shotcraft_ui.py --evidence docs/evidence/production-directions
# 新的外部目录；仅本机识别，不发云请求。
.venv/bin/python scripts/accept_categories.py --data /tmp/ecom-production-new --case headphones --spec docs/evidence/production-directions/case.json --prepare-only
# --live 最多3次火山请求：首句试听、整稿、第三句重做；使用本机已配凭据。
.venv/bin/python scripts/accept_categories.py --data /tmp/ecom-production-new --case headphones --spec docs/evidence/production-directions/case.json --music examples/client-demo/work/social/music-original.wav --live
.venv/bin/python scripts/accept_production_visual.py --data /tmp/ecom-production-new
.venv/bin/python scripts/publish_production_sample.py --data /tmp/ecom-production-new
.venv/bin/python scripts/check_production_sample.py
```

自动建议须回看；若需要人工校正，保留首次模型建议，再用 `--reviewed-ranges` 明确提供核对区间，不能把人工校正算作自动识别准确率。全部确认写在隔离库且标为 `AUTOMATED FIXTURE`，不是客户签收。不要将隔离验收库导入正式库冒充人工审核。

本轮耳机23.1秒实际成片、单句换声和首镜修改见 验收结果（历史记录或本机文件，未随公开版分发） 与 `/samples#productionExamples`。宽画幅素材保留完整商品会有竖屏留白，标题/焦点也要逐镜核对；“完整编排”不表示无需客户美术选择。

回退：保留新样片和制作记录后恢复本轮源码，重启原API/render/analysis三个进程；无需数据库降级，旧成片可继续播放。旧程序不能编辑新字段，勿将新分镜交给旧版本保存。
