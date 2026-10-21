"""Start both local processes; Ctrl-C stops children without losing the queue."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .media import font_path


def doctor():
    checks = {
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
    }
    try:
        checks["font"] = str(font_path())
    except ValueError:
        checks["font"] = None
    checks["ready"] = all(checks.values())
    print(json.dumps(checks, ensure_ascii=False, indent=2), flush=True)
    return checks["ready"]


def main():
    parser = argparse.ArgumentParser(description="本地电商视频工作流")
    parser.add_argument("--data", default=os.getenv("ECOM_DATA_DIR", "var"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="仅检查本机依赖")
    parser.add_argument(
        "--customer",
        action="store_true",
        help="客户模式：关闭平台写入和自动执行，开启CSV复盘与创意迭代",
    )
    parser.add_argument("--api-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from .host_os import protect_descendants

    if not args.check and not args.api_only:
        protect_descendants()
    if args.customer:
        from .customer_setup import customer_profile

        customer_profile()
    if args.check:
        raise SystemExit(0 if doctor() else 1)
    if args.api_only:
        import uvicorn

        from .api import create_app

        uvicorn.run(
            create_app(args.data),
            host="127.0.0.1",
            port=args.port,
            log_level="info",
            access_log=False,
        )
        return
    if not doctor():
        raise SystemExit("缺少运行依赖；请查看 README.md 安装 FFmpeg 或设置 ECOM_FONT。")
    root = str(Path(args.data).resolve())
    # Migrate once before parallel children open a newly created SQLite file.
    from .db import Store

    Store(Path(root) / "workflow.db")

    def request_stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    children = []
    print(f"打开 http://127.0.0.1:{args.port} ；按 Ctrl-C 停止。数据目录：{root}", flush=True)
    result = 0
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ecom_video",
                    "--api-only",
                    "--data",
                    root,
                    "--port",
                    str(args.port),
                ]
            )
        )
        children.append(
            subprocess.Popen([sys.executable, "-m", "ecom_video.worker", "--data", root])
        )
        children.append(
            subprocess.Popen([sys.executable, "-m", "ecom_video.platform_worker", "--data", root])
        )
        children.append(
            subprocess.Popen([sys.executable, "-m", "ecom_video.analysis_worker", "--data", root])
        )
        from .agent_runtime_contracts import execution_enabled

        if execution_enabled():
            children.append(
                subprocess.Popen([sys.executable, "-m", "ecom_video.agent_worker", "--data", root])
            )
        while all(p.poll() is None for p in children):
            time.sleep(0.5)
        result = 1
        print("服务进程退出，正在关闭另一进程；任务记录仍然保留。", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        for p in children:
            if p.poll() is None:
                p.terminate()
        for p in children:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    raise SystemExit(result)


if __name__ == "__main__":
    main()
