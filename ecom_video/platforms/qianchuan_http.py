"""Official Qianchuan HTTP contracts; bounded responses and zero mutation retries."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from ..distribution import encode, identifier

API = "https://api.oceanengine.com/open_api"
OAUTH = "https://ad.oceanengine.com/open_api"
CREATE = "/v1.0/qianchuan/uni_aweme/ad/create/"
UPLOAD = "/2/file/video/ad/"
MATERIAL = "/v1.0/qianchuan/video/get/"
REPORT = "/v1.0/qianchuan/report/material/get/"


class ProviderError(Exception):
    def __init__(
        self,
        message="千川接口请求失败，请检查授权、权限及任务记录",
        *,
        uncertain=False,
        code=None,
        request_id=None,
    ):
        super().__init__(message)
        self.uncertain, self.code, self.request_id = uncertain, code, request_id


def platform_id(value):
    text = identifier(str(value))
    if int(text) > 9223372036854775807:
        raise ValueError("平台数值 ID 超出 int64 范围")
    return text


def asset_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,200}", value):
        raise ValueError("平台视频/封面 ID 格式无效")
    return value


def request_id(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value) else None
    )


def md5_file(path):
    sha = hashlib.md5()  # Official upload-integrity protocol, not an authentication primitive.
    with Path(path).open("rb") as src:
        while chunk := src.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


class QianchuanHTTP:
    def __init__(self, transport=None):
        self.transport = transport

    def request(self, method, path, *, token=None, oauth=False, **kwargs):
        allowed = (
            {"/oauth2/access_token/", "/oauth2/refresh_token/", "/oauth2/advertiser/get/"}
            if oauth
            else {CREATE, UPLOAD, MATERIAL, REPORT}
        )
        if path not in allowed:
            raise ValueError("未允许的千川接口")
        write = method == "POST"
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=httpx.Timeout(45, connect=10),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                headers = {"Access-Token": token} if token else {}
                with client.stream(
                    method, (OAUTH if oauth else API) + path, headers=headers, **kwargs
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError(uncertain=write)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 5 * 1024**2:
                            raise ProviderError("平台响应超过限制", uncertain=write)
                    payload = json.loads(body, parse_float=Decimal)
            if not isinstance(payload, dict) or type(payload.get("code")) is not int:
                raise ProviderError("平台响应结构无效", uncertain=write)
            rid = request_id(payload.get("request_id"))
            if payload["code"] != 0:
                raise ProviderError(
                    "平台明确拒绝请求；请核对授权、权限和参数", code=payload["code"], request_id=rid
                )
            if not isinstance(payload.get("data"), dict):
                raise ProviderError("平台响应缺少结果", uncertain=write, request_id=rid)
            return payload["data"], rid
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProviderError("平台连接或响应失败；写入结果可能不明", uncertain=write) from None

    def exchange(self, app_id, secret, code):
        data, _ = self.request(
            "POST",
            "/oauth2/access_token/",
            oauth=True,
            json={"app_id": int(platform_id(app_id)), "secret": secret, "auth_code": code},
        )
        return self._token(data)

    def refresh(self, app_id, secret, refresh_token):
        data, _ = self.request(
            "POST",
            "/oauth2/refresh_token/",
            oauth=True,
            json={
                "app_id": int(platform_id(app_id)),
                "secret": secret,
                "refresh_token": refresh_token,
            },
        )
        return self._token(data)

    @staticmethod
    def _token(data):
        for key in ("access_token", "refresh_token"):
            if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 4096:
                raise ProviderError("授权响应不完整，请重新授权", uncertain=True)
        for key in ("expires_in", "refresh_token_expires_in"):
            if type(data.get(key)) is not int or not 0 < data[key] <= 366 * 86400:
                raise ProviderError("授权期限无效，请重新授权", uncertain=True)
        return {
            k: data[k]
            for k in ("access_token", "refresh_token", "expires_in", "refresh_token_expires_in")
        }

    def authorized(self, token, advertiser_id):
        advertiser_id = platform_id(advertiser_id)
        data, _ = self.request(
            "GET", "/oauth2/advertiser/get/", oauth=True, params={"access_token": token}
        )
        rows = data.get("list")
        if not isinstance(rows, list):
            raise ProviderError("授权账户列表不完整")
        # P3 supports explicit advertiser authorization, not agency/shop hierarchy expansion.
        return any(
            isinstance(r, dict)
            and str(r.get("account_id", r.get("advertiser_id"))) == advertiser_id
            and r.get("is_valid") is True
            and (r.get("account_type") == "ADVERTISER" or r.get("account_role") == "ADVERTISER")
            for r in rows
        )

    def upload(self, token, advertiser_id, path, is_aigc):
        path = Path(path)
        signature = md5_file(path)
        with path.open("rb") as src:
            data, rid = self.request(
                "POST",
                UPLOAD,
                token=token,
                data={
                    "advertiser_id": platform_id(advertiser_id),
                    "upload_type": "UPLOAD_BY_FILE",
                    "video_signature": signature,
                    "filename": "ecom-" + signature + ".mp4",
                    "is_aigc": "true" if is_aigc else "false",
                },
                files={"video_file": ("video.mp4", src, "video/mp4")},
            )
        try:
            result = {
                "video_id": asset_id(data.get("video_id")),
                "material_id": platform_id(data.get("material_id")),
                "video_cover_id": asset_id(data.get("video_cover_id")),
                "md5": signature,
                "request_id": rid,
            }
            if data.get("video_signature") != signature:
                raise ValueError("signature")
            return result
        except ValueError:
            raise ProviderError(
                "上传返回的素材标识或校验值不完整，请人工核对", uncertain=True, request_id=rid
            ) from None

    def material(self, token, advertiser_id, video_id, signature, material_id):
        data, rid = self.request(
            "GET",
            MATERIAL,
            token=token,
            params={
                "advertiser_id": platform_id(advertiser_id),
                "filtering": encode({"video_ids": [asset_id(video_id)]}),
                "page": "1",
                "page_size": "50",
            },
        )
        rows = data.get("list")
        if not isinstance(rows, list):
            raise ProviderError("素材列表响应无效")
        if not rows:
            return None
        if len(rows) != 1:
            raise ProviderError("素材查询返回不唯一")
        row = rows[0]
        if (
            row.get("id") != video_id
            or row.get("signature") != signature
            or str(row.get("material_id")) != material_id
            or row.get("image_mode") != "VIDEO_VERTICAL"
        ):
            raise ProviderError("平台素材与上传的视频标识/MD5/方向不一致")
        return {
            "video_id": video_id,
            "material_id": material_id,
            "md5": signature,
            "image_mode": "VIDEO_VERTICAL",
            "request_id": rid,
        }

    def create(self, token, payload):
        data, rid = self.request("POST", CREATE, token=token, json=payload)
        try:
            return {
                "ad_id": platform_id(data.get("ad_id")),
                "request_id": rid,
                "source": "qianchuan_api",
            }
        except ValueError:
            raise ProviderError(
                "创建响应缺少有效计划 ID，请在平台核对", uncertain=True, request_id=rid
            ) from None

    def report_day(self, token, advertiser_id, day):
        from ..reporting import dates, normalize
        from .ocean_watch import FIELDS

        dates(day, day)
        rows, ids, expected = [], [], None
        for page in range(1, 51):
            data, rid = self.request(
                "GET",
                REPORT,
                token=token,
                params={
                    "advertiser_id": platform_id(advertiser_id),
                    "start_date": day,
                    "end_date": day,
                    "fields": encode(list(FIELDS)),
                    "page": str(page),
                    "page_size": "100",
                    "order_field": "stat_cost",
                    "order_type": "DESC",
                },
            )
            batch, info = data.get("list"), data.get("page_info", {})
            if (
                not isinstance(batch, list)
                or type(info.get("total_number")) is not int
                or type(info.get("total_page")) is not int
            ):
                raise ProviderError("平台报表分页信息不完整")
            count, total = info["total_number"], info["total_page"]
            if (
                not 0 <= count <= 5000
                or not 0 <= total <= 50
                or (expected is not None and expected != (count, total))
            ):
                raise ProviderError("报表超过上限或查询期间范围变化")
            expected = (count, total)
            if info.get("page") not in (page, 0 if count == 0 else page):
                raise ProviderError("报表分页不匹配")
            for row in batch:
                try:
                    if not isinstance(row, dict) or platform_id(
                        row.get("advertiser_id")
                    ) != platform_id(advertiser_id):
                        raise ValueError()
                except ValueError:
                    raise ProviderError("平台报表行的广告主缺失或不匹配，整批拒绝") from None
                fields = row.get("fields", row)
                if not isinstance(fields, dict):
                    raise ProviderError("平台报表指标结构无效")
                metrics = {v: fields.get(k) for k, v in FIELDS.items()}
                for key, value in metrics.items():
                    if key in ("spend", "revenue") or value is None:
                        continue
                    try:
                        count_value = Decimal(str(value))
                        if (
                            not count_value.is_finite()
                            or not 0 <= count_value <= 999999999999999
                            or count_value != count_value.to_integral_value()
                        ):
                            raise ValueError()
                        metrics[key] = str(int(count_value))
                    except (ValueError, InvalidOperation):
                        raise ProviderError("平台计数须为有限非负整数") from None
                rows.append(
                    {
                        "date": day,
                        "material_id": str(row.get("material_id")),
                        **metrics,
                    }
                )
            if rid:
                ids.append(rid)
            if page >= total:
                break
        if len(rows) != expected[0]:
            raise ProviderError("报表数据不完整")
        return {
            "date": day,
            "advertiser_id": advertiser_id,
            "request_ids": ids,
            "rows": normalize(rows, day, day),
            "source_format": "whitelisted_normalized_provider_response",
        }
