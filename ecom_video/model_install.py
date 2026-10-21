"""One bounded, explicitly requested ASR install; only pinned official model files."""

import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path

import httpx

from .customer_setup import import_asr
from .db import Conflict

MAX_BYTES = 900 * 1024**2
MAX_SECONDS = 900


class ModelInstall:
    def __init__(self, project):
        self.project = Path(project)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.progress = {"state": "idle", "bytes": 0, "message": "尚未执行模型安装或校验。"}

    def status(self):
        with self.lock:
            return dict(self.progress)

    def update(self, **values):
        with self.lock:
            self.progress.update(values)

    def start(self):
        with self.lock:
            if self.progress["state"] in ("running", "cancelling"):
                raise Conflict("字幕模型安装正在进行，请等待或取消。")
            self.stop.clear()
            self.progress = {
                "state": "running",
                "bytes": 0,
                "message": "正在校验已有模型；需要下载时使用固定官方来源。",
            }
            threading.Thread(target=self.run, daemon=True).start()
            return dict(self.progress)

    def cancel(self):
        with self.lock:
            if self.progress["state"] == "running":
                self.stop.set()
                self.progress.update(state="cancelling", message="正在取消；不会启用未完成模型。")
            return dict(self.progress)

    def run(self):
        deadline = time.monotonic() + MAX_SECONDS
        total = 0

        def bounded():
            if self.stop.is_set():
                raise InterruptedError
            if time.monotonic() > deadline:
                raise TimeoutError

        def sha(path):
            result = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024**2):
                    bounded()
                    result.update(chunk)
            return result.hexdigest()

        try:
            record = json.loads((self.project / "docs/P5_MODEL.json").read_text())
            target = self.project / "var/models/firered"
            if target.is_symlink():
                raise ValueError
            if target.exists():
                for name, expected in record["files"].items():
                    if (target / name).is_symlink() or sha(target / name) != expected:
                        raise ValueError
                bounded()
                self.update(
                    state="complete", message="已有字幕模型 SHA256 校验通过；未下载或替换。"
                )
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".asr-install-", dir=target.parent) as folder:
                with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
                    for name, expected in record["files"].items():
                        bounded()
                        # Only repository-controlled names and endpoint, never a request parameter.
                        url = f"https://huggingface.co/{record['repo']}/resolve/{record['revision']}/{name}"
                        self.update(message=f"正在下载 {name}；最多15分钟，可取消。")
                        path = Path(folder) / name
                        with client.stream("GET", url) as response, path.open("xb") as output:
                            response.raise_for_status()
                            for chunk in response.iter_bytes():
                                bounded()
                                total += len(chunk)
                                if total > MAX_BYTES:
                                    raise ValueError
                                output.write(chunk)
                                self.update(bytes=total)
                        if sha(path) != expected:
                            raise ValueError
                # Cancellation and commit are serialized; never label a committed install cancelled.
                with self.lock:
                    bounded()
                    import_asr(Path(folder), target, record["files"])
                    self.progress.update(
                        state="complete",
                        message="字幕模型下载并通过 SHA256 校验；没有执行配音识别。",
                    )
        except InterruptedError:
            self.update(state="cancelled", message="已取消；未启用新模型，旧文件保留。")
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            self.update(
                state="failed",
                message="安装未完成。检查网络、磁盘与模型目录；已有目录损坏时请先在 Finder 中移走 firered 目录，再重试。旧文件未改写。",
            )
