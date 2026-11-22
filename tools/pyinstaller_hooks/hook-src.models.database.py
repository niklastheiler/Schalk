# PyInstaller hook (build.bat: --additional-hooks-dir tools\pyinstaller_hooks).
# cryptography (imported by src.models.database) ships for Python 3.15 only a wheel for the stable ABI "abi3t",
# whose _rust.pyd loads python3t.dll. PyInstaller does not find this DLL by itself, and without it Schalk.exe
# cannot start ("DLL load failed while importing _rust"). It lies next to python.exe of the Python installation.
import os
import sys

_candidates = [os.path.join(folder, "python3t.dll") for folder in
               dict.fromkeys((sys.base_prefix, os.path.dirname(sys._base_executable), sys.prefix,
                              os.path.join(sys.base_prefix, "DLLs")))]
_found = [path for path in _candidates if os.path.isfile(path)]
if sys.version_info >= (3, 15) and not _found:
    raise SystemExit("python3t.dll nicht gefunden, gesucht in: " + ", ".join(_candidates))
print("Schalk-Hook: python3t.dll ->", _found[0] if _found else "nicht nötig")
binaries = [(_found[0], ".")] if _found else []
