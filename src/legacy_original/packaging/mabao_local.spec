# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path(SPECPATH).parent
icon_path = root.parent / "assets" / "eryou_assistant_icon.ico"

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "bili_guest_hd.user.js"), "."),
        (str(root / "bili_guest_hd.LICENSE"), "."),
        (str(icon_path), "."),
    ],
    hiddenimports=[],
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
    upx=True,
    name="二游辅助",
)
