"""Pinned optional official SDK, with local semantic/schema allowlists before calls."""

import asyncio
import hashlib
import importlib.metadata
import json

SDK_VERSION = "2.3.0"
READ_TOOLS = {"video_data_read"}


def sdk_status():
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return {
            "available": False,
            "expected_version": SDK_VERSION,
            "reason": "未安装可选官方MCP SDK；文件导入可继续使用",
        }
    return {
        "available": version == SDK_VERSION,
        "version": version,
        "expected_version": SDK_VERSION,
        "platform_writes": False,
    }


def validate_tool(tool, expected_name, schema_sha256):
    # Hints/descriptions are untrusted evidence, never permission.
    if expected_name not in READ_TOOLS or tool.get("name") != expected_name:
        raise ValueError("MCP工具不在本机只读语义白名单")
    raw = json.dumps(
        tool.get("inputSchema"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    if hashlib.sha256(raw.encode()).hexdigest() != schema_sha256:
        raise ValueError("MCP输入契约变化，须重新审阅")
    return True


async def call_read(session, tool, *, schema_sha256, arguments, expected_account):
    if not sdk_status()["available"]:
        raise ValueError("需要固定版本的官方MCP SDK")
    validate_tool(tool, "video_data_read", schema_sha256)
    if (
        set(arguments) != {"account_id", "content_ids"}
        or arguments["account_id"] != expected_account
    ):
        raise ValueError("MCP账户或参数不符")
    if (
        not isinstance(arguments["content_ids"], list)
        or not 1 <= len(arguments["content_ids"]) <= 20
    ):
        raise ValueError("MCP读取范围过大")
    # The caller supplies an SDK session bound to a reviewed fixed transport. No URL/command input.
    try:
        result = await asyncio.wait_for(session.call_tool("video_data_read", arguments), timeout=30)
    except (TimeoutError, OSError) as exc:
        raise ValueError("MCP读取超时或连接中断；未自动重试") from exc
    if getattr(result, "is_error", True):
        raise ValueError("MCP读取未完成")
    data = getattr(result, "structured_content", None)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
    if (
        len(raw.encode()) > 2 * 1024**2
        or not isinstance(data, dict)
        or data.get("account_id") != expected_account
    ):
        raise ValueError("MCP返回大小、结构或账户不符")
    return data
