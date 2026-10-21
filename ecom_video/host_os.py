"""Small OS boundaries shared by desktop delivery; no shell/profile loading."""

import os
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"


def venv_python(root):
    return Path(root) / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")


def open_lock(path):
    path = Path(path)
    if path.is_symlink() or (
        path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("锁文件不能是链接或重解析点")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not os.path.samestat(info, path.stat()):
        os.close(fd)
        raise ValueError("锁文件无效")
    return fd


def file_lock(fd, *, exclusive=True, blocking=False):
    if not WINDOWS:
        import fcntl

        fcntl.flock(
            fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if blocking else fcntl.LOCK_NB)
        )
        return
    import ctypes as ct
    import msvcrt
    from ctypes import wintypes as wt

    class Overlapped(ct.Structure):
        _fields_ = [
            ("internal", ct.c_size_t),
            ("internal_high", ct.c_size_t),
            ("offset", wt.DWORD),
            ("offset_high", wt.DWORD),
            ("event", wt.HANDLE),
        ]

    fn = ct.WinDLL("kernel32", use_last_error=True).LockFileEx
    fn.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ct.POINTER(Overlapped)]
    fn.restype = wt.BOOL
    flags = (2 if exclusive else 0) | (0 if blocking else 1)
    if not fn(msvcrt.get_osfhandle(fd), flags, 0, 1, 0, ct.byref(Overlapped())):
        error = ct.get_last_error()
        if error in (33, 997):
            raise BlockingIOError("file lock busy")
        raise ct.WinError(error)
    # Lock lifetime is the open OS handle; closing the fd releases it on both platforms.


def process_options():
    return (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if WINDOWS
        else {"start_new_session": True}
    )


def stop_process(process, grace=3):
    if process.poll() is not None:
        return
    if WINDOWS:
        # No shell; only a PID we own. Kill the tree before its root can exit.
        taskkill = str(Path(os.environ["SYSTEMROOT"]) / "System32/taskkill.exe")
        result = subprocess.run(
            [taskkill, "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        if result.returncode and process.poll() is None:
            raise RuntimeError("未能停止工作进程树，请关闭启动窗口后检查任务管理器")
        process.wait(timeout=15)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


# Keep this non-inheritable handle alive for the launcher/supervisor lifetime.
_WINDOWS_JOB = None


def protect_descendants():
    """Windows window-close/forced exit also kills every child in this job."""
    global _WINDOWS_JOB
    if not WINDOWS or _WINDOWS_JOB is not None:
        return
    import ctypes as ct
    from ctypes import wintypes as wt

    class Limits(ct.Structure):
        _fields_ = [
            ("process_time", ct.c_int64),
            ("job_time", ct.c_int64),
            ("flags", wt.DWORD),
            ("min_working", ct.c_size_t),
            ("max_working", ct.c_size_t),
            ("active_limit", wt.DWORD),
            ("affinity", ct.c_size_t),
            ("priority", wt.DWORD),
            ("scheduling", wt.DWORD),
        ]

    class IO(ct.Structure):
        _fields_ = [
            (name, ct.c_uint64)
            for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
        ]

    class Extended(ct.Structure):
        _fields_ = [
            ("basic", Limits),
            ("io", IO),
            ("process_memory", ct.c_size_t),
            ("job_memory", ct.c_size_t),
            ("peak_process", ct.c_size_t),
            ("peak_job", ct.c_size_t),
        ]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    for name, args, result in [
        ("CreateJobObjectW", [ct.c_void_p, wt.LPCWSTR], wt.HANDLE),
        ("SetInformationJobObject", [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
        ("GetCurrentProcess", [], wt.HANDLE),
        ("AssignProcessToJobObject", [wt.HANDLE, wt.HANDLE], wt.BOOL),
        ("CloseHandle", [wt.HANDLE], wt.BOOL),
    ]:
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("无法建立安全进程组")
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(
        handle, 9, ct.byref(limits), ct.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise OSError("无法建立安全进程组，请不要在限制子进程的宿主中启动")
    _WINDOWS_JOB = handle


def npm_command():
    """Run npm's JS entry with node on Windows, avoiding implicit .cmd shell parsing."""
    if not WINDOWS:
        return ["npm"]
    npm = shutil.which("npm")
    if npm:
        cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if cli.is_file():
            return [shutil.which("node"), str(cli)]
    raise ValueError("未找到 Node.js 自带的 npm-cli.js，请用官方 Node.js 22/24 安装包修复安装")
