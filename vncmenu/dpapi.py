"""Protecao das credenciais UltraVNC via DPAPI do Windows.

Sem dependencias internas. Em outros sistemas crypt32 fica None e as
funcoes levantam RuntimeError.
"""

import base64
import ctypes
from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


try:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
except Exception:
    crypt32 = None
    kernel32 = None


CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob._buffer = buf  # mantém o buffer vivo durante a chamada DPAPI
    return blob


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if kernel32:
            kernel32.LocalFree(blob.pbData)


def dpapi_encrypt(plaintext: str) -> str:
    if crypt32 is None:
        raise RuntimeError("DPAPI disponível apenas no Windows.")
    data = plaintext.encode("utf-8")
    in_blob = _bytes_to_blob(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    return base64.b64encode(_blob_to_bytes(out_blob)).decode("ascii")


def dpapi_decrypt(ciphertext_b64: str) -> str:
    if crypt32 is None:
        raise RuntimeError("DPAPI disponível apenas no Windows.")
    data = base64.b64decode(ciphertext_b64.encode("ascii"))
    in_blob = _bytes_to_blob(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    return _blob_to_bytes(out_blob).decode("utf-8")
