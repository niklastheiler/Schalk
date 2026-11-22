# PyInstaller hook (build.bat: --additional-hooks-dir tools\pyinstaller_hooks).
# cryptography (imported by src.models.database) ships for Python 3.15 only a wheel for the stable ABI "abi3t",
# whose _rust.pyd loads python3t.dll. PyInstaller does not find this DLL by itself, and without it Schalk.exe
# cannot start ("DLL load failed while importing _rust"). Where the DLL lies differs between Python
# installations, so it is loaded here like at runtime and Windows is asked for the file it used.
import ctypes
import importlib
import sys


def _loaded_path(name: str):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    handle = kernel32.GetModuleHandleW(name)
    if not handle:
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(handle, buffer, len(buffer))
    return buffer.value[:length] if length else None


binaries = []
if sys.platform == "win32":
    # Loads python3t.dll if the installed wheel needs it
    importlib.import_module("cryptography.hazmat.bindings._rust")
    path = _loaded_path("python3t.dll")
    if path:
        print("Schalk-Hook: python3t.dll ->", path)
        binaries = [(path, ".")]
    elif sys.version_info >= (3, 15):
        print("Schalk-Hook: python3t.dll wird nicht geladen, nichts zu tun")
