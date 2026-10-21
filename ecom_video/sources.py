"""Extract quoted text with stable locators. Extraction does not verify product claims."""

import io
import json
import re
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from defusedxml import ElementTree
from pypdf import PdfReader

MAX_DOCUMENT = 10 * 1024 * 1024
MAX_TEXT = 100_000
MAX_UNITS = 300


def cleaned(text):
    return re.sub(r"\s+", " ", text).strip()


def result(units, title=""):
    units = [(loc, cleaned(text)) for loc, text in units if cleaned(text)]
    if not units:
        raise ValueError("未提取到可用文字；扫描件需先转为文字，登录或验证码页面请改用文档")
    if len(units) > MAX_UNITS or sum(len(t) for _, t in units) > MAX_TEXT:
        raise ValueError("文字过多；请拆分成不超过 300 段、10 万字的产品资料")
    if any(ord(c) < 32 for _, t in units for c in t):
        raise ValueError("资料包含无效控制字符")
    return {
        "title": title[:120],
        "units": [
            {"id": f"u{i:03d}", "locator": loc, "text": text}
            for i, (loc, text) in enumerate(units, 1)
        ],
    }


def parse_document(filename, data):
    if not data or len(data) > MAX_DOCUMENT:
        raise ValueError("文档为空或超过 10 MiB")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in (".txt", ".md"):
            return result(
                [
                    (f"第 {i} 行", line)
                    for i, line in enumerate(data.decode("utf-8-sig").splitlines(), 1)
                ],
                Path(filename).stem,
            )
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted or len(reader.pages) > 50:
                raise ValueError("只支持未加密、最多 50 页的文字 PDF")
            return result(
                [
                    (f"第 {i} 页", page.extract_text() or "")
                    for i, page in enumerate(reader.pages, 1)
                ],
                Path(filename).stem,
            )
        if suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                if (
                    len(infos) > 1000
                    or sum(x.file_size for x in infos) > 30 * 1024 * 1024
                    or any(
                        x.file_size > 10 * 1024 * 1024
                        or x.file_size > max(1, x.compress_size) * 200
                        for x in infos
                    )
                ):
                    raise ValueError("DOCX 解压大小或压缩比超过限制")
                root = ElementTree.fromstring(z.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            body = root.find("w:body", ns)
            units, paragraph, table = [], 0, 0
            if body is None:
                raise ValueError("DOCX 缺少正文")
            for child in body:
                if child.tag.endswith("}p"):
                    paragraph += 1
                    units.append(
                        (
                            f"第 {paragraph} 段",
                            "".join(t.text or "" for t in child.findall(".//w:t", ns)),
                        )
                    )
                elif child.tag.endswith("}tbl"):
                    table += 1
                    for rownum, row in enumerate(child.findall("w:tr", ns), 1):
                        units.append(
                            (
                                f"表 {table} / 行 {rownum}",
                                " | ".join(
                                    "".join(t.text or "" for t in cell.findall(".//w:t", ns))
                                    for cell in row.findall("w:tc", ns)
                                ),
                            )
                        )
            return result(units, Path(filename).stem)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("文档无法解析；请检查格式，或另存为 UTF-8 TXT") from exc
    raise ValueError("支持 TXT、MD、文字 PDF 和 DOCX")


def parse_html(data, content_type="text/html"):
    if "html" not in content_type:
        raise ValueError("只支持 HTML 网页")
    soup = BeautifulSoup(data, "html.parser")
    if soup.select('input[type="password"]'):
        raise ValueError("登录页面不能作为产品资料，请上传文档")
    title_text = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    heading_text = " ".join(h.get_text(" ", strip=True).lower() for h in soup.select("h1,h2"))
    challenge_phrases = (
        "just a moment",
        "verify you are human",
        "security check",
        "attention required",
        "安全验证",
        "访问验证",
        "验证码",
    )
    if soup.select("#challenge-form,#cf-challenge-running,.cf-turnstile") or any(
        phrase in title_text or phrase in heading_text for phrase in challenge_phrases
    ):
        raise ValueError("网页包含验证码或安全挑战，请完成访问后导出产品文档上传")
    units = []

    def product_objects(value, pointer):
        if isinstance(value, dict):
            kind = value.get("@type", [])
            if kind == "Product" or isinstance(kind, list) and "Product" in kind:
                # Only product-facing fields. Never ingest arbitrary instructions or URLs.
                def flatten(v, p):
                    if isinstance(v, dict):
                        for k, item in v.items():
                            if k in {
                                "name",
                                "description",
                                "sku",
                                "brand",
                                "offers",
                                "price",
                                "priceCurrency",
                                "availability",
                                "additionalProperty",
                                "value",
                                "unitText",
                                "material",
                                "color",
                                "size",
                            }:
                                flatten(item, p + "/" + k)
                    elif isinstance(v, list):
                        for i, item in enumerate(v):
                            flatten(item, p + f"/{i}")
                    elif isinstance(v, (str, int, float)):
                        units.append((p, str(v)))

                flatten(value, pointer)
            else:
                for key, item in value.items():
                    product_objects(item, pointer + "/" + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                product_objects(item, pointer + f"/{i}")

    for i, tag in enumerate(soup.select('script[type="application/ld+json"]'), 1):
        try:
            product_objects(json.loads(tag.get_text()), f"JSON-LD {i}")
        except (ValueError, RecursionError):
            continue
    title = soup.title.get_text(" ", strip=True) if soup.title else "产品网页"
    for tag in soup.select("script,style,nav,footer,header,noscript,form"):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    for i, tag in enumerate(main.select("h1,h2,h3,p,li,tr"), 1):
        text = tag.get_text(" ", strip=True)
        if text and not tag.find_parent(["li", "tr"]):
            units.append((f"网页正文 / 段 {i}", text))
    if not units or (
        sum(len(t) for _, t in units) < 20 and not any("JSON-LD" in loc for loc, _ in units)
    ):
        raise ValueError("网页正文不足，可能需要登录、验证码或 JavaScript；请上传产品文档")
    return result(units, title)
