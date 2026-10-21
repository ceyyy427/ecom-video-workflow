"""Explicit, pinned project-local download; never overwrite an existing checkout."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "ecom_video/platforms/ocean_watch.lock.json").read_text())
DEST = ROOT / "references/ocean-watch"
if not DEST.exists():
    DEST.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--no-checkout", LOCK["repository"], str(DEST)], check=True)
    subprocess.run(["git", "-C", str(DEST), "checkout", "--detach", LOCK["commit"]], check=True)
else:
    current = subprocess.check_output(
        ["git", "-C", str(DEST), "rev-parse", "HEAD"], text=True
    ).strip()
    if current != LOCK["commit"]:
        raise SystemExit("现有目录版本不同；请自行保留后选择独立位置，安装器不会覆盖。")

for name, expected in LOCK["sha256"].items():
    path = DEST / ".codex-plugin/bin" / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f"二进制校验失败：{name}")
print("Ocean Watch 项目内固定版本及全部平台二进制校验通过；未配置授权，未执行平台请求。")
