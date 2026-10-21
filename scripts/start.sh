#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  exec uv run --locked python -m ecom_video "$@"
fi
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m ecom_video "$@"
fi
printf '%s\n' '请先安装 uv 并执行 uv sync --locked，或按 README 创建虚拟环境。' >&2
exit 1
