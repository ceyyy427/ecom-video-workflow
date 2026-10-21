"""stdlib-only desktop customer launcher. No shell commands or credential loading."""

import argparse
import hashlib
import html
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .host_os import (
    file_lock,
    open_lock,
    process_options,
    protect_descendants,
    stop_process,
    venv_python,
)

PROJECT = Path(__file__).resolve().parents[1]


def installation_id(project, data):
    return hashlib.sha256(f"{Path(project).resolve()}\0{Path(data).resolve()}".encode()).hexdigest()


def matches_instance(value, expected):
    return (
        isinstance(value, dict)
        and value.get("installation") == expected
        and value.get("customer") is True
    )


def probe(port):
    # Ignore configured proxy variables for all loopback requests.
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/setup/instance", timeout=1) as r:
            return json.loads(r.read(4097))
    except (OSError, ValueError):
        return None


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def dependency_fingerprint(project):
    root = Path(project)
    return hashlib.sha256(
        b"\0".join(
            (root / n).read_bytes() for n in ("uv.lock", "render/remotion/package-lock.json")
        )
    ).hexdigest()


def dependencies_ready(project):
    root = Path(project)
    try:
        receipt = json.loads((root / ".customer-install.json").read_text())
        return (
            receipt["fingerprint"] == dependency_fingerprint(root)
            and Path(receipt["browser"]).is_file()
            and venv_python(root).is_file()
            and (root / "render/remotion/node_modules/@remotion/renderer").is_dir()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def show_problem(message, *, browser=True):
    print(message, flush=True)
    if browser:
        fd, path = tempfile.mkstemp(prefix="jianxu-start-", suffix=".html")
        with os.fdopen(fd, "w") as f:
            f.write(
                '<!doctype html><meta charset="utf-8"><title>剪序 · 启动帮助</title>'
                '<body style="font:18px system-ui;max-width:800px;margin:60px auto;line-height:1.8">'
                "<h1>还差一步就能开始</h1><p>" + html.escape(message) + "</p>"
                "<p>安装完成后重新双击“启动剪序.command / 启动剪序.cmd”。不需要复制终端命令。</p>"
                "<p>软件包内 docs/CUSTOMER_INSTALL.md 有完整安装与故障说明。"
                "基础系统工具需要先安装，本启动器不会修改系统权限或关闭安全保护。</p>"
                "<p>Python：python.org · Node.js：nodejs.org（22/24版）· "
                "uv：docs.astral.sh/uv · FFmpeg：ffmpeg.org · 视觉识别：Ollama 应用</p></body>"
            )
        webbrowser.open(Path(path).as_uri())


def run_installer(command, cwd, timeout=1600):
    child = subprocess.Popen(command, cwd=cwd, **process_options())
    complete = False
    try:
        result = child.wait(timeout=timeout)
        if result:
            raise subprocess.CalledProcessError(result, command)
        complete = True
    finally:
        if not complete:
            stop_process(child, grace=5)


def main():
    parser = argparse.ArgumentParser(description="双击启动剪序：首次安装项目依赖并打开配置页")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=PROJECT / "var")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在1024–65535之间")
    browser = not args.no_browser
    expected = installation_id(PROJECT, args.data)
    url = f"http://127.0.0.1:{args.port}/setup"

    def open_page():
        if browser:
            webbrowser.open(url)

    # Never stop or reuse an unrelated server, even if it serves our health endpoint.
    if port_open(args.port):
        if matches_instance(probe(args.port), expected):
            print("已在运行，打开现有工作台。", flush=True)
            open_page()
            return 0
        show_problem(
            f"端口 {args.port} 正被其他程序或其他项目占用。请先关闭对应程序后重试；未停止任何进程。",
            browser=browser,
        )
        return 1
    protect_descendants()

    lock_path = PROJECT / ".customer-launch.lock"
    lock_fd = open_lock(lock_path)
    with os.fdopen(lock_fd, "r+b") as lock:
        try:
            file_lock(lock.fileno())
        except BlockingIOError:
            show_problem(
                "此安装目录正在启动或已打开其他数据目录。请等待首次安装完成，不要重复启动。",
                browser=browser,
            )
            return 1
        # Finder does not load shell profiles. Add known install locations, never source user files.
        os.environ["PATH"] = os.pathsep.join(
            dict.fromkeys(
                [
                    *os.environ.get("PATH", "").split(os.pathsep),
                    "/opt/homebrew/bin",
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                ]
            )
        )
        from .customer_setup import node_ready

        missing = [n for n in ("uv", "node", "npm", "ffmpeg", "ffprobe") if not shutil.which(n)]
        if sys.version_info < (3, 11):
            missing.append("Python 3.11+")
        if not node_ready():
            missing.append("Node.js 22/24")
        if missing:
            show_problem("需要先安装：" + "、".join(dict.fromkeys(missing)) + "。", browser=browser)
            return 1
        python = venv_python(PROJECT)

        def stop(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, stop)
        if not dependencies_ready(PROJECT):
            print("首次安装项目依赖，可能需要数分钟；请保留此窗口，不需要输入命令。", flush=True)
            try:
                run_installer(
                    [sys.executable, str(PROJECT / "scripts/install_customer.py")], PROJECT
                )
            except KeyboardInterrupt:
                print("已停止首次安装；下次双击会重新检查并补齐。", flush=True)
                return 0
            except (OSError, subprocess.SubprocessError):
                show_problem(
                    "项目依赖安装未完成。检查网络和上方失败步骤后重新双击；商品资料和密钥没有被改写。",
                    browser=browser,
                )
                return 1
        child = None
        try:
            child = subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "ecom_video",
                    "--customer",
                    "--data",
                    str(args.data.resolve()),
                    "--port",
                    str(args.port),
                ],
                cwd=PROJECT,
                **process_options(),
            )
            deadline = time.monotonic() + 30
            while child.poll() is None and time.monotonic() < deadline:
                if matches_instance(probe(args.port), expected):
                    print("工作台已就绪；关闭启动窗口或按 Ctrl-C 可停止。", flush=True)
                    open_page()
                    return child.wait()
                time.sleep(0.3)
            show_problem(
                "服务尚未就绪。检查端口、FFmpeg和中文字体；失败步骤见启动窗口。再次启动前等待本窗口退出。",
                browser=browser,
            )
            return 1
        except KeyboardInterrupt:
            return 0
        finally:
            if child and child.poll() is None:
                stop_process(child, grace=15)


if __name__ == "__main__":
    raise SystemExit(main())
