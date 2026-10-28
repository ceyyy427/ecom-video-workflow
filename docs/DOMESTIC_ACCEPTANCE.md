# 国内运营套件 0.18.0 · Mac 候选交付验收

2026-10-28，分支 `codex/domestic-suite`。状态：工程候选，真实账号、客户听审与发布仍待处理。不把自动测试夹具当作客户审批；本轮不使用 Computer Use、不自动发布或投放。

## 交付内容与入口

保留原UI和客户制作入口，新增 `/operations` 七模块：市场资料、商品定位、内容方案、封面图文、视频交接、表现复盘、评论与迭代。六个7秒真实静音方向在 `/ideas`，采用后回到 `/create`，原事实/文稿/风格/听核/最终分镜/逐镜及整片审核继续有效。

使用步骤见 [Mac指南](MAC_WORKBENCH_GUIDE.md)及[国内运营指南](DOMESTIC_SUITE_GUIDE.md)；范围见[能力矩阵](DOMESTIC_CAPABILITY_MATRIX.md)。最终完整包与0.17.1过渡包均为本地候选，不上传GitHub Release，不合并或覆盖原生产目录。最终包SHA单列于交付目录的SHA256SUMS.txt，不使用较早预审包的SHA。

## 实测环境与结果

Apple M2／8GiB、macOS26.5.2。全新中文带空格目录、独立Python环境与node_modules，已有系统工具及下载缓存；未冒称无缓存网络首次下载。

| 验收 | 实际覆盖 |
| --- | --- |
| 一键启动 | 实际双击入口的等效命令执行，安装锁依赖及渲染浏览器后本机页面就绪；观测11.18秒。模型不随包附带 |
| 首次配置 | 固定P5字幕权重从已有本机缓存导入，安装目录及SHA核验；页面“安装/校验”确认已有权重，无额外下载。模型下载取消可用；未修改原生产模型或配置 |
| 声音 | 独立VoiceStudio固定Kokoro模型实际生成5.775秒工程测试音频，用时4.395秒；不是自然度听核。无新增火山/付费调用，应用及权重不打包 |
| 藏蓝完整制作 | 实际上传资料、8段单色实拍、既有配音和音乐→本机ASR→回放旧工程时间校正→原分镜编辑/确认→27.8秒成片。没有新的VLM推理或客户签收 |
| 单镜修改 | 藏蓝第一镜改字卡后，只重渲1镜，其他5镜SHA、解码PCM、SRT保持不变；父片与子片均待审 |
| 两品类原生链路 | 实际六方向方案采用→既有有界Runtime→最终分镜关卡→26秒成片→逐镜修改→恢复→待审交接包；真实动作素材，非图片轮播占位。原生链路为静音商品展示 |
| 六条有声工程回归 | 藏蓝21/24.1/21秒、许可鲜橙26.5/26.5/26.5秒；三种样式，旧配音和动作保护重放。新作品全部待审，不继承客户成片认可 |
| 数据与迭代 | 安装副本中两品类实际导出交接、登记工程作品、导入、冻结、评论候选、假设选择、待确认下一版及不可比原因；数值为明确标记的合成工程数据，真实下一轮数据待补 |
| 页面 | 实际安装副本1440/768/390宽度、七模块/键盘/真实市场表单、缺失与零、密钥不回填；页面错误、失败API、外部请求及审批请求均0 |
| 备份恢复 | 实际页面API创建/下载/校验/恢复藏蓝备份；56表、58个登记业务文件完全一致，新目录可运行，旧数据未覆盖。缓存与临时文件不属于业务备份 |
| 旧版升级 | 固定0.17.0源码的旧加载器实际接受0.17.1过渡包，再由过渡副本准备0.18.0完整包；每步先备份，383个原业务文件保留，全部准备于新目录，未自动启用 |
| 历史兼容 | 从真实生产库只读SQLite备份到外部目录后迁移14→16；49张既有业务表内容完全相同（迁移登记表按设计增2行），真实历史审批未改写，未添加审批 |

工程确认统一标记 `AUTOMATED FIXTURE`；只出现在专用副本，不是客户实际听审。字幕模型固定SHA、声音及成片SHA随各验收JSON留存。

## 性能与采用依据

