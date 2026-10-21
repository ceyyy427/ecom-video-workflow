"""Lazy, owned Ollama process for the verified small-Mac inference profile.

No generic host/command configuration, cloud inference or customer credentials.
"""

import contextvars
import hashlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path

import httpx

SHARED = "http://127.0.0.1:11434"
CURRENT = contextvars.ContextVar("private_vision_process", default=None)
BINARY = Path("/Applications/Ollama.app/Contents/Resources/ollama")
HASHES = {
    "ollama": "add45eb02df0252fb888549d277a66d6b551801869140d1c280bf11689e81b77",
    "llama-server": "c8bbfac5e73a6f04f0dd2d91dde8f9934c0f1526b862f6129703be8d158a25db",
}


def verified_binary():
    for name, sha in HASHES.items():
        path = BINARY.with_name(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            return None
    return BINARY


def host_cache_mib():
    # Experiment only. Never inherit llama.cpp's 8 GiB / unlimited defaults on
    # an 8 GiB Mac; anything except this reviewed bound keeps the old profile.
    return 256 if os.getenv("ECOM_VISION_HOST_CACHE") == "256" else 0


def environment(port):
    value = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR", "LANG") if k in os.environ}
    # Only a trusted local operator's model directory is inherited, never a URL.
    if os.environ.get("OLLAMA_MODELS"):
        value["OLLAMA_MODELS"] = os.environ["OLLAMA_MODELS"]
    return {
        **value,
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "OLLAMA_NO_CLOUD": "true",
        "OLLAMA_FLASH_ATTENTION": "true",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "LLAMA_ARG_CACHE_RAM": str(host_cache_mib()),
    }


def read_local(url, path):
    with (
        httpx.Client(trust_env=False, follow_redirects=False, timeout=1) as c,
        c.stream("GET", url + path) as r,
    ):
        r.raise_for_status()
        body = bytearray()
        for block in r.iter_bytes():
            body.extend(block)
            if len(body) > 2 * 1024**2:
                raise ValueError("本机服务元数据过长")
        return json.loads(body)


class Session:
    def __init__(self, check):
        self.callback = check
        self.candidate = None
        self.process = None
        self.url = None
        self.error = None
        self.stop = threading.Event()
        self.thread = None
        self.record = {
            "backend": "shared_ollama",
            "starts": 0,
            "stops": 0,
            "fallbacks": 0,
            "closed": False,
            "flash_attention": "auto",
            "host_cache_mib": None,
        }

    def check(self):
        from .agent_guard import request_timeout

        request_timeout(30)
        if self.callback:
            self.callback()
        if self.error:
            raise self.error

    def plan(self, model, context_size, verified_memory):
        eligible = (
            os.getenv("ECOM_VISION_PROCESS", "auto") != "shared"
            and os.getenv("ECOM_VISION_ACCELERATION", "auto") != "off"
            and 0 < verified_memory <= 16 * 1024**3
            and context_size <= 3072
        )
        if self.record["fallbacks"] or self.stop.is_set():
            self.candidate = None
            return
        if self.url and (not eligible or self.candidate != model):
            self.close()
            self.record.update(
                backend="mixed_ollama", fallbacks=1, fallback_reason="profile_changed"
            )
            eligible = False
        self.candidate = model if eligible else None

    def endpoint(self, path, payload):
        # Only fixed no-inference cleanup survives cancellation. Prompt-bearing
        # requests still go through both Agent and Analysis admission checks.
        cleanup = (
            path == "/api/generate"
            and isinstance(payload, dict)
            and set(payload) == {"model", "keep_alive"}
            and payload["keep_alive"] == 0
        )
        if not cleanup:
            self.check()
        if (
            path == "/api/chat"
            and self.candidate
            and payload.get("model") != self.candidate["model"]
        ):
            raise ValueError("独立识别的模型发生变化，请重新开始")
        if not self.url and self.candidate and path == "/api/chat":
            try:
                self.start()
            except Exception:
                cleanup_error = None
                try:
                    self.close()
                except Exception as exc:
                    cleanup_error = exc
                    self.record["cleanup_failed"] = True
                self.check()  # Cancellation/deadline is never a silent fallback.
                if cleanup_error:
                    raise ValueError("独立推理进程清理未确认，未开始共享推理") from None
                self.record.update(
                    fallbacks=self.record["fallbacks"] + 1, fallback_reason="startup_unavailable"
                )
                self.candidate = None
        return self.url or SHARED

    def start(self):
        binary = verified_binary()
        if binary is None:
            raise ValueError("尚未验证该本机推理程序版本")
        if read_local(SHARED, "/api/ps")["models"]:
            raise ValueError("保留其他已加载模型，使用原共享服务")
        self.check()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = environment(port)
        self.process = subprocess.Popen(
            [str(binary), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.record["starts"] += 1
        self.record["closed"] = False
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20
        while True:
            self.check()
            if self.process.poll() is not None:
                raise ValueError("本机独立推理服务未启动")
            try:
                if read_local(url, "/api/version").get("version") == "0.35.0":
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("本机独立推理启动超时")
            time.sleep(0.1)
        models = read_local(url, "/api/tags")["models"]
        if not any(
            m.get("name") == self.candidate["model"] and m.get("digest") == self.candidate["digest"]
            for m in models
        ):
            raise ValueError("独立推理模型与已验证模型不一致")
        self.url = url
        self.record.update(
            backend="scoped_ollama",
            flash_attention="on",
            host_cache_mib=int(env["LLAMA_ARG_CACHE_RAM"]),
        )
        context = contextvars.copy_context()
        self.thread = threading.Thread(target=lambda: context.run(self.watch), daemon=True)
        self.thread.start()

    def watch(self):
        while not self.stop.wait(0.5):
            try:
                self.check()
            except Exception as exc:
                self.error = exc
                self.terminate(signal.SIGTERM)
                return

    def terminate(self, sig):
        if self.process:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, sig)

    def close(self):
        self.stop.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(2)
        if self.process:
            try:
                self.terminate(signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.terminate(signal.SIGKILL)
                    self.process.wait(timeout=5)
            except Exception:
                self.record["cleanup_failed"] = True
                raise
            finally:
                # The owned group can still contain a runner after its parent exits.
                self.terminate(signal.SIGKILL)
                self.process = None
                self.url = None
                self.record["stops"] += 1
        self.record["closed"] = not self.record.get("cleanup_failed", False)
