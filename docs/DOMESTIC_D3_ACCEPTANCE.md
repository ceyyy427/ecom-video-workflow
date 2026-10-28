# D3：只读连接器与发布交接

2026-10-28；**离线及协议模拟已验证，真实平台账户仍待实接**。没有自动发布、投放、评论、私信或调价接口。

| 能力 | 状态与依据 |
| --- | --- |
| 抖音本人公开作品计数 | 已适配固定只读 POST /video/data/，请求限定已登记的本人作品ID，最多10个；需要平台批准 video.data 且由本人授权。真实账号未取得，不宣称联调完成。返回实时累计量，未返回为未知。 |
| OAuth | 仅 video.data，官方固定域名，POST 表单换 token；state仅存哈希、10分钟有效、使用一次。Secret/token进入已有 OS Keychain，按安装目录隔离；不进入 SQLite、响应或交付包。结果不明不重放；过期请重新授权。 |
| 小红书 | 客户授权 UTF-8 CSV 导入可用；通用笔记数据API未验证，显示 unavailable。xpzouying 的浏览器 MCP 登记为 disabled，不导入Cookie。 |
| MCP | 官方 mcp==2.3.0，MIT，Python≥3.10；隔离 Python3.11环境61MiB，导入峰值RSS约65.4MiB。官方 Client/Server 内存协议实测通过；适配 v2 snake_case 响应，不自建协议栈。可选 connectors extra，不默认安装或启动服务。 |
| 交接包 | 绑定具体成片 SHA、输入快照与创意特征；包含视频、已有SRT/封面、待核对文案和操作清单。待审片明确待审；即使已审也只交客户手动发布。登记作品ID是人工声明映射，不是平台发布回执。 |
| n8n | 仅提供人工触发的本机快照 GET 示例，不安装、不常驻、不发布；其 Sustainable Use License 不作为本包代码许可。 |

官方依据：[抖音作品数据](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/video-data/)、[换取token](https://open.douyin.com/platform/resource/docs/openapi/account-permission/get-access-token)、[MCP官方发行](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0)。部分官方网页字段表为空，当前契约仍须用客户获批账户实测；如平台不允许本机 HTTP 回调，不放宽 loopback 边界，先用文件导入。

## 验证与证据

- tests/test_connectors_policy.py：伪造 readOnlyHint、变更schema、错账户、异常结构、缺失计数、302/401/429/500、不跳转、不重试、错误脱敏。
- tests/test_connectors_auth.py：固定作用域与地址、一次state、密钥不入库、断连、默认关闭；只用内存凭据与 MockTransport。
- tests/test_connectors_import.py：注册来源文件、备份恢复完整、篡改失败；schema016只新增运营对象/文件/state表。
- tests/test_operations_media_pack.py：待审包、版本SHA、映射确认、跨版本冲突和变动拒绝。
- 保留原 tests/test_qianchuan_api.py，不把自然数据塞进广告表。
- /Users/mac/Documents/ChatGPT/ecom-domestic-d3-20261028/sdk-smoke.json 是官方SDK实际内存协议结果；平台调用0。requirements-mcp.txt 与 uv.lock 均固定依赖，直接许可见第三方清单。

## 客户路径

内容运营 → 账户与只读连接设置 → 登记报表账户 → 视频交接包 → 客户手动发布 → 登记对应作品ID → 导入报表。Secret只在本机密码框输入，页面不回填；官方读取另需安装人员启用 ECOM_DOMESTIC_OFFICIAL_READ=1。

回调只接受 http://127.0.0.1:实际端口/api/operations/connectors/douyin/callback（或localhost）；须与控制台获准地址完全一致。不能保证平台允许该回调或个人账户获批。

## 回滚

ECOM_DOMESTIC_OFFICIAL_READ=0 关闭真实读取；页面可移除本机凭据，平台授权在抖音中另行撤销。ECOM_DOMESTIC_CONNECTIONS=0 / ECOM_DOMESTIC_HANDOFF=0 关闭新写入，历史可读、断连仍可用。恢复到新目录后重新配置授权，旧目录的凭据不复用。数据库不降版本，原广告复盘入口保留。
