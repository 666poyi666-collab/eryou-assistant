"""探测：能否用本机 Python 3.12 + 便携版 _internal 里的依赖，导入原始 app 模块。

如果这个能跑通，就能用 PyInstaller 重新打包（把 src/legacy_original 里的修复真正装进 exe）。
"""

from __future__ import annotations

import os
import sys

INTERNAL = r"C:\Users\16408\Desktop\二游自动\03_二游辅助\app\_internal"

sys.path.insert(0, INTERNAL)
dll_dirs = [
    INTERNAL,
    os.path.join(INTERNAL, "win32"),
    os.path.join(INTERNAL, "Pythonwin"),
    os.path.join(INTERNAL, "PyQt5", "Qt5", "bin"),
    os.path.join(INTERNAL, "numpy.libs"),
    os.path.join(INTERNAL, "pywin32_system32"),
]
for path in dll_dirs:
    if os.path.isdir(path):
        try:
            os.add_dll_directory(path)
        except OSError:
            pass
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
os.environ["QT_PLUGIN_PATH"] = os.path.join(INTERNAL, "PyQt5", "Qt5", "plugins")
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(INTERNAL, "PyQt5", "Qt5", "plugins", "platforms")

MODULES = [
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "pythonnet",
    "clr_loader",
    "qtwebview2",
    "numpy",
    "cv2",
    "onnxruntime",
    "requests",
    "bs4",
    "lxml",
    "jsonschema",
    "PIL",
    "scipy",
    "yaml",
    "zstandard",
    "win32com",
    "wmi",
    "app.logger",
    "app.settings",
    "app.main_window",
    "qtwebview2.widget",
]

print("python:", sys.version.split()[0], flush=True)
for name in MODULES:
    try:
        module = __import__(name)
        origin = getattr(module, "__file__", "?")
        print(f"OK   {name:22} {origin}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name:22} {type(exc).__name__}: {str(exc)[:150]}", flush=True)
