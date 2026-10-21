"""Parsing and remote requests have a wall-clock bound and never run in API threads."""

import json
import subprocess
import sys
import threading
from pathlib import Path

from .network import fetch_public
from .sources import parse_document, parse_html

SLOTS = threading.BoundedSemaphore(2)


def isolated(payload, timeout=40):
    if not SLOTS.acquire(blocking=False):
        raise ValueError("资料处理繁忙，请稍后重试")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "ecom_video.source_process"],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            cwd=Path(__file__).resolve().parent.parent,
        )
        if completed.returncode:
            raise ValueError("资料处理进程失败；请简化资料后重试")
        response = json.loads(completed.stdout)
        if "error" in response:
            raise ValueError(response["error"])
        return response
    except subprocess.TimeoutExpired as exc:
        raise ValueError("处理超过时限；请上传精简产品资料或稍后重试") from exc
    finally:
        SLOTS.release()


def main():
    # Resource ceilings are defense in depth; this is not an OS security sandbox.
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    payload = json.loads(sys.stdin.read(200_000))
    try:
        if payload["operation"] == "document":
            response = parse_document(payload["filename"], Path(payload["path"]).read_bytes())
        elif payload["operation"] == "url":
            final_url, data = fetch_public(payload["url"])
            response = parse_html(data)
            Path(payload["path"]).write_bytes(data)
            response["final_url"] = final_url
        elif payload["operation"] == "model":
            from .generation import call_model

            response = call_model(payload["facts"])
        else:
            raise ValueError("未知操作")
    except ValueError as exc:
        response = {"error": str(exc)}
    except Exception:
        # Never expose network diagnostics, document content, auth headers or vendor responses.
        response = {"error": "解析或远程请求失败，请检查资料格式、网络和服务配置"}
    sys.stdout.write(json.dumps(response, ensure_ascii=True))


if __name__ == "__main__":
    main()
