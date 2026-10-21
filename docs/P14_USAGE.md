# P14：本机自动制作与人工确认

P14 把现有素材识别、自动选段、准备分镜和渲染串起来；没有新增云服务、平台写入或 P15 复盘功能。仍由人核对事实、确认文稿、选择风格、听核配音和审核成片。

## 在制作页使用

启动维护者进程时明确打开两个开关，勿把密钥写进命令：

```sh
ECOM_AGENT_ENABLED=1 ECOM_AGENT_EXECUTION_ENABLED=1 .venv/bin/python -m ecom_video --data var
```

在 `/create` 上传资料、图片/实拍和成品配音，确认事实与文稿；需要自动选段时保存相应制作要求。选定三个推荐方向之一，在页面下方“自动制作”填写风格确认人，勾选确认，再设置步骤、时限与本机模型调用上限并启动。纯商品展示可无配音。

自动流程会读取或排队识别、冻结素材版本、准备本机配音对齐，在听核处暂停。逐句试听、必要时校正字级时间，填写听核人并勾选后，点击“确认后恢复”：先保存听核，再由 Agent 选段、写分镜和提交渲染。不要使用旧的“生成分镜”按钮接管同一个活动执行。

成片停在 `needs_review`，执行记录为 `waiting_human/film_review`。完整观看并使用原页面人工审核；只有人工审核通过才会成为 ready，Agent 随后记录 completed。自动完成编码不等于事实正确或审核通过。

## 暂停、恢复、取消与修改

- 暂停阻止新步骤；已派发的本机子任务可在原预算内完成。暂停时不会撤销已确认资料或删除产物。
- 恢复继续原计划，不重置预算；已存在回执的步骤不会重复创建子任务。没有回执但已预留推理调用的中断步骤进入 unknown，不自动重发。
- 取消撤销本次新建且拥有的识别、对齐和制作任务。复用的原任务继续保留，需通过原页面单独管理；取消不删除已生成成片或原审批。
- 更换资料、改稿、修改素材/制作要求或手工编辑分镜会使旧计划失效。保留修改及旧产物，重新提案并确认相关输入；系统不会用旧审批覆盖新输入。只读状态轮询不会重画未变的听核输入。
- 缺少事实/文稿确认时会等待，不代签。确认改变了输入版本后应创建新计划；缺配音时只等待上传，不自动调用火山语音。

总时限是从 execute 开始的墙钟时间，包含暂停和人工等待；到期停止继续派发并撤销本次拥有的活动子任务。已发出的本机推理可能等待本次响应/超时后才释放资源，取消后不会提交其分镜结果。需要更长时限时重新提案，不能通过恢复续期。

## 契约与 CLI/API

默认 `ECOM_AGENT_EXECUTION_ENABLED` 关闭。关闭时 P13 四个读取工具继续可用；开启后目录增加 `project.produce` 及策略、控制、人工风格确认的 JSON Schema。所有公共命令不接受 Shell、任意工具、供应商 URL、凭据或代签字段。

用现有项目接口读取 `revision` 与 `product.revision`，将下例实际 ID 和版本填入 `produce.json`：

```json
{"schema_version":1,"request_id":"production-001","operation":"project.produce","input":{"project_id":"00000000000000000000000000000000","expected_revision":0,"expected_product_revision":0,"policy":{"policy_id":"local-v1","max_steps":40,"max_elapsed_s":3600,"max_model_calls":120,"max_cost_cny":"0"}}}
```

限额：步骤 1–80、时限 30–14400 秒、本机推理 0–500 次，云费用必须为字符串 `"0"`。资源等待和状态轮询不消耗步骤；实际派发与安全重试消耗步骤。推理发出前预留一次调用，结果不明也不退还；本机 ASR 计一次，模型元数据查询不计推理。复用已存在任务的调用不纳入本次新派发预算。

```sh
export ECOM_AGENT_ENABLED=1 ECOM_AGENT_EXECUTION_ENABLED=1
.venv/bin/python -m ecom_video.agent_cli --data var run --input produce.json
.venv/bin/python -m ecom_video.agent_cli --data var inspect RUN_ID
.venv/bin/python -m ecom_video.agent_cli --data var style RUN_ID --input style.json
.venv/bin/python -m ecom_video.agent_cli --data var execute RUN_ID --input control.json
.venv/bin/python -m ecom_video.agent_cli --data var pause RUN_ID --input control.json
.venv/bin/python -m ecom_video.agent_cli --data var resume RUN_ID --input control.json
.venv/bin/python -m ecom_video.agent_cli --data var cancel RUN_ID --input control.json
.venv/bin/python -m ecom_video.agent_cli --data var events RUN_ID --after-seq 0
```

`control.json` 为 `{"revision":当前执行版本,"plan_hash":"提案返回的64位哈希","policy_id":"local-v1"}`；每次操作前 inspect 读取当前执行版本，不能使用客户项目版本替代。
`style.json` 在上述控制字段上增加 `style_id`（cinema/social/lab）、当前 `direction_basis`、`reviewer` 与 `confirmed:true`。风格是明确人工操作，不是可自动运行的模型工具。

HTTP 对应 `POST /api/agent/runs`、`POST /api/agent/runs/{id}/style|execute|pause|resume|cancel`；查询 `GET /api/agent/runs/{id}/execution` 与 `GET /api/agent/executions?project_id=...`。写操作沿用会话令牌与同源边界，CLI 沿用本机文件权限。P13 `GET runs/{id}` 仍返回原始不可变提案，执行状态由 `/execution` 查询。

新增稳定错误：BUDGET_EXCEEDED、DEADLINE_EXCEEDED、LOCAL_TASK_FAILED、OUTCOME_UNKNOWN；输入版本冲突仍为 STALE_INPUT。错误不公开原始堆栈或模型输入，详细剪辑诊断仍在既有领域页面。

## 资源、迁移与回退

同一数据目录的识别、对齐、选段和渲染共享 SQLite 计算租约；领取、续租和提交均核对 token。只协调本项目进程，不接管外部 Ollama 使用者或别的数据目录。当前固定执行图可审计，不是任意自主工具 Agent。

schema v10 新增执行/步骤/回执/人工风格/资源租约表，扩展事件类型并保留原 seq；旧 P13 提案、视频快照和审批不重写。升级前停机备份。关闭执行开关并重启新版会停止新领取，保留记录与原工作台；已停止服务的任务不会凭空完成。硬回退须恢复匹配 v9 的备份与源码，不修改 user_version。

验收与已知限制见 P14_ACCEPTANCE.md（历史记录或本机文件，未随公开版分发）。
