"""Run explicitly from an extracted handoff package. Does not install models or credentials."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("请先安装 Python 3.11+；未改变系统配置")
    missing = [
        name for name in ("uv", "node", "npm", "ffmpeg", "ffprobe") if not shutil.which(name)
    ]
    if missing:
        print(
            json.dumps(
                {
                    "ok": False,
                    "missing": missing,
                    "message": "先按CUSTOMER_INSTALL.md安装这些依赖，再重试",
                },
                ensure_ascii=False,
            )
        )
        return 1
    sys.path.insert(0, str(ROOT))
    from ecom_video.customer_launcher import dependency_fingerprint
    from ecom_video.customer_setup import node_ready
    from ecom_video.host_os import npm_command, venv_python

    if not node_ready():
        print("Node.js版本不满足本项目要求，请先安装22或24版本。尚未安装依赖。")
        return 1
    receipt = ROOT / ".customer-install.json"
    receipt.unlink(missing_ok=True)
    try:
        subprocess.run(["uv", "sync", "--locked"], cwd=ROOT, check=True, timeout=600)
        subprocess.run(
            [*npm_command(), "ci", "--no-audit", "--no-fund"],
            cwd=ROOT / "render/remotion",
            check=True,
            timeout=600,
        )
        browser = subprocess.run(
            ["node", "setup-browser.mjs"],
            cwd=ROOT / "render/remotion",
            check=True,
            timeout=300,
            capture_output=True,
            text=True,
        )
        browser = json.loads(browser.stdout.strip().splitlines()[-1])
        if not browser.get("ready") or not Path(browser["path"]).is_file():
            raise ValueError("browser not ready")
        python = venv_python(ROOT)
        subprocess.run(
            [str(python), "-m", "ecom_video.maintenance", "check"], cwd=ROOT, check=True, timeout=30
        )
        receipt.write_text(
            json.dumps({"fingerprint": dependency_fingerprint(ROOT), "browser": browser["path"]})
        )
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        print("安装未完成，请按首次安装指南检查失败步骤后重试；没有启动服务或修改密钥。")
        return 1
    print("基础依赖安装完成。下一步配置本机模型，再以 --customer 启动；尚未创建商品或执行投放。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
