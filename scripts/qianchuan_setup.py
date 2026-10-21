"""Configure public app metadata and write secrets directly to the OS keychain."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ecom_video.db import Store  # noqa: E402
from ecom_video.qianchuan_auth import QianchuanAuth  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="配置千川应用；Secret 仅在隐藏输入中提供，保存在系统安全凭据库"
    )
    parser.add_argument("--data", default="var")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    root = Path(args.data).resolve()
    auth = QianchuanAuth(root, Store(root / "workflow.db"))
    if not auth.secrets.available():
        raise SystemExit("未找到 macOS Keychain / Linux secret-tool。禁止明文保存 Secret。")
    app_id = input("应用 App ID：").strip()
    secret = getpass.getpass("应用 Secret（不回显）：")
    maximum = input("每计划 budget 参数上限（元）：").strip()
    auth.configure(
        app_id, secret, f"http://127.0.0.1:{args.port}/api/qianchuan/oauth/callback", maximum
    )
    print("应用配置已保存。请在千川投放页面发起广告主授权。真实写入开关仍由启动环境控制。")


if __name__ == "__main__":
    main()
