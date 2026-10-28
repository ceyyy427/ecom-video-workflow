"""Official optional SDK in-memory contract smoke; never connects to a platform."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def check():
    from mcp import Client, types
    from mcp.server import Server

    from ecom_video.connectors.mcp_client import call_read

    schema = {
        "type": "object",
        "properties": {
            "account_id": {"type": "string"},
            "content_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["account_id", "content_ids"],
        "additionalProperties": False,
    }

    async def listing(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(name="video_data_read", inputSchema=schema)])

    async def calling(ctx, params):
        return types.CallToolResult(
            content=[],
            structuredContent={
                "account_id": params.arguments["account_id"],
                "rows": [],
                "fixture": True,
            },
        )

    server = Server(
        "domestic-read-fixture",
        on_list_tools=listing,
        on_call_tool=calling,
        get_tool_input_schema=lambda name: schema if name == "video_data_read" else None,
    )
    async with Client(server, read_timeout_seconds=30) as client:
        tool = (await client.list_tools()).tools[0].model_dump(by_alias=True, exclude_none=True)
        sha = hashlib.sha256(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = await call_read(
            client,
            tool,
            schema_sha256=sha,
            arguments={"account_id": "a" * 32, "content_ids": ["fixture"]},
            expected_account="a" * 32,
        )
        assert result["fixture"] is True
    return {
        "sdk": "mcp==2.3.0",
        "official_protocol": "in_memory",
        "passed": True,
        "platform_calls": 0,
        "platform_writes": 0,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(check())))
