"""Explicit, hash-verified local model provisioning. Never runs during video submission."""

import hashlib
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
record = json.loads((root / "docs/P5_MODEL.json").read_text())
folder = root / "var/models/firered"
folder.mkdir(parents=True, exist_ok=True)
for name, expected in record["files"].items():
    target = folder / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        print(name, "verified")
        continue
    url = f"https://huggingface.co/{record['repo']}/resolve/{record['revision']}/{name}"
    partial = folder / (name + ".part")
    print("Downloading", name, flush=True)
    urllib.request.urlretrieve(url, partial)
    if hashlib.sha256(partial.read_bytes()).hexdigest() != expected:
        raise SystemExit("模型哈希不一致；保留 .part 供诊断，未启用")
    partial.replace(target)
    print(name, "verified")
print("Run: uv sync --group dev --group browser; npm ci --prefix render/remotion")
