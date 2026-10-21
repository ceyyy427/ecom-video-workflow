"""Atomic private credential storage; no network access."""

import base64
import json
import os
import stat
import tempfile
from pathlib import Path

from .host_os import WINDOWS
from .volc_voice import SPEAKERS


def save_config(path, key, speaker, replace=False):
    path = Path(path)
    if (
        not isinstance(key, str)
        or not 1 <= len(key) <= 4096
        or any(not 33 <= ord(char) <= 126 for char in key)
        or speaker not in SPEAKERS
    ):
        raise ValueError("API Key 或音色格式无效。")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".voice-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            data = {"api_key": key, "speaker": speaker}
            if WINDOWS:
                from .windows_dpapi import crypt

                data = {"dpapi_user": base64.b64encode(crypt(json.dumps(data).encode())).decode()}
            else:
                os.fchmod(output.fileno(), 0o600)
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Atomic no-clobber installation; existing config is never opened.
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config(path):
    path = Path(path)
    if path.is_symlink() or (
        path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("配置不能是链接")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > (16384 if WINDOWS else 8192):
            raise ValueError("配置无效")
        if not WINDOWS and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
            raise ValueError("配置权限无效")
        data = json.load(source)
    if WINDOWS:
        from .windows_dpapi import crypt

        # Reject unprotected files, including configs copied from a different OS.
        data = json.loads(crypt(base64.b64decode(data["dpapi_user"], validate=True), decrypt=True))
    return data
