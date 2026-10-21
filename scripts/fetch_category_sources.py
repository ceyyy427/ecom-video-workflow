"""Fetch pinned official stock URLs into a private local cache, never the gallery."""

import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    rows = json.loads((ROOT / "docs/evidence/category-validation/sources.json").read_text())
    for row in rows:
        dest = ROOT / row["path"]
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == row["sha256"]:
            print(row["key"] + ": verified local cache")
            continue
        assert row["download_url"].startswith("https://videos.pexels.com/video-files/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        try:
            size = 0
            with httpx.stream("GET", row["download_url"], timeout=120, follow_redirects=False) as r:
                r.raise_for_status()
                with part.open("wb") as f:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > 100 * 1024**2:
                            raise ValueError("Stock download exceeds 100 MiB")
                        f.write(chunk)
            if (
                size != row["size"]
                or hashlib.sha256(part.read_bytes()).hexdigest() != row["sha256"]
            ):
                raise ValueError("Official source changed; review provenance before adopting")
            part.replace(dest)
            print(row["key"] + ": verified download")
        finally:
            part.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
