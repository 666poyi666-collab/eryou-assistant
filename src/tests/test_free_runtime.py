from __future__ import annotations

from pathlib import Path

FORBIDDEN_RUNTIME_MARKERS = (
    "TiandunAuth",
    "ENCRYPT_KEY",
    "DECRYPT_KEY",
    "start_heartbeat",
    "saved_card",
    "卡密登录",
    "购买卡密",
    "发现新版本",
    "会员权限",
    "QSplashScreen",
    "广告",
    "推广",
    "开屏",
    "particle",
    "粒子",
)


def test_runtime_has_no_paid_auth_markers() -> None:
    source_root = Path(__file__).parents[1] / "src"
    runtime = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
    ).casefold()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        assert marker.casefold() not in runtime


def test_browser_uses_free_webview2_wrapper_without_qt_webengine() -> None:
    project_root = Path(__file__).parents[1]
    project_config = (project_root / "pyproject.toml").read_text(encoding="utf-8").casefold()
    browser_source = (project_root / "src/eryou_assistant/ui/pages.py").read_text(encoding="utf-8")
    assert "qtwebview2" in project_config
    assert "pythonnet" in project_config
    assert "QtWebEngine" not in browser_source


def test_local_bundle_is_per_user_and_excludes_optional_ai() -> None:
    project_root = Path(__file__).parents[1]
    build_script = (project_root / "scripts" / "build-local.ps1").read_text(encoding="utf-8")
    spec = (project_root / "packaging" / "eryou_assistant.spec").read_text(encoding="utf-8")

    assert "LOCALAPPDATA" in build_script
    assert "Path(SPECPATH).parent\n" in spec
    assert 'includes=["translations/qtbase_*.qm"]' in spec
    assert "uac_admin=False" in spec
    for excluded in ("cv2", "numpy", "onnxruntime"):
        assert excluded in spec
    assert "include_ai" in spec
    assert "WithAI" in build_script
    assert "eryou_assistant_icon.ico" in spec
    assert "icon=str(icon_path)" in spec


def test_product_identity_is_eryou_assistant() -> None:
    project_root = Path(__file__).parents[1]
    assert (project_root / "assets" / "eryou_assistant_icon.svg").is_file()
    assert (project_root / "assets" / "eryou_assistant_icon.ico").is_file()
    legacy_spec = (project_root / "legacy_original" / "packaging" / "mabao_local.spec").read_text(
        encoding="utf-8"
    )
    legacy_build = (project_root / "legacy_original" / "build-local.ps1").read_text(
        encoding="utf-8"
    )
    assert 'name="二游辅助"' in legacy_spec
    assert "Programs\\MabaoLocal" in legacy_build
    assert "二游辅助.lnk" in legacy_build


def test_local_uninstaller_is_scoped_to_eryou_assistant() -> None:
    project_root = Path(__file__).parents[1]
    uninstall_script = (project_root / "scripts" / "uninstall-local.ps1").read_text(
        encoding="utf-8"
    )

    assert "LOCALAPPDATA" in uninstall_script
    assert "expectedRoot" in uninstall_script
    assert "LanRenMaBao" not in uninstall_script
