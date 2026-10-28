"""Account capability evidence is separate from optional package availability."""


def connector_catalog():
    return [
        {
            "id": "douyin-official",
            "name": "抖音本人作品数据",
            "transport": "https",
            "status": "requires_approval",
            "dataset_kind": "organic",
            "scopes": ["video.data"],
            "platform_writes": False,
            "live_verified": False,
            "source": "https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/search-video/video-data/",
            "checked_at": "2026-10-28",
        },
        {
            "id": "douyin-import",
            "name": "抖音授权报表导入",
            "transport": "file",
            "status": "ready",
            "dataset_kind": "organic",
            "platform_writes": False,
        },
        {
            "id": "xhs-import",
            "name": "小红书授权报表导入",
            "transport": "file",
            "status": "ready",
            "dataset_kind": "organic",
            "platform_writes": False,
        },
        {
            "id": "xhs-note-api",
            "name": "小红书笔记数据API",
            "transport": "https",
            "status": "unavailable",
            "reason": "尚未取得可核验的通用笔记数据契约与账户权限",
            "platform_writes": False,
        },
        {
            "id": "xhs-browser-mcp",
            "name": "小红书浏览器MCP",
            "transport": "browser",
            "status": "disabled",
            "reason": "浏览器依赖；不导入Cookie，不暴露发布或互动工具",
            "repository": "xpzouying/xiaohongshu-mcp",
            "commit": "7797fd375aba02dcd33afe143f6bee13e5870859",
            "license": "Apache-2.0",
            "platform_writes": False,
        },
        {
            "id": "qianchuan-ad",
            "name": "千川广告复盘（原流程）",
            "transport": "existing",
            "status": "existing",
            "dataset_kind": "ad",
            "platform_writes": False,
            "path": "/distribution",
        },
    ]
