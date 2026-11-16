"""Save the review connection in local settings with a Windows-protected key."""

import base64
import ctypes
import json
import os
from ctypes import wintypes

from PySide6.QtCore import QSettings

from .review_cloud import CloudConfig, DEFAULT_MODEL, environment_key

CONNECTION = "review/connection"


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.argtypes = (ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob))
    operation.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = DataBlob(len(data), buffer), DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN, with the default current-user scope.
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    local_free = ctypes.WinDLL("kernel32").LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        local_free(result.data)


def load_connection(settings: QSettings) -> tuple[CloudConfig, str]:
    saved = settings.value(CONNECTION, "", str)
    if not saved:
        url = (os.environ.get("NOTEFLOW_REVIEW_BASE_URL")
               or settings.value("review/base_url", "", str)).strip().rstrip("/")
        model = os.environ.get("NOTEFLOW_REVIEW_MODEL") or settings.value("review/model", DEFAULT_MODEL, str)
        return CloudConfig(url, model, environment_key(url)), ""
    try:
        data = json.loads(saved)
        url, model, protocol, encrypted = (data[name] for name in ("base_url", "model", "protocol", "key"))
        if not all(isinstance(value, str) for value in (url, model, protocol, encrypted)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return CloudConfig(""), "无法读取本机云端模型设置，请重新填写。"
    try:
        key = _crypt(base64.b64decode(encrypted, validate=True), protect=False).decode() if encrypted else ""
    except (OSError, ValueError):
        return CloudConfig(url, model, protocol=protocol), "当前 Windows 用户无法读取已保存的 API Key，请重新填写。"
    return CloudConfig(url, model, key, protocol), ""


def save_connection(settings: QSettings, config: CloudConfig) -> None:
    try:
        key = base64.b64encode(_crypt(config.api_key.encode(), protect=True)).decode() if config.api_key else ""
    except OSError:
        raise ValueError("Windows 无法加密保存 API Key，请检查当前用户的本机配置。") from None
    settings.setValue(CONNECTION, json.dumps({
        "base_url": config.base_url, "model": config.model, "protocol": config.protocol, "key": key,
    }))
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise ValueError("无法写入本机云端模型设置，请检查当前用户的写入权限。")