复用原Runtime、Worker、Remotion、FFmpeg、Pillow、SQLite备份/增量迁移和OS钥匙串。国内方法包35份MIT文本固定到Fork本地候选提交，运行时不更新或执行上游脚本。官方MCP SDK2.3.0在隔离环境做Client/Server内存协议验证，作为可选依赖；导入峰值约65.4MiB、环境约61MiB，不默认安装。n8n及浏览器MCP不运行。

三轮交错渲染：Agent冷次中位106.596秒、固定工作流108.329秒；单镜暖次25.552／23.425秒。没有稳定的整体优势，不切默认后端。本轮不改变视觉识别后端，不与五段首次识别21.04分钟比较，不降低同款、主体可见或动作完整性门槛。详细数据见[D2验收](DOMESTIC_D2_ACCEPTANCE.md)。

## 自动回归

最终复核前全量Python：**1107通过、4跳过、1排除**，248.05秒。跳过为未随公开源码分发的私有旧证据1项、Windows原生DPAPI/Job Object2项、需明确启用的系统钥匙串集成1项；排除的浏览器焦点布局用例不在本轮非CU集合中。另有本机页面隔离回归，不能把这些未运行项称为通过。

Node **50通过**，TypeScript及Ruff通过；官方MCP SDK内存协议复核通过。全量首轮发现4处旧测试版本/模拟旧库前提过时，修正后旧任务/历史审批断言仍保留；另外通过失败测试补齐发行指南引用文档，打包/恢复31项通过。完整日志保留于D6证据目录。最终独立只读复核及其后修复另行记录，不把本段当作已完成真人验收。

## 可执行复核

在源码候选分支运行：

```sh
uv run pytest -q -rs -k 'not test_focus_frame_contains_requested_media_point_in_actual_browser_layout'
node --test tests/web/*.test.cjs
render/remotion/node_modules/.bin/tsc --noEmit -p render/remotion/tsconfig.json
uv run ruff check ecom_video scripts tests
```

重放工程制作时使用仓库外全新目录，显式 `--simulate-confirmations`；禁止对真实客户数据使用该选项：

```sh
python scripts/accept_delivery_upgrade1.py --application ABS_APP --workspace ABS_NEW_DIR --case ABS_CASE_JSON --stage intake --simulate-confirmations
# intake成功后依次将stage换为 produce、retake、verify；失败时先读日志，不自动跳步。
python scripts/accept_domestic_workbench.py --application ABS_APP --bundle ABS_ENGINEERING_BACKUP --workspace ABS_NEW_DIR --simulate-confirmations
python scripts/accept_domestic_suite.py --stage mac --workspace ABS_NEW_DIR --manifest ABS_MANIFEST_JSON --mode customer
```

完整证据保存在本机 `ecom-domestic-d1-20261028` 至 `ecom-domestic-d6-20261028` 专用目录。D6包含 first-launch.json、asr-page-check.json、customer-flow/acceptance.json、native-workbench/acceptance.json、mac-operations/acceptance.json、first-run-ui/ui-final/acceptance.json、navy-backup-restore-final.json、legacy-bridge-check.json、bridge-to-full-check.json、legacy-db-migration/acceptance.json及各回归日志。早期失败的配置/验收尝试保留，未混入通过结果。

## 发布前仍待完成

- 用户实际核对新版两品类方向和作品，逐版完成事实、文稿、风格、听核与成片审核；工程签名不转为真人签名。
- 抖音应用实际获批video.data并验证本机回调、账户和只读结果；未接账号时使用授权文件导入。小红书通用笔记API仍 unavailable。
- 提供真实评论和下一轮报表后，才判断期间/指标是否可比；当前不宣称真实运营效果或因果结论。
- Windows原生另机验证，不在本轮Mac验收结论中；第三方音色、媒体及Remotion的客户使用范围分别核对。
- 最终由用户验收并发布；本地Fork方法候选和应用候选均不推送。

## 回滚

未迁移生产安装，可直接继续使用原目录。旧0.17用户先过渡包、再完整包，每步页面自动先备份且保留独立应用/数据目录。关闭新版，从升级前旧应用及旧数据副本启动；禁止旧程序打开schema16数据库、改版本号或合并数据库。新目录须保留，以免丢失升级后新项目。

只停用新功能可设 `ECOM_DOMESTIC_EXECUTION=0`，各运营写模块按指南独立关闭；原制作入口和历史仍可读。撤销连接只清本机钥匙串，平台侧授权另行撤销。备份不含模型、凭据或可重建渲染缓存，恢复后重新检查配置。
