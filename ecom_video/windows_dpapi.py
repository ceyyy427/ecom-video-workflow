"""Current-user Windows DPAPI; no machine-wide encryption or plaintext fallback."""

import ctypes as ct
from ctypes import wintypes as wt


def crypt(raw, *, decrypt=False):
    class Blob(ct.Structure):
        _fields_ = [("size", wt.DWORD), ("data", ct.POINTER(ct.c_ubyte))]

    buffer = ct.create_string_buffer(raw)
    source = Blob(len(raw), ct.cast(buffer, ct.POINTER(ct.c_ubyte)))
    target = Blob()
    library = ct.WinDLL("crypt32", use_last_error=True)
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ct.c_void_p], ct.c_void_p
    fn = library.CryptUnprotectData if decrypt else library.CryptProtectData
    fn.argtypes = [
        ct.POINTER(Blob),
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        wt.DWORD,
        ct.POINTER(Blob),
    ]
    fn.restype = wt.BOOL
    if not fn(ct.byref(source), None, None, None, None, 1, ct.byref(target)):
        raise ValueError("Windows 当前用户凭据保护失败；未使用明文回退")
    try:
        return ct.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)
