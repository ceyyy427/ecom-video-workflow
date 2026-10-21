"""OS-backed secrets only. No plaintext fallback, no secrets in command arguments."""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from ..host_os import file_lock, open_lock
from .macos_keychain import operate

SERVICE = "ecom-video-workflow-qianchuan"


class SecretStore:
    def __init__(self, root):
        self.namespace = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]

    def available(self):
        return bool(
            True  # Security.framework is in the macOS dyld shared cache.
            if platform.system() == "Darwin"
            else shutil.which("secret-tool")
            if platform.system() == "Linux"
            else False
        )

    def _name(self, key):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", key):
            raise ValueError("凭据引用无效")
        return self.namespace + "-" + key

    def _run(self, args, payload=None, missing=False):
        try:
            r = subprocess.run(args, input=payload, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("系统安全凭据存储不可用，请检查钥匙串/Secret Service") from None
        if r.returncode:
            if missing and (
                (platform.system() == "Darwin" and r.returncode == 44)
                or (platform.system() == "Linux" and r.returncode == 1)
            ):
                return b""
            raise ValueError("系统安全凭据存储拒绝操作；未使用明文回退")
        return r.stdout

    def read(self, key):
        name = self._name(key)
        if not self.available():
            raise ValueError("需要 macOS Keychain 或 Linux Secret Service")
        raw = (
            operate("read", SERVICE, name)
            if platform.system() == "Darwin"
            else self._run(
                ["secret-tool", "lookup", "service", SERVICE, "account", name], missing=True
            )
        )
        try:
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError):
            raise ValueError("系统凭据格式无效，请重新配置授权") from None

    def write(self, key, value):
        name = self._name(key)
        if not self.available():
            raise ValueError("需要 macOS Keychain 或 Linux Secret Service")
        raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
        if platform.system() == "Darwin":
            operate("write", SERVICE, name, raw)
        else:
            self._run(
                [
                    "secret-tool",
                    "store",
                    "--label=Ecom video Qianchuan",
                    "service",
                    SERVICE,
                    "account",
                    name,
                ],
                raw + b"\n",
            )
        if self.read(key) != value:
            raise ValueError("安全凭据写入校验失败")

    def delete(self, key):
        name = self._name(key)
        if not self.available():
            raise ValueError("系统安全凭据存储不可用")
        if platform.system() == "Darwin":
            operate("delete", SERVICE, name)
        else:
            self._run(["secret-tool", "clear", "service", SERVICE, "account", name], missing=True)


@contextmanager
def credential_lock(home):
    # Same root lock serializes configure/callback/refresh across API and worker processes.

    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "credentials.lock"
    with os.fdopen(open_lock(path), "r+b") as file:
        path.chmod(0o600)
        file_lock(file.fileno(), blocking=True)
        try:
            yield
        finally:
            pass  # Closing this handle releases the OS lock.


@contextmanager
def task_ownership(root, task_id):
    """Nonblocking OS ownership covers dispatch through completion, even past lease expiry.

    Recovery and manual reconciliation use the same lock. A paused live process
    cannot be declared absent and then resume sending after human reconciliation.
    Process termination releases the OS lock; it is never inferred from elapsed time.
    """

    if not re.fullmatch(r"[0-9a-f]{32}", task_id):
        raise ValueError("任务 ID 无效")
    directory = Path(root) / "integrations" / "qianchuan" / "ownership"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (task_id + ".lock")
    with os.fdopen(open_lock(path), "r+b") as file:
        path.chmod(0o600)
        try:
            file_lock(file.fileno())
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            pass  # Closing this handle releases the OS lock.
