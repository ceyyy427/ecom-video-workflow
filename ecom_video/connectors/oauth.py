"""Narrow Douyin own-public-video OAuth. Secrets use the existing OS keychain.

Opt-in, fixed scope/domain and one-use state. No publish scope or browser automation.
"""

import hashlib
import os
import re
import secrets as random_secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx

from ..platforms.secret_store import SecretStore, credential_lock
from .douyin_readonly import ReadGrant

CALLBACK = "/api/operations/connectors/douyin/callback"


def enabled():
    return os.getenv("ECOM_DOMESTIC_OFFICIAL_READ", "0") == "1"


def redirect_uri(value):
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost")
        or url.username
        or url.password
        or not url.port
        or url.path != CALLBACK
        or url.query
        or url.fragment
    ):
        raise ValueError("回调须为本机固定路径 http://127.0.0.1:端口" + CALLBACK)
    return value


class DouyinAuth:
    def __init__(self, records, *, secrets=None, transport=None):
        self.records = records
        self.secrets = secrets if secrets is not None else SecretStore(records.root)
        self.transport = transport

    def configure(self, client_key, client_secret, callback):
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_key)
            or not 1 <= len(client_secret) <= 4096
        ):
            raise ValueError("应用配置无效；Secret仅保存在系统钥匙串")
        config = self.records.put(
            "oauth_config",
            {
                "platform": "douyin",
                "client_key": client_key,
                "callback": redirect_uri(callback),
                "scope": "video.data",
                "platform_writes": False,
            },
        )
        with credential_lock(self.records.root / "integrations/domestic"):
            self.secrets.write("dy-config-" + config["id"], {"client_secret": client_secret})
        return config

    def begin(self, config_id, *, confirmed):
        if not enabled() or confirmed is not True:
            raise ValueError("请明确启用本人作品只读授权，并确认应用已获批video.data权限")
        config = self.records.get(config_id, "oauth_config")["payload"]
        if not self.secrets.read("dy-config-" + config_id).get("client_secret"):
            raise ValueError("本安装目录没有应用密钥；恢复或换目录后须重新配置")
        state = random_secrets.token_urlsafe(32)
        with self.records.store.transaction() as c:
            c.execute(
                "INSERT INTO operation_oauth_states VALUES(?,?,'pending',?,?)",
                (
                    hashlib.sha256(state.encode()).hexdigest(),
                    config_id,
                    time.time() + 600,
                    time.time(),
                ),
            )
        return {
            "url": "https://open.douyin.com/platform/oauth/connect/?"
            + urlencode(
                {
                    "client_key": config["client_key"],
                    "response_type": "code",
                    "scope": "video.data",
                    "redirect_uri": config["callback"],
                    "state": state,
                }
            ),
            "expires_in": 600,
            "note": "在平台页面由本人登录授权；若平台不接受本机回调，使用报表导入，勿关闭本机边界",
        }

    def callback(self, state, code):
        if (
            not enabled()
            or not isinstance(state, str)
            or not 32 <= len(state) <= 128
            or not 1 <= len(code) <= 2048
        ):
            raise ValueError("授权未启用或回调无效")
        sha = hashlib.sha256(state.encode()).hexdigest()
        with credential_lock(self.records.root / "integrations/domestic"):
            with self.records.store.transaction() as c:
                row = c.execute(
                    "SELECT * FROM operation_oauth_states WHERE state_hash=?", (sha,)
                ).fetchone()
                if not row or row["status"] != "pending" or row["expires_at"] <= time.time():
                    raise ValueError("授权状态已过期或已使用，请重新开始授权")
                # Consume BEFORE the network; ambiguous token outcomes are never replayed.
                c.execute(
                    "UPDATE operation_oauth_states SET status='consumed' WHERE state_hash=?", (sha,)
                )
            config_id = row["config_id"]
            config = self.records.get(config_id, "oauth_config")["payload"]
            secret = self.secrets.read("dy-config-" + config_id).get("client_secret")
            if not secret:
                raise ValueError("此安装没有应用密钥，请重新配置并授权")
            try:
                with (
                    httpx.Client(
                        transport=self.transport,
                        trust_env=False,
                        follow_redirects=False,
                        timeout=20,
                    ) as client,
                    client.stream(
                        "POST",
                        "https://open.douyin.com/oauth/access_token/",
                        data={
                            "client_key": config["client_key"],
                            "client_secret": secret,
                            "code": code,
                            "grant_type": "authorization_code",
                        },
                    ) as response,
                ):
                    if response.status_code != 200:
                        raise ValueError()
                    raw = bytearray()
                    started = time.monotonic()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65536 or time.monotonic() - started > 20:
                            raise ValueError()
                import json

                data = json.loads(raw)["data"]
                if str(data.get("error_code")) != "0" or "video.data" not in str(
                    data.get("scope", "")
                ).split(","):
                    raise ValueError()
                owner = data["open_id"]
                ttl = int(data["expires_in"])
                if (
                    not isinstance(owner, str)
                    or not 1 <= len(owner) <= 256
                    or not 0 < ttl <= 366 * 86400
                ):
                    raise ValueError()
                account = self.records.put(
                    "connection",
                    {
                        "platform": "douyin",
                        "transport": "official",
                        "name": "抖音本人作品",
                        "owner_sha256": hashlib.sha256((config_id + owner).encode()).hexdigest(),
                        "config_ref": config_id,
                        "scope": "video.data",
                        "ownership": "oauth_verified_owner",
                        "platform_writes": False,
                    },
                )
                grant = ReadGrant(
                    account_id=account["id"],
                    open_id=owner,
                    token=data["access_token"],
                    scopes=["video.data"],
                    expires_at=time.time() + ttl,
                )
                self.secrets.write(
                    "dy-" + account["id"],
                    {
                        "open_id": grant.open_id,
                        "token": grant.token.get_secret_value(),
                        "expires_at": grant.expires_at,
                        "scopes": grant.scopes,
                    },
                )
                return account
            except (ValueError, KeyError, TypeError, httpx.HTTPError):
                raise ValueError(
                    "授权未完成；请检查应用权限后重新授权，不自动重试，不回显平台响应或凭据"
                ) from None

    def grant(self, account_id):
        account = self.records.get(account_id, "connection")["payload"]
        if not enabled() or account.get("ownership") != "oauth_verified_owner":
            raise ValueError("需要本安装内有效的本人授权")
        data = self.secrets.read("dy-" + account_id)
        if not data or data.get("expires_at", 0) <= time.time():
            raise ValueError("未连接或授权已过期，请重新授权；未自动刷新或重试")
        return ReadGrant(account_id=account_id, **data)

    def disconnect(self, account_id):
        self.records.get(account_id, "connection")
        with credential_lock(self.records.root / "integrations/domestic"):
            self.secrets.delete("dy-" + account_id)
        return {
            "disconnected": True,
            "local_only": True,
            "note": "本机凭据已删除；平台授权可另在抖音管理中撤销",
        }
