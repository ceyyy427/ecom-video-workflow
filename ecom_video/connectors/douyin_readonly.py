"""Official own-public-video counters: fixed read POST, bounded output, no retries."""

import json
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ReadGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    account_id: str = Field(pattern="^[a-f0-9]{32}$")
    open_id: str = Field(min_length=1, max_length=256)
    token: SecretStr = Field(exclude=True, repr=False)
    scopes: list[str]
    expires_at: float


class ProviderProblem(ValueError):
    def __init__(self, code="unavailable"):
        self.code = code
        super().__init__("抖音只读数据未取得，请核对授权、video.data权限及本人作品ID；未自动重试")


def counter(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value < 10**20:
        raise ProviderProblem("invalid_counter")
    return str(value)


class DouyinReadOnly:
    def __init__(self, transport=None):
        self.transport = transport

    def read(self, grant, content_ids):
        if "video.data" not in grant.scopes or grant.expires_at <= time.time():
            raise ProviderProblem("reauthorize")
        if (
            not isinstance(content_ids, list)
            or not 1 <= len(content_ids) <= 10
            or len(set(content_ids)) != len(content_ids)
            or any(
                not isinstance(v, str) or not 1 <= len(v) <= 256 or any(ord(c) < 33 for c in v)
                for v in content_ids
            )
        ):
            raise ProviderProblem("invalid_ids")
        token = grant.token.get_secret_value()
        if not token or len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token):
            raise ProviderProblem("reauthorize")
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=httpx.Timeout(30, connect=10),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                raw = bytearray()
                started = time.monotonic()
                with client.stream(
                    "POST",
                    "https://open.douyin.com/video/data/",
                    params={"open_id": grant.open_id},
                    headers={"access-token": token, "Content-Type": "application/json"},
                    json={"item_ids": content_ids},
                ) as r:
                    if r.status_code != 200:
                        raise ProviderProblem("http_" + str(r.status_code))
                    for chunk in r.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024**2 or time.monotonic() - started > 30:
                            raise ProviderProblem("output_limit")
            data = json.loads(raw)
        except (httpx.HTTPError, ValueError, TypeError) as error:
            if isinstance(error, ProviderProblem):
                raise
            raise ProviderProblem() from None
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise ProviderProblem("invalid_response")
        body = data["data"]
        if body.get("error_code") != 0:
            raise ProviderProblem("platform_error")
        found = body.get("list")
        if not isinstance(found, list) or len(found) > 10:
            raise ProviderProblem("invalid_response")
        rows = []
        seen = set()
        mapping = {
            "views": "play_count",
            "likes": "digg_count",
            "comments": "comment_count",
            "shares": "share_count",
            "downloads": "download_count",
        }
        for item in found:
            if not isinstance(item, dict):
                raise ProviderProblem("invalid_response")
            oid = item.get("item_id")
            if oid not in content_ids or oid in seen:
                raise ProviderProblem("account_or_content_mismatch")
            seen.add(oid)
            stats = item.get("statistics", {})
            if not isinstance(stats, dict):
                raise ProviderProblem("invalid_response")
            values = {name: counter(stats.get(source)) for name, source in mapping.items()}
            rows.append(
                {
                    "content_ref": oid,
                    "values": values,
                    "missing_reasons": {
                        k: "平台未返回该指标" for k, v in values.items() if v is None
                    },
                }
            )
        for oid in content_ids:
            if oid not in seen:
                rows.append(
                    {
                        "content_ref": oid,
                        "values": dict.fromkeys(mapping),
                        "missing_reasons": dict.fromkeys(mapping, "作品不可见或平台未返回，不补零"),
                    }
                )
        observed = datetime.now(UTC)
        return {
            "platform": "douyin",
            "account_ref": grant.account_id,
            "dataset_kind": "organic",
            "counting": "cumulative",
            "observed_at": observed.isoformat(),
            "metric_date": observed.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "timezone": "Asia/Shanghai",
            "currency": None,
            "attribution_window": None,
            "rows": rows,
            "source_kind": "official_own_public_video",
            "causal_inference": False,
            "platform_writes": 0,
        }
