"""Exact, local memoization AFTER provider schemas/semantic checks have passed."""

import contextvars
import copy
import functools
import inspect
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .creative import signature
from .media import digest

ACTIVE = contextvars.ContextVar("local_inference_reuse", default=None)
VERSION = "validated-function-v1"
MAX_BYTES = 64 * 1024**2
MAX_ENTRY = 2 * 1024**2


def inputs(value, name=""):
    if isinstance(value, Path) or (
        name in ("reference", "frame", "before", "after") and isinstance(value, str)
    ):
        return {"image_sha256": digest(Path(value))}
    if isinstance(value, dict):
        return {k: inputs(v, k) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [inputs(Path(v) if name == "images" else v) for v in value]
    return value


def frozen(value, folder, name=""):
    if isinstance(value, Path) or (
        name in ("reference", "frame", "before", "after") and isinstance(value, str)
    ):
        source = Path(value)
        sha = digest(source)
        target = folder / (sha + source.suffix)
        shutil.copyfile(source, target)
        if digest(target) != sha:
            raise ValueError("识别图片复制期间发生变化，请重试")
        return target
    if isinstance(value, dict):
        return {k: frozen(v, folder, k) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [frozen(Path(v) if name == "images" else v, folder) for v in value]
    return value


class Reuse:
    def __init__(self, root, check, bypass):
        self.root = Path(root).resolve() / "inference-cache"
        self.check, self.bypass = check, bypass
        self.hits = self.misses = self.errors = 0
        self.inference_seconds = 0.0
        self.used = self.entries = 0
        try:
            if self.root.is_symlink():
                raise OSError("cache symlink")
            self.root.mkdir(mode=0o700, exist_ok=True)
            files = list(self.root.glob("*.json"))
            self.entries = len(files)
            self.used = sum(p.lstat().st_size for p in files)
        except OSError:
            self.errors += 1
            self.used = MAX_BYTES

    def invoke(self, fn, args, kwargs):
        from .agent_guard import request_timeout

        self.check()
        request_timeout(240)  # Cache hits still obey Agent cancellation/deadlines.
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        original_inputs = inputs(bound.arguments)
        key = signature(
            {
                "version": VERSION,
                "function": fn.__module__ + "." + fn.__qualname__,
                "function_code": digest(Path(inspect.getfile(fn))),
                "provider_code": digest(Path(__file__).with_name("vision_model.py")),
                "cache_code": digest(Path(__file__)),
                "inputs": original_inputs,
            }
        )
        path = self.root / (key + ".json")
        if not self.bypass:
            try:
                if self.root.is_symlink() or path.is_symlink() or path.stat().st_size > MAX_ENTRY:
                    raise OSError("unsafe cache entry")
                entry = json.loads(path.read_text())
                if (
                    entry["key"] != key
                    or entry["version"] != VERSION
                    or signature(entry["value"]) != entry["value_sha256"]
                ):
                    raise ValueError("cache checksum mismatch")
                self.check()
                if inputs(bound.arguments) != original_inputs:
                    raise ValueError("识别图片发生变化，请重试")
                self.hits += 1
                return copy.deepcopy(entry["value"])
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError):
                self.errors += 1
        self.misses += 1
        start = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(
                prefix=".model-input-", dir=self.root.parent
            ) as directory:
                snapshot = frozen(bound.arguments, Path(directory))
                if inputs(snapshot) != original_inputs:
                    raise ValueError("识别图片发生变化，请重试")
                value = fn(**snapshot)
        finally:
            self.inference_seconds += time.monotonic() - start
        self.check()
        if inputs(bound.arguments) != original_inputs:
            self.errors += 1
            raise ValueError("识别图片发生变化，请重试；不保存本轮观测")
        payload = json.dumps(
            {"version": VERSION, "key": key, "value": value, "value_sha256": signature(value)},
            ensure_ascii=False,
        )
        if (
            len(payload.encode()) > MAX_ENTRY
            or self.used + len(payload.encode()) > MAX_BYTES
            or self.entries >= 2048
        ):
            return value
        temp = None
        try:
            if self.root.is_symlink() or path.is_symlink():
                raise OSError("unsafe cache target")
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, prefix=".pending-", delete=False
            ) as f:
                temp = Path(f.name)
                f.write(payload)
            self.check()
            os.replace(temp, path)
            self.entries += 1
            self.used += len(payload.encode())
        except OSError:
            self.errors += 1  # Cache availability never replaces the validated live result.
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return value

    def metrics(self):
        return {
            "version": VERSION,
            "hits": self.hits,
            "misses": self.misses,
            "cache_errors": self.errors,
            "inference_seconds": round(self.inference_seconds, 4),
            "forced_inference": self.bypass,
        }


@contextmanager
def scope(root, check, *, bypass=False):
    current = Reuse(root, check, bypass)
    token = ACTIVE.set(current)
    try:
        yield current
    finally:
        ACTIVE.reset(token)


def memoized(fn):
    @functools.wraps(fn)
    def call(*args, **kwargs):
        cache = ACTIVE.get()
        return fn(*args, **kwargs) if cache is None else cache.invoke(fn, args, kwargs)

    return call
