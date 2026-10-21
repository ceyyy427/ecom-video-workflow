"""OAuth sessions, direct advertiser binding, and fenced refresh-token rotation."""

import hashlib
import json
import os
import re
import secrets
import time
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlparse

from .db import Conflict
from .distribution import Distribution, encode
from .platforms.qianchuan_http import QianchuanHTTP, platform_id
from .platforms.secret_store import SecretStore, credential_lock

CALLBACK = "/api/qianchuan/oauth/callback"
AUTHORIZE = "https://qianchuan.jinritemai.com/openapi/qc/audit/oauth.html"


class QianchuanAuth:
    def __init__(self, root, store, secrets=None, provider=None):
        self.root = Path(root).resolve()
        self.home = self.root / "integrations" / "qianchuan"
        self.path = self.home / "config.json"
        self.store = store
        self.secrets = secrets if secrets is not None else SecretStore(root)
        self.provider = provider if provider is not None else QianchuanHTTP()
        self.distribution = Distribution(root, store)

    def configure(self, app_id, secret, redirect_uri, max_budget):
        app_id = platform_id(app_id)
        if (
            not isinstance(secret, str)
            or not 1 <= len(secret) <= 4096
            or any(ord(c) < 32 for c in secret)
        ):
            raise ValueError("应用 Secret 无效")
        url = urlparse(redirect_uri)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.path != CALLBACK
            or url.query
            or url.fragment
            or url.username
            or url.password
            or not url.port
        ):
            raise ValueError("回调须为 http://127.0.0.1:<端口>/api/qianchuan/oauth/callback")
        from .reporting import number

        maximum = number(max_budget, money=True)
        if maximum is None or not Decimal("0") < Decimal(maximum) <= Decimal("1000000"):
            raise ValueError("每计划 budget 参数上限须大于 0，且不超过 1000000 元")
        with credential_lock(self.home):
            revision = uuid.uuid4().hex
            self.secrets.write("app-" + revision, {"app_id": app_id, "secret": secret})
            config = {
                "app_id": app_id,
                "revision": revision,
                "redirect_uri": redirect_uri,
                "max_budget": maximum,
                "secret_ref": "app-" + revision,
            }
            temp = self.path.with_suffix(".tmp")
            temp.write_text(encode(config), encoding="utf-8")
            temp.chmod(0o600)
            temp.replace(self.path)
            with self.store.transaction() as c:
                c.execute(
                    "UPDATE qianchuan_grants SET status='reauthorize',updated_at=?", (time.time(),)
                )
        return self.config()

    def config(self):
        if not self.path.is_file():
            raise Conflict("尚未配置千川应用；请运行本地 qianchuan_setup.py")
        try:
            config = json.loads(self.path.read_text(encoding="utf-8"))
            platform_id(config["app_id"])
            if (
                not re.fullmatch(r"[0-9a-f]{32}", config["revision"])
                or config["secret_ref"] != "app-" + config["revision"]
            ):
                raise ValueError()
            url = urlparse(config["redirect_uri"])
            if (
                url.scheme != "http"
                or url.hostname != "127.0.0.1"
                or url.path != CALLBACK
                or url.query
                or url.fragment
                or url.username
                or url.password
                or not url.port
            ):
                raise ValueError()
            from .reporting import number

            maximum = number(config["max_budget"], money=True)
            if maximum is None or not Decimal("0") < Decimal(maximum) <= Decimal("1000000"):
                raise ValueError()
            return config
        except (ValueError, KeyError, TypeError):
            raise Conflict("应用配置格式无效，请重新运行配置工具") from None

    def writes_enabled(self):
        return os.getenv("ECOM_QIANCHUAN_WRITES") == "1"

    def grant(self, aid):
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM qianchuan_grants WHERE account_id=?", (aid,)).fetchone()
        if not row:
            raise Conflict("该广告主尚未完成千川原生授权")
        return dict(row)

    def status(self, aid):
        account = self.distribution.account(aid)
        configured = self.path.is_file()
        base = {
            "configured": configured,
            "secure_store_available": self.secrets.available(),
            "writes_enabled": self.writes_enabled(),
            "live_verified": False,
            "account_id": aid,
            "advertiser_id": account["advertiser_id"],
            "status": "unconfigured" if not configured else "unauthorized",
        }
        if not configured:
            return base
        config = self.config()
        base.update(
            {
                "app_id": config["app_id"],
                "redirect_uri": config["redirect_uri"],
                "max_budget": config["max_budget"],
            }
        )
        try:
            grant = self.grant(aid)
        except Conflict:
            return base
        status = grant["status"]
        if (
            grant["config_revision"] != config["revision"]
            or grant["refresh_expires_at"] <= time.time()
            or status == "refreshing"
        ):
            status = "reauthorize"
        base.update(
            {
                "status": status,
                "authorization_id": grant["id"],
                "access_expires_at": grant["access_expires_at"],
                "refresh_expires_at": grant["refresh_expires_at"],
                "verified_at": grant["verified_at"],
            }
        )
        return base

    def start(self, aid):
        account = self.distribution.account(aid)
        if account["platform"] != "qianchuan":
            raise ValueError("原生授权仅支持巨量千川")
        config = self.config()
        state = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(state.encode()).hexdigest()
        now = time.time()
        with self.store.transaction() as c:
            c.execute(
                "INSERT INTO qianchuan_oauth_sessions VALUES(?,?,?,?,?,?)",
                (hashed, aid, config["revision"], now + 600, None, now),
            )
        return {
            "url": AUTHORIZE
            + "?"
            + urlencode(
                {
                    "app_id": config["app_id"],
                    "redirect_uri": config["redirect_uri"],
                    "state": state,
                    "material_auth": "1",
                }
            ),
            "expires_at": now + 600,
        }

    def callback(self, state, code):
        if (
            not isinstance(state, str)
            or not 20 <= len(state) <= 100
            or not isinstance(code, str)
            or not 1 <= len(code) <= 4096
        ):
            raise Conflict("授权回调无效或已过期")
        hashed = hashlib.sha256(state.encode()).hexdigest()
        with credential_lock(self.home):
            config = self.config()
            with self.store.transaction() as c:
                row = c.execute(
                    "SELECT * FROM qianchuan_oauth_sessions WHERE state_hash=?", (hashed,)
                ).fetchone()
                if (
                    not row
                    or row["consumed_at"]
                    or row["expires_at"] <= time.time()
                    or row["config_revision"] != config["revision"]
                ):
                    raise Conflict("授权回调无效、已使用或已过期")
                c.execute(
                    "UPDATE qianchuan_oauth_sessions SET consumed_at=? WHERE state_hash=?",
                    (time.time(), hashed),
                )
                aid = row["account_id"]
            app = self.secrets.read(config["secret_ref"])
            token = self.provider.exchange(config["app_id"], app["secret"], code)
            account = self.distribution.account(aid)
            if not self.provider.authorized(token["access_token"], account["advertiser_id"]):
                raise Conflict("授权中未找到该直接广告主，或授权无效；请选择正确广告主重新授权")
            gid = uuid.uuid4().hex
            ref = "grant-" + gid
            now = time.time()
            secure = self._secure_token(token, now)
            self.secrets.write(ref, secure)
            with self.store.transaction() as c:
                c.execute(
                    "INSERT INTO qianchuan_grants VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET id=excluded.id,config_revision=excluded.config_revision,secret_ref=excluded.secret_ref,status=excluded.status,access_expires_at=excluded.access_expires_at,refresh_expires_at=excluded.refresh_expires_at,verified_at=excluded.verified_at,updated_at=excluded.updated_at",
                    (
                        aid,
                        gid,
                        config["revision"],
                        ref,
                        "authorized",
                        secure["expires_at"],
                        secure["refresh_expires_at"],
                        now,
                        now,
                        now,
                    ),
                )
        return self.status(aid)

    @staticmethod
    def _secure_token(token, now):
        return {
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "expires_at": now + token["expires_in"],
            "refresh_expires_at": now + token["refresh_token_expires_in"],
        }

    def token(self, aid):
        with credential_lock(self.home):
            config = self.config()
            grant = self.grant(aid)
            if grant["status"] != "authorized" or grant["config_revision"] != config["revision"]:
                raise Conflict("授权无效或刷新结果不明，请重新授权")
            token = self.secrets.read(grant["secret_ref"])
            if not token or token.get("refresh_expires_at", 0) <= time.time():
                raise Conflict("授权已过期，请重新授权")
            if token.get("expires_at", 0) > time.time() + 120:
                return token["access_token"]
            # Persist before network: a crash during rotating refresh never reuses old refresh token.
            with self.store.transaction() as c:
                c.execute(
                    "UPDATE qianchuan_grants SET status='refreshing',updated_at=? WHERE account_id=?",
                    (time.time(), aid),
                )
            try:
                app = self.secrets.read(config["secret_ref"])
                refreshed = self.provider.refresh(
                    config["app_id"], app["secret"], token["refresh_token"]
                )
                secure = self._secure_token(refreshed, time.time())
                self.secrets.write(grant["secret_ref"], secure)
                with self.store.transaction() as c:
                    c.execute(
                        "UPDATE qianchuan_grants SET status='authorized',access_expires_at=?,refresh_expires_at=?,updated_at=? WHERE account_id=?",
                        (secure["expires_at"], secure["refresh_expires_at"], time.time(), aid),
                    )
                return secure["access_token"]
            except Exception:
                with self.store.transaction() as c:
                    c.execute(
                        "UPDATE qianchuan_grants SET status='reauthorize',updated_at=? WHERE account_id=?",
                        (time.time(), aid),
                    )
                raise

    def verify(self, aid):
        token = self.token(aid)
        if not self.provider.authorized(token, self.distribution.account(aid)["advertiser_id"]):
            self.revoke(aid)
            raise Conflict("平台已不再授权该广告主，请重新授权")
        with self.store.transaction() as c:
            c.execute(
                "UPDATE qianchuan_grants SET verified_at=? WHERE account_id=?", (time.time(), aid)
            )
        return self.status(aid)

    def revoke(self, aid):
        # Local disconnect only; use platform console for actual provider-side revocation.
        with credential_lock(self.home), self.store.transaction() as c:
            c.execute(
                "UPDATE qianchuan_grants SET status='revoked',updated_at=? WHERE account_id=?",
                (time.time(), aid),
            )
        return self.status(aid)
