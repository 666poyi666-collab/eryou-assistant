# -*- mode: python ; coding: utf-8 -*-
"""重建「二游辅助」便携版的 exe（不含依赖，依赖复用已有便携包的 _internal）。

为什么需要这个 spec：
  * 原版 `mabao_local.spec` 依赖 `C:\\Program Files (x86)\\LanRenMaBao` 里的运行时，
    那台机器上已经没有这份安装；但我们已经有一份能跑的便携包，它的 _internal
    就是「原版运行时 + 本地补丁 + 兼容版 numpy/cv2/onnxruntime」，可以直接复用。
  * PyInstaller 只分析 launcher.py / local_features.py 的导入，会漏掉原版 PYZ 里
    那些 stdlib 模块（fileinput、asyncio、multiprocessing…）。build/inspect_pyz.py
    会算出缺失清单写到 build/hiddenimports_stdlib.json，这里读进来补上。
"""

import json
import os
from pathlib import Path

spec_dir = Path(SPECPATH)                  # src/legacy_original/packaging
legacy_root = spec_dir.parent              # src/legacy_original
project_root = legacy_root.parent          # src
repo_root = project_root.parent            # 03_二游辅助
build_root = repo_root / "build"

hidden_path = build_root / "hiddenimports_stdlib.json"
hiddenimports = []
if hidden_path.is_file():
    hiddenimports = json.loads(hidden_path.read_text(encoding="utf-8"))

icon_path = project_root / "assets" / "eryou_assistant_icon.ico"

a = Analysis(
    [str(legacy_root / "launcher.py")],
    pathex=[str(legacy_root)],
    binaries=[],
    datas=[
        (str(legacy_root / "bili_guest_hd.user.js"), "."),
        (str(legacy_root / "bili_guest_hd.LICENSE"), "."),
        (str(icon_path), "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="二游辅助",
    icon=str(icon_path),
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="二游辅助",
)
