# P3 接口来源与证据边界

核验日期：2026-10-14。官方 Go SDK 固定版本：[`oceanengine/ad_open_sdk_go@1907e5f46b1b138062ff017a2325c38787ed6bca`](https://github.com/oceanengine/ad_open_sdk_go/tree/1907e5f46b1b138062ff017a2325c38787ed6bca)。只参考接口与模型，未安装整个 SDK；下载文件摘要见 `evidence/p3/contract-files.json`。许可证留存 `third-party/oceanengine-sdk-LICENSE`。

| 功能 | 官方 HTTP 路径 | 已核对内容 |
|---|---|---|
| OAuth 换取/刷新 | `ad.oceanengine.com/open_api/oauth2/access_token/`、`refresh_token/` | POST JSON app_id/secret/auth_code 或 refresh_token |
| 广告主范围 | `ad.oceanengine.com/open_api/oauth2/advertiser/get/` | GET query access_token；list account_id/account_type/account_role/is_valid |
| 视频上传 | `api.oceanengine.com/open_api/2/file/video/ad/` | multipart video_file/MD5/advertiser_id/is_aigc；回执 video_id/material_id/video_cover_id/video_signature |
| 千川素材库 | `api.oceanengine.com/open_api/v1.0/qianchuan/video/get/` | video_ids 过滤、id/signature/material_id/image_mode |
| 全域短视频带货创建 | `api.oceanengine.com/open_api/v1.0/qianchuan/uni_aweme/ad/create/` | aweme_id/product_ids/delivery_setting/creative_setting/programmatic_creative_media_list；ad_id |
| 素材日报 | `api.oceanengine.com/open_api/v1.0/qianchuan/report/material/get/` | 日期、指标、分页、data.list/page_info |

普通 API OAuth 授权入口沿用固定版本 Ocean Watch 的千川授权实现：`https://qianchuan.jinritemai.com/openapi/qc/audit/oauth.html`，携带 app_id、redirect_uri、state、material_auth=1。

[巨量开放平台 2026-09-15 公告](https://open.oceanengine.com/changelog/1866779017215370)说明 2026-10-13 起营销 MCP 写入工具和 MCP 专用 APIKey/OAuth 配置变化，普通 API 仍可用。因此 P3 使用原生 HTTP API，不依赖 MCP 写入工具。P2 Ocean Watch 保持只读与独立凭据命名空间。

[千川视频库官方文档](https://open.oceanengine.com/labels/12/docs/1739309912219663)检索结果提示上传后存在分钟级同步延迟；页面正文受前端加载限制，具体字段以固定 SDK 源文件交叉核对。没有把抓不到正文的页面当作完整运行证明。

macOS 凭据实现使用 Apple [SecItemAdd](https://developer.apple.com/documentation/security/secitemadd(_:_:))、[SecItemCopyMatching](https://developer.apple.com/documentation/security/secitemcopymatching(_:_:))、SecItemUpdate、SecItemDelete。实机无敏感测试值 roundtrip 已验证；Linux Secret Service 只有代码路径和隔离单元测试，未在 Linux 实机联调。

所有平台返回值测试均为 fixture。当前没有真实平台账号、应用权限、回调策略、预算下限、商品/抖音号资格、媒体约束或全链路投放运行证明。原生授权成功也只证明当次授权与账户范围；`live_verified=false` 保留表示本项目未完成真实全链路验收。
