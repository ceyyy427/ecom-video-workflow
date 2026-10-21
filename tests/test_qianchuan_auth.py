import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest

from ecom_video.db import Conflict, Store
from ecom_video.distribution import Distribution
from ecom_video.platforms.qianchuan_http import ProviderError
from ecom_video.qianchuan_auth import QianchuanAuth


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def read(self, key):
        return self.values.get(key, {})

    def write(self, key, value):
        self.values[key] = dict(value)

    def delete(self, key):
        self.values.pop(key, None)

    def available(self):
        return True


class OAuthFixture:
    def __init__(self):
        self.refreshes = 0
        self.exchanges = 0
        self.allowed = True
        self.fail = False

    def exchange(self, *args):
        self.exchanges += 1
        return {
            "access_token": "private-access",
            "refresh_token": "private-refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 86400,
        }

    def authorized(self, *args):
        return self.allowed

    def refresh(self, *args):
        self.refreshes += 1
        if self.fail:
            raise ProviderError(uncertain=True)
        return {
            "access_token": "new-private-access",
            "refresh_token": "new-private-refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 86400,
        }


@pytest.fixture
def auth_setup(tmp_path):
    store = Store(tmp_path / "workflow.db")
    account = Distribution(tmp_path, store).add_account("千川", "qianchuan", "123")
    secrets = MemorySecrets()
    provider = OAuthFixture()
    auth = QianchuanAuth(tmp_path, store, secrets=secrets, provider=provider)
    auth.configure(
        "456", "private-app-secret", "http://127.0.0.1:8765/api/qianchuan/oauth/callback", "1000"
    )
    return auth, account["id"], provider, secrets


def authorize(setup):
    auth, aid, _, _ = setup
    session = auth.start(aid)
    state = parse_qs(urlparse(session["url"]).query)["state"][0]
    auth.callback(state, "valid-code")
    return state


def test_oauth_state_once_account_and_no_secrets(auth_setup):
    auth, aid, provider, secrets = auth_setup
    with pytest.raises(Conflict):
        auth.callback("bad-state", "code")
    state = authorize(auth_setup)
    assert auth.status(aid)["status"] == "authorized"
    assert "private" not in json.dumps(auth.status(aid))
    with auth.store.connect() as c:
        dump = "\n".join(c.iterdump())
    assert "private" not in dump and state not in dump and "valid-code" not in dump
    with pytest.raises(Conflict):
        auth.callback(state, "code")
    assert provider.exchanges == 1
    assert auth.token(aid) == "private-access"


def test_wrong_advertiser_and_expired_state(auth_setup):
    auth, aid, provider, _ = auth_setup
    provider.allowed = False
    with pytest.raises(Conflict):
        authorize(auth_setup)
    assert auth.status(aid)["status"] != "authorized"
    session = auth.start(aid)
    state = parse_qs(urlparse(session["url"]).query)["state"][0]
    with auth.store.transaction() as c:
        c.execute("UPDATE qianchuan_oauth_sessions SET expires_at=0")
    with pytest.raises(Conflict):
        auth.callback(state, "code")
    assert provider.exchanges == 1


def test_refresh_rotation_serialized_and_failure_not_retried(auth_setup):
    auth, aid, provider, secrets = auth_setup
    authorize(auth_setup)
    grant = auth.grant(aid)
    secret = secrets.read(grant["secret_ref"])
    secret["expires_at"] = time.time() - 1
    secrets.write(grant["secret_ref"], secret)
    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda _: auth.token(aid), range(2)))
    assert values == ["new-private-access"] * 2 and provider.refreshes == 1
    secret = secrets.read(grant["secret_ref"])
    secret["expires_at"] = 0
    secrets.write(grant["secret_ref"], secret)
    provider.fail = True
    with pytest.raises(ProviderError):
        auth.token(aid)
    with pytest.raises(Conflict):
        auth.token(aid)
    assert provider.refreshes == 2
    assert auth.status(aid)["status"] == "reauthorize"


def test_reconfiguration_invalidates_grants_and_sessions(auth_setup):
    auth, aid, _, _ = auth_setup
    authorize(auth_setup)
    auth.configure(
        "456",
        "new-private-app-secret",
        "http://127.0.0.1:8765/api/qianchuan/oauth/callback",
        "1000",
    )
    assert auth.status(aid)["status"] == "reauthorize"
    with pytest.raises(Conflict):
        auth.token(aid)


@pytest.mark.parametrize(
    "key,value",
    [
        ("redirect_uri", "https://evil.invalid/callback"),
        ("max_budget", "-1"),
        ("revision", "x" * 32),
        ("secret_ref", "other-ref"),
    ],
)
def test_public_config_tamper_fails_closed(auth_setup, key, value):
    auth, *_ = auth_setup
    config = auth.config()
    config[key] = value
    auth.path.write_text(json.dumps(config))
    with pytest.raises(Conflict):
        auth.config()
