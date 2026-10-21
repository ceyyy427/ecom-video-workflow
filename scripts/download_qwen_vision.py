"""Download pinned official Qwen weights via ModelScope, verifying size and SHA256.

Does not change system networking, disable TLS, or import/run the downloaded model.
"""

import hashlib
import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "var/models/qwen3-vl-2b-official"
REV = "1d49f1a70c0c1ea52f82fd46ea44b388183aa16c"
BASE = "https://modelscope.cn/models/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/" + REV + "/"
FILES = {
    "Qwen3VL-2B-Instruct-Q4_K_M.gguf": (
        1107409952,
        "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae",
    ),
    "mmproj-Qwen3VL-2B-Instruct-F16.gguf": (
        819394848,
        "c3d5afbef5287953acd57b4043d2269456e5761a4eaccb3b71b062996970aea5",
    ),
}


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def validate_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
        raise ValueError("HTTPS only")
    if p.hostname != "modelscope.cn" and not p.hostname.endswith(".modelscope.cn"):
        raise ValueError("Unexpected download host")
    addresses = {r[4][0] for r in socket.getaddrinfo(p.hostname, 443)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Download host must resolve to public addresses")


def download(client, name, size, sha):
    target = DEST / name
    if target.is_file():
        if target.stat().st_size != size or digest(target) != sha:
            raise ValueError("Existing file failed verification; preserve it for inspection")
        print(name, "already verified", flush=True)
        return
    partial = target.with_suffix(".gguf.part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        raise ValueError("Partial file larger than expected")
    import shutil
    from concurrent.futures import ThreadPoolExecutor, as_completed

    parts = DEST / (name + ".chunks")
    parts.mkdir(exist_ok=True)
    ranges = [(a, min(size - 1, a + 4 * 1024**2 - 1)) for a in range(offset, size, 4 * 1024**2)]

    def fetch(bounds):
        a, b = bounds
        file = parts / str(a)
        if file.exists() and file.stat().st_size == b - a + 1:
            return b - a + 1
        for attempt in range(4):
            url = (
                "https://modelscope.cn/api/v1/models/Qwen/Qwen3-VL-2B-Instruct-GGUF/repo?Revision="
                + REV
                + "&FilePath="
                + name
            )
            try:
                for _ in range(5):
                    validate_url(url)
                    with client.stream(
                        "GET",
                        url,
                        headers={"Range": f"bytes={a}-{b}", "Accept-Encoding": "identity"},
                    ) as r:
                        if r.is_redirect:
                            url = urljoin(url, r.headers["location"])
                            continue
                        r.raise_for_status()
                        if (
                            r.status_code != 206
                            or r.headers.get("content-range") != f"bytes {a}-{b}/{size}"
                        ):
                            raise ValueError("Server did not honor exact resume range")
                        data = bytearray()
                        for chunk in r.iter_bytes(1024 * 1024):
                            data.extend(chunk)
                            if len(data) > b - a + 1:
                                raise ValueError("Download exceeds expected range")
                        if len(data) != b - a + 1:
                            raise ValueError("Incomplete download range")
                        temp = file.with_suffix(".part")
                        temp.write_bytes(data)
                        temp.replace(file)
                        return len(data)
                raise ValueError("Too many redirects")
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        raise AssertionError("unreachable")

    received = offset
    reported = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(fetch, r) for r in ranges]):
            received += future.result()
            if time.monotonic() - reported > 15 or received == size:
                print(name, round(received / size * 100, 1), "%", flush=True)
                reported = time.monotonic()
    with partial.open("ab") as out:
        for a, _b in ranges:
            with (parts / str(a)).open("rb") as f:
                shutil.copyfileobj(f, out)
    shutil.rmtree(parts)
    if partial.stat().st_size != size or digest(partial) != sha:
        raise ValueError("Downloaded model failed size/SHA256 verification")
    partial.rename(target)
    print(name, "SHA256 VERIFIED", sha, flush=True)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=httpx.Timeout(45, connect=20), trust_env=False, follow_redirects=False
    ) as c:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                pool.submit(download, c, name, size, sha) for name, (size, sha) in FILES.items()
            ]
            for result in results:
                result.result()
    manifest = {
        "source": BASE,
        "revision": REV,
        "license": "Apache-2.0",
        "cross_reference": "https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF",
        "files": [{"file": n, "size": s, "sha256": h} for n, (s, h) in FILES.items()],
    }
    (DEST / "source.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
