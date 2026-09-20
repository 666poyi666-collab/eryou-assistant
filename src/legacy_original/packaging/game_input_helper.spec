# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "elevated_input_helper.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PyQt5", "PySide6", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mabao-game-input-helper",
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
)
