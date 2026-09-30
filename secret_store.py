# -*- coding: utf-8 -*-
"""密钥加密存储（Windows DPAPI）。

为什么要它
----------
旧版把自定义 API Key 明文写进 team_settings.json。用户截图求助、把配置目录
同步到网盘、或者只是共享这台电脑，Key 就泄露了。

怎么做的
--------
用 Windows 自带的 DPAPI（CryptProtectData / CryptUnprotectData），密钥由系统
按"当前用户"派生并保管，我们不碰、也不存主密钥。换用户或换机器都解不开。

为什么用 ctypes 而不是 pywin32
------------------------------
pywin32 是个大依赖，打包体积已经 273MB 了，为一个加解密函数再塞一个库不划算。
ctypes 是标准库，直接调 crypt32.dll 即可。

存储格式
--------
``dpapi:<base64>`` 前缀 + Base64 密文。带前缀是为了能识别"这条到底加密没有"，
老配置里的明文 Key 仍然读得出来（首次保存时自动升级为密文）。
"""
import base64
import ctypes
import json
from ctypes import wintypes

__all__ = ["protect", "unprotect", "is_protected", "encrypt_value", "decrypt_value",
           "CRYPTPROTECT_UI_FORBIDDEN"]

PREFIX = "dpapi:"
CRYPTPROTECT_UI_FORBIDDEN = 0x1

_IS_WINDOWS = hasattr(ctypes, "windll")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _local_free(blob: _DataBlob) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _crypt(protect_mode: bool, data: bytes) -> bytes:
    """调用 DPAPI。protect_mode=True 加密，False 解密。"""
    if not _IS_WINDOWS:
        raise OSError("DPAPI 只在 Windows 上可用")

    blob_in = _blob_from_bytes(data)
    blob_out = _DataBlob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect_mode else \
        ctypes.windll.crypt32.CryptUnprotectData

    # CryptProtectData(pDataIn, szDescr, pEntropy, pvReserved, pPromptStruct, dwFlags, pDataOut)
    # CryptUnprotectData(pDataIn, ppszDescr, pEntropy, pvReserved, pPromptStruct, dwFlags, pDataOut)
    if protect_mode:
        ok = fn(ctypes.byref(blob_in), None, None, None, None,
                CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        descr = ctypes.c_void_p()
        ok = fn(ctypes.byref(blob_in), ctypes.byref(descr), None, None, None,
                CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if descr:
            ctypes.windll.kernel32.LocalFree(descr)

    if not ok:
        raise OSError("DPAPI 调用失败（错误码 %d）" % ctypes.get_last_error())
    try:
        return _bytes_from_blob(blob_out)
    finally:
        _local_free(blob_out)


def is_protected(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(plaintext: str) -> str:
    """加密一个字符串，返回 ``dpapi:<base64>``。空串原样返回。"""
    if not plaintext:
        return ""
    raw = _crypt(True, plaintext.encode("utf-8"))
    return PREFIX + base64.b64encode(raw).decode("ascii")


def unprotect(value: str) -> str:
    """解密。非密文（老配置里的明文）原样返回，不抛异常。"""
    if not is_protected(value):
        return value or ""
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        return _crypt(False, raw).decode("utf-8", errors="replace")
    except Exception:
        # 换了用户/换了机器就解不开。返回空串让上层提示重新填写，
        # 而不是把异常抛到 UI 上让用户看一串英文。
        return ""


def encrypt_value(value: str) -> str:
    """加密；已经是密文或为空则不动（幂等，避免重复加密）。"""
    if not value or is_protected(value):
        return value or ""
    return protect(value)


def decrypt_value(value: str) -> str:
    return unprotect(value)


def _iter_role_dicts(settings: dict):
    """roles 在 v3 里是有序列表，在 v2 里是字典 —— 两种都要能遍历。"""
    roles = settings.get("roles")
    if isinstance(roles, list):
        return [r for r in roles if isinstance(r, dict)]
    if isinstance(roles, dict):
        return [r for r in roles.values() if isinstance(r, dict)]
    return []


def encrypt_settings(settings: dict, fields=("api_key",), shared_fields=("zai_api_key",)) -> dict:
    """就地加密配置里的密钥字段，返回同一个 dict。

    两处都要处理：每个角色各自的 api_key，以及顶层的共享智谱 Key。
    只加密前者的话，共享 Key 会明文躺在 team_settings.json 里 —— 那正是要避免的事。
    """
    for cfg in _iter_role_dicts(settings):
        for field in fields:
            if cfg.get(field):
                cfg[field] = encrypt_value(cfg[field])
    shared = settings.get("shared")
    if isinstance(shared, dict):
        for field in shared_fields:
            if shared.get(field):
                shared[field] = encrypt_value(shared[field])
    return settings


def decrypt_settings(settings: dict, fields=("api_key",), shared_fields=("zai_api_key",)) -> dict:
    for cfg in _iter_role_dicts(settings):
        for field in fields:
            if cfg.get(field):
                cfg[field] = decrypt_value(cfg[field])
    shared = settings.get("shared")
    if isinstance(shared, dict):
        for field in shared_fields:
            if shared.get(field):
                shared[field] = decrypt_value(shared[field])
    return settings


if __name__ == "__main__":
    sample = "sk-test-中文-1234567890"
    blob = protect(sample)
    print("明文   :", sample)
    print("密文   :", blob[:60] + "...")
    print("解密回来:", unprotect(blob))
    print("往返一致:", unprotect(blob) == sample)
    print("明文透传:", unprotect("plain-old-key") == "plain-old-key")
    print("幂等    :", encrypt_value(blob) == blob)
    print("坏密文不炸:", repr(unprotect(PREFIX + "bm90LWEtcmVhbC1ibG9i")))
    d = {"roles": {"a": {"api_key": "secret1"}, "b": {"api_key": ""}}}
    json.dumps(encrypt_settings(d))          # 确认可 JSON 序列化
    print("配置往返:", decrypt_settings(d)["roles"]["a"]["api_key"] == "secret1")
