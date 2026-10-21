import io
import socket
import zipfile

import pytest

from ecom_video import network
from ecom_video.sources import parse_document, parse_html


def test_document_locators_and_quotes():
    result = parse_document("介绍.txt", "产品名称：随行杯\n容量：500mL\n材质：不锈钢".encode())
    assert result["units"][1]["text"] == "容量：500mL"
    assert result["units"][1]["locator"] == "第 2 行"
    assert result["units"][1]["id"] == "u002"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>产品名称：随行杯</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>容量</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>500mL</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""",
        )
    result = parse_document("产品.docx", buf.getvalue())
    assert result["units"][0]["locator"] == "第 1 段"
    assert result["units"][1]["locator"] == "表 1 / 行 1"
    assert "500mL" in result["units"][1]["text"]


def test_pdf_extracts_pages_and_rejects_blank():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(300, 400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 350 Td (Capacity: 500mL) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    result = parse_document("product.pdf", buffer.getvalue())
    assert "第 1 页" in result["units"][0]["locator"]
    assert "500mL" in result["units"][0]["text"]
    blank = PdfWriter()
    blank.add_blank_page(300, 400)
    buffer = io.BytesIO()
    blank.write(buffer)
    with pytest.raises(ValueError, match="文字|扫描"):
        parse_document("scan.pdf", buffer.getvalue())


def test_html_product_jsonld_preserves_pointer_and_no_script_execution():
    body = b"""<html><head><title>Test cup</title><script type="application/ld+json">{"@type":"Product","name":"Cup","sku":"C1","offers":{"price":"19.9","priceCurrency":"CNY"}}</script><script>fetch('http://127.0.0.1/')</script></head><body><p>Capacity: 500mL.</p></body></html>"""
    parsed = parse_html(body, "text/html; charset=utf-8")
    assert any(u["text"] == "Cup" and "name" in u["locator"] for u in parsed["units"])
    assert any("19.9" in u["text"] for u in parsed["units"])
    assert not any("fetch" in u["text"] for u in parsed["units"])
    with pytest.raises(ValueError, match="登录|验证码|正文"):
        parse_html(
            b'<html><body><form><input type="password">Sign in</form></body></html>', "text/html"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com:8443",
        "file:///etc/passwd",
        "https://127.0.0.1",
        "https://[::1]",
        "https://169.254.169.254",
    ],
)
def test_url_boundary(url):
    with pytest.raises(ValueError):
        network.public_target(url)


def test_mixed_public_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError, match="公网"):
        network.public_target("https://example.com/product")


def test_redirect_is_rechecked_and_not_followed_with_credentials(monkeypatch):
    calls = []

    def request(url, **kwargs):
        network.public_target(url)
        calls.append(url)
        return 302, {"location": "https://127.0.0.1/private"}, b""

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(network, "request_once", request)
    with pytest.raises(ValueError):
        network.fetch_public("https://example.com/product")
    assert len(calls) == 1


def test_bad_documents_do_not_become_facts():
    for name, data in [
        ("x.txt", b"\x00\x01"),
        ("x.pdf", b"not pdf"),
        ("x.docx", b"not zip"),
        ("x.exe", b"content"),
    ]:
        with pytest.raises(ValueError):
            parse_document(name, data)


def test_pinned_tls_uses_checked_ip_and_original_hostname(monkeypatch):
    connected, tls = [], []

    class RawSocket:
        def close(self):
            pass

    raw = RawSocket()

    def connect(address, timeout):
        connected.append(address)
        return raw

    monkeypatch.setattr(socket, "create_connection", connect)
    connection = network.PinnedHTTPS("product.example", "93.184.216.34", 10)

    class Context:
        def wrap_socket(self, sock, server_hostname):
            tls.append(server_hostname)
            return sock

    connection._context = Context()
    connection.connect()
    assert connected == [("93.184.216.34", 443)]
    assert tls == ["product.example"]


def test_response_size_and_encoding_limits(monkeypatch):
    monkeypatch.setattr(
        network, "public_target", lambda url: ("product.example", ["93.184.216.34"], "/")
    )

    class Response:
        status = 200
        headers = []
        body = b"x" * 101

        def getheaders(self):
            return self.headers

        def read(self, count):
            return self.body[:count]

    response = Response()

    class Connection:
        def __init__(self, *args):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr(network, "PinnedHTTPS", Connection)
    with pytest.raises(ValueError, match="大小"):
        network.request_once("https://product.example", max_bytes=100)
    response.headers = [("content-encoding", "gzip")]
    with pytest.raises(ValueError, match="压缩"):
        network.request_once("https://product.example")


def test_docx_entity_and_zip_expansion_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"A" * 1_000_000)
    with pytest.raises(ValueError, match="压缩"):
        parse_document("bomb.docx", buf.getvalue())


def test_challenge_page_is_not_product_evidence():
    html = b'<html><head><title>Just a moment...</title></head><body><main><h1>Verify you are human</h1><p>Checking if the site connection is secure. Please complete the security check to continue.</p><div class="cf-turnstile" data-sitekey="fixture"></div></main></body></html>'
    with pytest.raises(ValueError, match="验证码"):
        parse_html(html)


def test_public_html_redirect_success_has_final_url(monkeypatch):
    monkeypatch.setattr(
        network, "public_target", lambda url: ("example.com", ["93.184.216.34"], "/")
    )
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        assert "Authorization" not in kwargs.get("headers", {})
        if len(calls) == 1:
            return 302, {"location": "/product"}, b""
        return 200, {"content-type": "text/html"}, b"<p>Product</p>"

    monkeypatch.setattr(network, "request_once", request)
    final, body = network.fetch_public("https://example.com/start")
    assert final == "https://example.com/product"
    assert body == b"<p>Product</p>"
