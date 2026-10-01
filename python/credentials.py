"""Host-bound tokens: Windows DPAPI or Linux Secret Service, never plaintext."""
import base64
import ctypes
from ctypes import wintypes
import os
import re
import shutil
from runtime_safety import run_process


def normalize_host(host):
    host = (host or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?", host):
        raise ValueError("Informe o host GitLab, por exemplo gitlab.empresa.com, sem protocolo ou caminho.")
    return host


def _dpapi(data, encrypt):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def _secret(*args, input=None):
    binary = shutil.which("secret-tool")
    if not binary:
        raise RuntimeError("Secret Service indisponivel: instale secret-tool ou use token e host por variaveis de ambiente.")
    result = run_process([binary, *args], input=input, timeout=15)
    if result.returncode:
        raise RuntimeError("Falha no cofre de credenciais do sistema.")
    return result.stdout.strip()


def store(host, token):
    host = normalize_host(host)
    if os.name == "nt":
        return {"host": host, "backend": "dpapi", "value": base64.b64encode(_dpapi(token.encode(), True)).decode()}
    _secret("store", "--label=Git AutoSync", "application", "git-autosync", "host", host, input=token)
    return {"host": host, "backend": "secret-service"}


def resolve(record, host):
    if not record or record.get("host") != normalize_host(host):
        return None
    if record.get("backend") == "dpapi" and os.name == "nt":
        return _dpapi(base64.b64decode(record["value"]), False).decode()
    if record.get("backend") == "secret-service":
        return _secret("lookup", "application", "git-autosync", "host", host)
    raise RuntimeError("Cofre de credenciais incompativel com este sistema.")


def clear(record):
    if record and record.get("backend") == "secret-service":
        _secret("clear", "application", "git-autosync", "host", normalize_host(record["host"]))
