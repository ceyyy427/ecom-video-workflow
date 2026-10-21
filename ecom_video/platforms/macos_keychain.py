"""Minimal macOS Security.framework binding; secrets never enter process argv."""

import ctypes as ct


def operate(action, service, account, value=None):
    cf = ct.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    sec = ct.CDLL("/System/Library/Frameworks/Security.framework/Security")
    ptr = ct.c_void_p
    functions = [
        (cf, "CFStringCreateWithCString", [ptr, ct.c_char_p, ct.c_uint32], ptr),
        (cf, "CFDataCreate", [ptr, ptr, ct.c_long], ptr),
        (cf, "CFDataGetLength", [ptr], ct.c_long),
        (cf, "CFDataGetBytePtr", [ptr], ptr),
        (cf, "CFDictionaryCreateMutable", [ptr, ct.c_long, ptr, ptr], ptr),
        (cf, "CFDictionarySetValue", [ptr, ptr, ptr], None),
        (cf, "CFRelease", [ptr], None),
        (sec, "SecItemAdd", [ptr, ptr], ct.c_int32),
        (sec, "SecItemUpdate", [ptr, ptr], ct.c_int32),
        (sec, "SecItemDelete", [ptr], ct.c_int32),
        (sec, "SecItemCopyMatching", [ptr, ct.POINTER(ptr)], ct.c_int32),
    ]
    for library, name, args, result in functions:
        function = getattr(library, name)
        function.argtypes = args
        function.restype = result
    refs = []

    def constant(name):
        return ptr.in_dll(sec, name).value

    def string(text):
        result = cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)
        refs.append(result)
        return result

    def dictionary(values):
        # No callbacks: all values stay alive in refs until every operation completes.
        result = cf.CFDictionaryCreateMutable(None, 0, None, None)
        refs.append(result)
        for key, val in values.items():
            cf.CFDictionarySetValue(result, constant(key), val)
        return result

    def check(status, missing=False):
        if status and not (missing and status == -25300):
            raise ValueError("系统钥匙串拒绝操作，请检查登录钥匙串及访问授权")

    try:
        query = dictionary(
            {
                "kSecClass": constant("kSecClassGenericPassword"),
                "kSecAttrService": string(service),
                "kSecAttrAccount": string(account),
            }
        )
        if action == "read":
            cf.CFDictionarySetValue(
                query, constant("kSecReturnData"), ptr.in_dll(cf, "kCFBooleanTrue").value
            )
            cf.CFDictionarySetValue(
                query, constant("kSecMatchLimit"), constant("kSecMatchLimitOne")
            )
            result = ptr()
            status = sec.SecItemCopyMatching(query, ct.byref(result))
            check(status, True)
            if status == -25300:
                return b""
            refs.append(result.value)
            return ct.string_at(cf.CFDataGetBytePtr(result), cf.CFDataGetLength(result))
        if action == "delete":
            check(sec.SecItemDelete(query), True)
            return b""
        if action != "write" or not isinstance(value, bytes):
            raise ValueError("无效钥匙串操作")
        data = cf.CFDataCreate(None, value, len(value))
        refs.append(data)
        update = dictionary({"kSecValueData": data})
        status = sec.SecItemUpdate(query, update)
        if status == -25300:
            cf.CFDictionarySetValue(query, constant("kSecValueData"), data)
            status = sec.SecItemAdd(query, None)
        check(status)
        return b""
    finally:
        for ref in reversed(refs):
            if ref:
                cf.CFRelease(ref)
