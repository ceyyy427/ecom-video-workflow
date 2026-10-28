import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


class Secrets:
    def __init__(self):
        self.values = {}

    def write(self, key, value):
        self.values[key] = value

    def read(self, key):
        return self.values.get(key, {})

    def delete(self, key):
        self.values.pop(key, None)


def test_oauth_state_is_once_only_and_secrets_never_enter_database(tmp_path, monkeypatch):
    from ecom_video.connectors.oauth import DouyinAuth
    from ecom_video.db import Store
    from ecom_video.operations.records import Records

    monkeypatch.setenv("ECOM_DOMESTIC_OFFICIAL_READ", "1")
    records = Records(tmp_path, Store(tmp_path / "workflow.db"))
    secrets = Secrets()
    seen = []

    def reply(req):
        seen.append(req)
        assert req.method == "POST" and req.url.path == "/oauth/access_token/"
        assert b"client_secret=VERY_PRIVATE" in req.content
        return httpx.Response(
            200,
            json={
                "data": {
                    "error_code": 0,
                    "access_token": "SECRET_TOKEN",
                    "open_id": "owned-id",
                    "scope": "video.data",
                    "expires_in": 86400,
                }
            },
        )

    auth = DouyinAuth(records, secrets=secrets, transport=httpx.MockTransport(reply))
    config = auth.configure(
        "app-123", "VERY_PRIVATE", "http://127.0.0.1:8793/api/operations/connectors/douyin/callback"
    )
    url = auth.begin(config["id"], confirmed=True)["url"]
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == ["video.data"]
    connection = auth.callback(params["state"][0], "temporary-code")
    with pytest.raises(ValueError):
        auth.callback(params["state"][0], "temporary-code")
    assert len(seen) == 1 and auth.grant(connection["id"]).open_id == "owned-id"
    raw = (tmp_path / "workflow.db").read_bytes()
    for secret in (
        b"SECRET_TOKEN",
        b"VERY_PRIVATE",
        b"temporary-code",
        params["state"][0].encode(),
    ):
        assert secret not in raw
    assert "SECRET_TOKEN" not in json.dumps(connection)
    auth.disconnect(connection["id"])
    with pytest.raises(ValueError):
        auth.grant(connection["id"])


def test_oauth_forbids_arbitrary_redirect_scope_and_disabled_live_reads(tmp_path):
    from ecom_video.connectors.oauth import DouyinAuth
    from ecom_video.db import Store
    from ecom_video.operations.records import Records

    auth = DouyinAuth(Records(tmp_path, Store(tmp_path / "workflow.db")), secrets=Secrets())
    for redirect in (
        "https://evil.test/callback",
        "http://127.0.0.1:8765/other",
        "http://user@localhost:8765/api/operations/connectors/douyin/callback",
    ):
        with pytest.raises(ValueError):
            auth.configure("app", "secret", redirect)
    config = auth.configure(
        "app", "secret", "http://127.0.0.1:8793/api/operations/connectors/douyin/callback"
    )
    with pytest.raises(ValueError):
        auth.begin(config["id"], confirmed=True)


def test_sources_bind_declared_owner_and_freeze_original_bytes(tmp_path):
    from ecom_video.connectors.xhs_import import add_account, freeze_source
    from ecom_video.db import Store
    from ecom_video.operations.records import Records

    records = Records(tmp_path, Store(tmp_path / "workflow.db"))
    account = add_account(records, "xiaohongshu", "工程账号", "fixture-owner")
    source = freeze_source(
        records,
        account["id"],
        b"content_id,views\nabc,0\n",
        "sample.csv",
        "AUTOMATED FIXTURE authorized export",
    )
    assert source["payload"]["ownership"] == "declared_not_api_verified"
    assert source["payload"]["account_ref"] == account["id"]
    with pytest.raises(ValueError):
        freeze_source(records, account["id"], b"x", "../../a.csv", "")
