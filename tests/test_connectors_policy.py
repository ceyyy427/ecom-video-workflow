import json

import httpx
import pytest


def test_catalog_does_not_turn_browser_mcp_or_write_hints_into_permission():
    from ecom_video.connectors.mcp_client import validate_tool
    from ecom_video.connectors.registry import connector_catalog

    rows = connector_catalog()
    assert next(r for r in rows if r["id"] == "xhs-browser-mcp")["status"] == "disabled"
    assert next(r for r in rows if r["id"] == "xhs-note-api")["status"] == "unavailable"
    assert all(not r["platform_writes"] for r in rows)
    with pytest.raises(ValueError):
        validate_tool(
            {"name": "publish_note", "inputSchema": {}, "annotations": {"readOnlyHint": True}},
            "video_data_read",
            "0" * 64,
        )
    with pytest.raises(ValueError):
        validate_tool(
            {"name": "video_data_read", "inputSchema": {"additionalProperties": True}},
            "video_data_read",
            "0" * 64,
        )


def test_official_sdk_v2_structured_result_is_read_with_bound_account(monkeypatch):
    import asyncio
    import hashlib
    from types import SimpleNamespace

    import ecom_video.connectors.mcp_client as adapter

    monkeypatch.setattr(adapter, "sdk_status", lambda: {"available": True})
    schema = {"type": "object", "additionalProperties": False}
    sha = hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    class Session:
        async def call_tool(self, name, arguments, **kwargs):
            return SimpleNamespace(
                is_error=False,
                structured_content={"account_id": arguments["account_id"], "rows": []},
            )

    result = asyncio.run(
        adapter.call_read(
            Session(),
            {"name": "video_data_read", "inputSchema": schema},
            schema_sha256=sha,
            arguments={"account_id": "a" * 32, "content_ids": ["id"]},
            expected_account="a" * 32,
        )
    )
    assert result["rows"] == []


def test_official_read_uses_fixed_post_contract_and_keeps_missing_unknown():
    from ecom_video.connectors.douyin_readonly import DouyinReadOnly, ReadGrant

    seen = []

    def response(req):
        seen.append(req)
        assert req.url.host == "open.douyin.com" and req.url.path == "/video/data/"
        assert req.method == "POST" and req.url.params["open_id"] == "owner"
        assert json.loads(req.content) == {"item_ids": ["item-1"]}
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 0,
                    "list": [
                        {"item_id": "item-1", "statistics": {"play_count": 0, "digg_count": 3}}
                    ],
                },
                "extra": {"logid": "safe-log"},
            },
        )

    grant = ReadGrant(
        account_id="a" * 32,
        open_id="owner",
        token="DO_NOT_EXPOSE_TOKEN",
        scopes=["video.data"],
        expires_at=9999999999,
    )
    result = DouyinReadOnly(transport=httpx.MockTransport(response)).read(grant, ["item-1"])
    assert len(seen) == 1
    assert result["rows"][0]["values"]["views"] == "0"
    assert result["rows"][0]["values"]["shares"] is None
    assert result["counting"] == "cumulative" and result["dataset_kind"] == "organic"
    assert "DO_NOT_EXPOSE_TOKEN" not in json.dumps(result)


@pytest.mark.parametrize("payload", [[], {"data": None}, {"data": {"error_code": 0, "list": [None]}},
    {"data": {"error_code": 0, "list": [{"item_id": "id", "statistics": "private provider message"}]}}])
def test_malformed_official_response_has_safe_structured_failure(payload):
    from ecom_video.connectors.douyin_readonly import DouyinReadOnly, ProviderProblem, ReadGrant
    grant=ReadGrant(account_id="a"*32,open_id="owner",token="private-token",scopes=["video.data"],expires_at=9999999999)
    with pytest.raises(ProviderProblem) as error:
        DouyinReadOnly(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))).read(grant,["id"])
    assert "private" not in str(error.value)


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_error_no_redirect_or_automatic_retry_or_secret_leak(status):
    from ecom_video.connectors.douyin_readonly import DouyinReadOnly, ProviderProblem, ReadGrant

    calls = []

    def response(req):
        calls.append(req)
        return httpx.Response(
            status, headers={"Location": "https://attacker.test/"}, text="secret-token"
        )

    grant = ReadGrant(
        account_id="a" * 32,
        open_id="owner",
        token="secret-token",
        scopes=["video.data"],
        expires_at=9999999999,
    )
    with pytest.raises(ProviderProblem) as error:
        DouyinReadOnly(transport=httpx.MockTransport(response)).read(grant, ["id"])
    assert len(calls) == 1 and "secret-token" not in str(error.value)
    grant.scopes = []
    with pytest.raises(ProviderProblem):
        DouyinReadOnly(transport=httpx.MockTransport(response)).read(grant, ["id"])
    assert len(calls) == 1
