import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


project_root = Path(SPECPATH).parent
source_root = project_root / "src"
icon_path = project_root / "assets" / "eryou_assistant_icon.ico"
include_ai = os.environ.get("ERYOU_INCLUDE_AI") == "1"
ai_modules = ["cv2", "numpy", "onnxruntime"]
webview_datas, webview_binaries, webview_hiddenimports = collect_all("qtwebview2")
webview_root_datas = [
    (source, destination.removeprefix("qtwebview2\\"))
    for source, destination in collect_data_files("qtwebview2", includes=["lib/**/*"])
]

analysis = Analysis(
    [str(source_root / "eryou_assistant" / "__main__.py")],
    pathex=[str(source_root)],
    datas=(
        collect_data_files("PySide6", includes=["translations/qtbase_*.qm"])
        + collect_data_files("eryou_assistant", includes=["resources/**/*"])
        + webview_datas
        + webview_root_datas
        + [(str(project_root / "THIRD_PARTY_NOTICES.md"), ".")]
        + [(str(icon_path), "eryou_assistant/resources")]
    ),
    binaries=webview_binaries,
    hiddenimports=webview_hiddenimports + (ai_modules if include_ai else []),
    excludes=[] if include_ai else ai_modules,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="二游辅助",
    icon=str(icon_path),
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="二游辅助",
)
