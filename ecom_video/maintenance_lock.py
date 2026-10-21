"""Cross-process admission lock: production shares, maintenance excludes."""

import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .host_os import file_lock, open_lock


class MaintenanceBusy(ValueError):
    pass


def acquire(root, *, exclusive=False):
    fd = open_lock(Path(root) / ".maintenance.lock")
    try:
        file_lock(fd, exclusive=exclusive)
        return fd
    except BlockingIOError:
        os.close(fd)
        raise MaintenanceBusy("维护或制作操作仍在进行，请等待完成后重试。") from None
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def hold(root, *, exclusive=False):
    fd = acquire(root, exclusive=exclusive)
    try:
        yield
    finally:
        os.close(fd)


def worker_guard(root):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                fd = acquire(root(*args, **kwargs))
            except MaintenanceBusy:
                return False
            try:
                return fn(*args, **kwargs)
            finally:
                os.close(fd)

        return wrapped

    return decorate
