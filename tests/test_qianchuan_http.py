import hashlib
import json

import httpx
import pytest

from ecom_video.platforms.qianchuan_http import ProviderError, QianchuanHTTP


def test_oauth_and_upload_wire_contract(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture-video")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.scheme == "https" and request.url.host in (
            "api.oceanengine.com",
            "ad.oceanengine.com",
        )
        if request.url.path.endswith("/oauth2/access_token/"):
            assert json.loads(request.content) == {
                "app_id": 123,
                "secret": "app-secret",
                "auth_code": "code",
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": 86400,
                        "refresh_token_expires_in": 2592000,
                    },
                },
            )
        assert request.url.path == "/open_api/2/file/video/ad/"
        assert request.headers["Access-Token"] == "access"
        body = request.read()
        assert (
            b"fixture-video" in body and hashlib.md5(b"fixture-video").hexdigest().encode() in body
        )
        assert b'name="advertiser_id"' in body and b"1234567890123456789" in body
        assert b'name="is_aigc"' in body and b"true" in body
        return httpx.Response(
            200,
            json={
                "code": 0,
                "request_id": "request-123",
                "data": {
                    "video_id": "v030xxABC",
                    "material_id": 987654321012345678,
                    "video_cover_id": "tos-cn-i-cover",
                    "video_signature": hashlib.md5(b"fixture-video").hexdigest(),
                },
            },
        )

    api = QianchuanHTTP(transport=httpx.MockTransport(handler))
    assert api.exchange("123", "app-secret", "code")["access_token"] == "access"
    result = api.upload("access", "1234567890123456789", video, True)
    assert result["video_id"] == "v030xxABC" and result["material_id"] == "987654321012345678"
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["timeout", "bad_json", "missing_ad_id", "http500", "redirect"])
def test_create_uncertain_never_retries_or_exposes_provider_text(kind):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("token=LEAK", request=request)
        if kind == "bad_json":
            return httpx.Response(200, text="LEAK")
        if kind == "missing_ad_id":
            return httpx.Response(200, json={"code": 0, "data": {}, "message": "LEAK"})
        return httpx.Response(
            500 if kind == "http500" else 302,
            text="LEAK",
            headers={"Location": "https://evil.invalid"},
        )

    api = QianchuanHTTP(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as info:
        api.create("token", {"advertiser_id": 123})
    assert info.value.uncertain and len(calls) == 1
    assert "LEAK" not in str(info.value)


def test_explicit_rejection_is_failed_not_unknown():
    api = QianchuanHTTP(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"code": 40000, "message": "secret=LEAK", "request_id": "req123"}
            )
        )
    )
    with pytest.raises(ProviderError) as info:
        api.create("token", {"advertiser_id": 123})
    assert not info.value.uncertain and info.value.code == 40000
    assert "LEAK" not in str(info.value)


def test_material_identity_and_direct_account_scope():
    def handler(request):
        if "oauth2/advertiser" in request.url.path:
            assert request.url.params["access_token"] == "token"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "list": [
                            {"account_id": 123, "account_type": "ADVERTISER", "is_valid": True}
                        ]
                    },
                },
            )
        assert request.headers["Access-Token"] == "token"
        assert json.loads(request.url.params["filtering"]) == {"video_ids": ["v030xx"]}
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": "v030xx",
                            "material_id": 456,
                            "signature": "a" * 32,
                            "image_mode": "VIDEO_VERTICAL",
                        }
                    ]
                },
            },
        )

    api = QianchuanHTTP(transport=httpx.MockTransport(handler))
    assert api.authorized("token", "123") is True
    assert api.authorized("token", "999") is False
    assert api.material("token", "123", "v030xx", "a" * 32, "456")["video_id"] == "v030xx"
    with pytest.raises(ProviderError):
        api.material("token", "123", "v030xx", "b" * 32, "456")


def test_native_report_contract_pagination_and_missing_metrics():
    def handler(request):
        assert request.url.path == "/open_api/v1.0/qianchuan/report/material/get/"
        assert request.headers["Access-Token"] == "token"
        assert request.url.params["start_date"] == request.url.params["end_date"] == "2026-10-12"
        assert "stat_cost" in json.loads(request.url.params["fields"])
        return httpx.Response(
            200,
            json={
                "code": 0,
                "request_id": "fixture-report",
                "data": {
                    "list": [
                        {
                            "advertiser_id": 123,
                            "material_id": 9123456789012345678,
                            "fields": {
                                "stat_cost": 12.25,
                                "show_cnt": 100,
                                "click_cnt": 5,
                                "pay_order_count": 1,
                                "pay_order_amount": 30,
                            },
                        }
                    ],
                    "page_info": {"page": 1, "total_page": 1, "total_number": 1},
                },
            },
        )

    api = QianchuanHTTP(transport=httpx.MockTransport(handler))
    result = api.report_day("token", "123", "2026-10-12")
    assert result["rows"][0]["material_id"] == "9123456789012345678"
    assert result["rows"][0]["spend"] == "12.25"
    assert result["rows"][0]["completed_views"] is None
    assert result["request_ids"] == ["fixture-report"]


@pytest.mark.parametrize("count,valid", [(100.0, True), (100.5, False), (-1.0, False)])
def test_report_float_counts_and_account_scope(count, valid):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {"advertiser_id": 123, "material_id": 456, "fields": {"show_cnt": count}}
                    ],
                    "page_info": {"page": 1, "total_page": 1, "total_number": 1},
                },
            },
        )

    api = QianchuanHTTP(transport=httpx.MockTransport(handler))
    if valid:
        assert api.report_day("token", "123", "2026-10-12")["rows"][0]["impressions"] == "100"
    else:
        with pytest.raises((ValueError, ProviderError)):
            api.report_day("token", "123", "2026-10-12")


@pytest.mark.parametrize("advertiser", [None, 999])
def test_report_missing_or_wrong_advertiser_rejected(advertiser):
    api = QianchuanHTTP(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "advertiser_id": advertiser,
                                "material_id": 456,
                                "fields": {"show_cnt": 100},
                            }
                        ],
                        "page_info": {"page": 1, "total_page": 1, "total_number": 1},
                    },
                },
            )
        )
    )
    with pytest.raises(ProviderError):
        api.report_day("token", "123", "2026-10-12")
