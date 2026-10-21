"""Bounded public HTTPS, DNS pinned to the checked addresses (no environment proxy)."""

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

MAX_WEB_BYTES = 2 * 1024 * 1024


def public_target(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 for c in url):
        raise ValueError("链接格式无效")
    p = urlsplit(url)
    try:
        port = p.port
    except ValueError as exc:
        raise ValueError("链接端口无效") from exc
    if p.scheme != "https" or not p.hostname or p.username or p.password or port not in (None, 443):
        raise ValueError("只支持无账号信息的公网 HTTPS 链接（443 端口）")
    host = p.hostname.encode("idna").decode("ascii")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("链接必须指向公网地址")
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(r[4][0] for r in records))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("域名解析包含非公网地址")
    return host, addresses, (p.path or "/") + ("?" + p.query if p.query else "")


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def request_once(
    url, *, method="GET", body=None, headers=None, max_bytes=MAX_WEB_BYTES, timeout=15
):
    host, addresses, path = public_target(url)
    conn = PinnedHTTPS(host, addresses[0], timeout)
    try:
        conn.request(
            method, path, body=body, headers={"Accept-Encoding": "identity", **(headers or {})}
        )
        response = conn.getresponse()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
        if response_headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("服务器返回压缩内容，请改用文档上传")
        length = response_headers.get("content-length")
        if length and int(length) > max_bytes:
            raise ValueError("远程内容超过大小限制")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("远程内容超过大小限制")
        return response.status, response_headers, data
    finally:
        conn.close()


def fetch_public(url):
    current = url
    for _ in range(4):
        status, headers, data = request_once(
            current, headers={"User-Agent": "EcomWorkflow/0.2", "Accept": "text/html"}
        )
        if status in (301, 302, 303, 307, 308):
            current = urljoin(current, headers.get("location", ""))
            public_target(current)
            continue
        if status != 200:
            raise ValueError(f"网页返回 HTTP {status}；请上传产品文档")
        if "html" not in headers.get("content-type", "").lower():
            raise ValueError("产品链接需要返回 HTML 网页；其他格式请上传文档")
        return current, data
    raise ValueError("网页重定向次数过多")
