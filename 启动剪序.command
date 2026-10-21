#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/launch_customer.py "$@"
fi
open docs/CUSTOMER_INSTALL.md
printf '%s\n' '请先从 python.org 安装 Python 3.11 或更新版本，再双击启动。'
exit 1
