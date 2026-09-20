import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from launcher import (  # noqa: E402
    SINGLE_INSTANCE_MUTEX,
    acquire_single_instance,
    clamp_ai_region_origin,
    fit_ai_region_size,
    load_bilibili_guest_hd_script,
    normalize_capture_image,
    orb_locate_center,
    rewrite_bilibili_playurl,
    should_prevent_window_activation,
)
from local_features import (  # noqa: E402
    PLAYBACK_RATES,
    RI_MOUSE_BUTTON_4_DOWN,
    RI_MOUSE_BUTTON_5_DOWN,
    VK_OEM_3,
    WM_KEYDOWN,
    NativeInputBridge,
    PlaybackSpeedState,
    actions_from_mouse_flags,
    debounce_action,
    is_game_window,
    keyboard_action,
    playback_speed_script,
)


def test_launcher_skips_remote_entitlement_and_splash() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "UpdateChecker" not in source
    assert "AuthDialog" not in source
    assert "_local_full_access = True" in source
    assert "particle.play_show_effect = no_show_effect" in source
    assert "if callable(on_finished):" in source
    assert "on_finished()" in source
    assert "get_particle_effect_show = lambda self: False" in source
    assert '"账号信息"' in source
    assert '"取消自动登录"' in source
    assert '"发现新版本"' in source
    assert "widget.hide()" in source


def test_launcher_enforces_one_media_process() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert SINGLE_INSTANCE_MUTEX == r"Local\MabaoLocalMainWindow"
    assert callable(acquire_single_instance)
    assert "CreateMutexW" in source
    assert "activate_existing_instance()" in source
    assert "QueryFullProcessImageNameW" in source
    assert "same_executable = executable == current_executable" in source
    assert "if not is_primary:" in source
    assert "CloseHandle(instance_mutex)" in source


def test_media_controls_never_autoplay_or_leave_hidden_audio_running() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "module._UNMUTE_SCRIPT = MEDIA_SINGLETON_SCRIPT" in source
    assert "document.querySelectorAll('video,audio')" in source
    assert "document.addEventListener('play', window.__mabaoMediaPlayGuard, true)" in source
    assert "main_window.MainWindow._pause_video_only = pause_all_media" in source
    assert "main_window.MainWindow.toggle_play = toggle_primary_media" in source
    assert "active.play()" in source
    singleton = source.split('MEDIA_SINGLETON_SCRIPT = r"""', 1)[1].split('"""', 1)[0]
    assert ".play()" not in singleton


def test_original_install_is_read_only_input() -> None:
    script = (ROOT / "build-local.ps1").read_text(encoding="utf-8")
    assert "OriginalRuntime" in script
    assert "3E1E2181D967650646FF8739C9CEF8D4F74E0C6BA5610676794530DE968EBD1D" in script
    assert "Copy-Item -LiteralPath $bundleRoot" in script
    assert "Programs\\MabaoLocal" in script
    assert "InstallRoot must be ASCII" in script
    assert "forbiddenModules" in script
    assert "$moduleCount -ne $expectedModuleCount" in script
    assert "$appModuleCount -ne 53" in script
    assert "namespacePackages" in script
    assert "game_input_helper.spec" in script
    assert "mabao-game-input-helper.exe" in script
    assert "compatibleCv2" in script
    assert "opencv_videoio_ffmpeg4140_64.dll" in script
    assert "Compatible OpenCV copy failed" in script
    assert "compatibleNumpy" in script
    assert "compatibleNumpyLibs" in script
    assert "Compatible NumPy copy failed" in script
    assert "Compatible NumPy DLL copy failed" in script
    assert "compatibleOnnxruntime" in script
    assert "Compatible ONNX Runtime copy failed" in script
    assert "Bundled NumPy/OpenCV/ONNX Runtime ABI smoke test failed" in script
    assert "NumPy ABI inventory mismatch" in script
    assert "compatibleRuntimeFiles" in script
    assert "MSVCP140.dll" in script
    assert "VCRUNTIME140.dll" in script
    assert "ucrtbase.dll" in script
    assert "Compatible runtime file is missing" in script
    assert "runtimeDirectories" in script
    assert "DirectoryName" in script
    assert "runtimeAssets" in script
    assert "bili_guest_hd.user.js" in script
    assert "bili_guest_hd.LICENSE" in script
    assert "eryou_assistant_icon.ico" in script
    assert "abi_smoke.py" in script
    assert "multiarrayFiles.Count -ne 1" in script
    abi_smoke = (ROOT / "tools" / "abi_smoke.py").read_text(encoding="utf-8")
    assert "numpy.random" in abi_smoke
    assert "onnxruntime" in abi_smoke


def test_original_feature_module_inventory_is_required() -> None:
    script = (ROOT / "build-local.ps1").read_text(encoding="utf-8")
    modules = (
        "direction_reminder",
        "enhanced_reminder",
        "subtitle_parser",
        "turn_reminder",
        "hotkey_manager",
        "bookmark_manager",
        "history_manager",
        "theme\\theme_manager",
        "immersive_anti_occlude",
        "immersive_dodge",
        "immersive_hole",
        "auto_dialog\\manager",
        "auto_dialog\\learning_window",
        "auto_dialog\\runner",
        "auto_dialog\\template_match",
        "ai_nav\\ai_nav_worker",
        "ai_nav\\ai_region_selector",
        "ai_nav\\locator",
        "webview_container",
    )
    for module in modules:
        assert f"app\\{module}.pyc" in script


def test_bilibili_guest_script_is_available_from_local_bundle() -> None:
    script = load_bilibili_guest_hd_script()
    assert "__mabaoBiliOverdriveLoaded" in script


def test_bilibili_playurl_rewrite_uses_anonymous_1080p_preview() -> None:
    source = (
        "https://api.bilibili.com/x/player/wbi/playurl?bvid=BV1xx&cid=42&qn=16&w_rid=signed&wts=123"
    )
    rewritten = rewrite_bilibili_playurl(source)
    assert "/x/player/playurl?" in rewritten
    assert "qn=80" in rewritten
    assert "fnval=4048" in rewritten
    assert "try_look=1" in rewritten
    assert "w_rid=" not in rewritten
    assert "wts=" not in rewritten
    assert rewrite_bilibili_playurl("https://example.com/x/player/playurl?qn=16") == (
        "https://example.com/x/player/playurl?qn=16"
    )


def test_original_auth_and_particle_implementations_are_excluded() -> None:
    source = (ROOT / "tools" / "extract_original.py").read_text(encoding="utf-8")
    for module in ("app.auth", "app.dialogs.auth_dialogs", "tiandun", "app.particle_splash"):
        assert f'"{module}"' in source
    stub = (ROOT / "overrides" / "app" / "particle_splash.py").read_text(encoding="utf-8")
    assert "return None" in stub
    assert "QTimer" not in stub
    auth_stub = (ROOT / "overrides" / "app" / "dialogs" / "auth_dialogs.py").read_text(
        encoding="utf-8"
    )
    assert "class LoginDialog" in auth_stub
    assert "QDialog.Rejected" in auth_stub
    assert "TiandunAuth" not in auth_stub


def test_namespace_packages_are_not_written_as_invalid_pyc() -> None:
    source = (ROOT / "tools" / "extract_original.py").read_text(encoding="utf-8")
    assert "if code is None:" in source
    assert 'output.joinpath(*name.split(".")).mkdir' in source


def test_runtime_fixes_are_installed_before_main_window() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    main_window_import = source.index('importlib.import_module("app.main_window")')
    assert source.index("setup_runtime_logging()") < main_window_import
    assert source.index("force_cpu_onnxruntime()") < main_window_import
    assert source.index("extend_original_hotkey_names()") < main_window_import
    assert source.index("enable_ai_navigation_defaults()") < main_window_import
    assert source.index("install_web_runtime(playback_state)") < main_window_import
    assert "install_playback_hotkey_lifecycle(main_window, playback_state)" in source
    assert "original = main_window.MainWindow._init_hotkeys" in source
    assert "install_playback_hotkey(self, playback_state)" in source
    assert "MABAO_LOCAL_SELF_TEST" in source
    assert "SELF_TEST_PASS" in source
    assert "install_safe_close(main_window)" in source
    assert "install_document_start_script()" in source
    assert "native_input_bridge = start_native_input()" in source
    assert "install_native_input(window, qt_core, native_input_bridge)" in source
    assert "WA_ShowWithoutActivating" in source
    assert "sync_game_no_activate" not in source
    assert "WS_EX_NOACTIVATE" not in source
    assert 'ELEVATED_INPUT_HELPER_ENV = "MABAO_ENABLE_ELEVATED_INPUT_HELPER"' in source
    assert 'os.environ.get(ELEVATED_INPUT_HELPER_ENV, "").strip() != "1"' in source
    assert "AddScriptToExecuteOnDocumentCreatedAsync" in source
    assert "Bilibili guest script registration queued" in source
    assert "load_bilibili_guest_hd_script()" in source
    assert "Bilibili guest script registration queued" in source
    assert "Bilibili runtime probe:" in source
    assert "NativeInputBridge" in source
    assert "self._shutdown_ai_nav(force_terminate=True)" in source
    assert '["CPUExecutionProvider"]' in source
    assert 'default_settings_path().parent / "logs"' in source
    assert "log_dir.mkdir(parents=True, exist_ok=True)" in source
    assert 'window.hotkey_manager.register("=", "cycle_playback_speed"' in source
    assert "MutationObserver" in source
    assert "_local_initial_navigation_done" in source
    assert "LOCAL_HOME_HTML" in source
    assert 'app.setApplicationName("二游辅助")' in source
    assert "install_application_identity(app, qt_gui)" in source
    assert "install_settings_focus_guard(main_window, qt_core, native_input_bridge)" in source
    assert "guarded_activate" in source
    assert "install_ai_navigation_runtime(main_window, qt_core, qt_gui)" in source
    assert "AI_NAV_INTERVAL_MS = 500" in source
    assert "AI_NAV_DEFAULT_SIZE = 180" in source
    assert "AI_NAV_MIN_SIZE = 72" in source
    assert "AI_NAV_SAVE_DEBOUNCE_MS" in source
    assert "_mabao_follow_pending" in source
    assert "AI navigation result:" in source
    assert "AI navigation locator fallback: backend=orb" in source
    assert "AI navigation capture timer active" in source
    assert "orb-only (XFeat unavailable)" in source
    assert "screenshot_module.capture_window_region" in source
    assert "open_selector_without_activation" in source
    assert "event_type == qt_core.QEvent.Wheel" in source
    assert "暂未匹配到地图" in source
    assert "_local_ui_sanitizer_timer = None" in source
    assert "worker_module.ensure_bgr = ensure_bgr_capture" in source
    assert "frame skipped" in source
    assert "_mabao_models_attempted" in source
    assert "using safe fallback" in source
    assert "if xfeat is not orb_only_sentinel" in source
    assert "self.grabMouse()" in source
    assert "self.releaseMouse()" in source
    assert "event_type == qt_core.QEvent.MouseMove" in source
    assert 'getattr(worker, "_busy", False)' in source


def test_playback_speed_cycles_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    state = PlaybackSpeedState(path)
    assert state.rate == 1.0
    assert [state.cycle() for _ in PLAYBACK_RATES] == [1.25, 1.5, 2.0, 1.0]
    assert PlaybackSpeedState(path).rate == 1.0


def test_playback_script_applies_to_current_and_future_videos() -> None:
    script = playback_speed_script(1.5)
    assert "window.__mabaoPlaybackRate = 1.5" in script
    assert "video.defaultPlaybackRate" in script
    assert "video.playbackRate" in script
    assert "MutationObserver" in script
    assert "attributeFilter: ['src']" in script
    assert "document.addEventListener('play'" in script


def test_native_mouse_flags_preserve_side_button_mapping() -> None:
    assert actions_from_mouse_flags(RI_MOUSE_BUTTON_4_DOWN) == ("x",)
    assert actions_from_mouse_flags(RI_MOUSE_BUTTON_5_DOWN) == ("x2",)
    assert actions_from_mouse_flags(RI_MOUSE_BUTTON_4_DOWN | RI_MOUSE_BUTTON_5_DOWN) == ("x", "x2")


def test_native_keyboard_and_game_window_fallbacks() -> None:
    assert keyboard_action(VK_OEM_3, WM_KEYDOWN) == "toggle_play"
    assert keyboard_action(0x41, WM_KEYDOWN) == ""
    assert is_game_window("原神", "UnityWndClass", "")
    assert is_game_window("", "UnityWndClass", "YuanShen.exe")
    assert not is_game_window("Bilibili", "Chrome_WidgetWin_1", "妈宝本地版.exe")


def test_game_window_clicks_do_not_activate_without_explicit_control_key() -> None:
    assert should_prevent_window_activation(True, False)
    assert not should_prevent_window_activation(True, True)
    assert not should_prevent_window_activation(False, False)


def test_game_switching_does_not_mutate_application_window_styles() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "SetWindowLongW" not in source
    assert "SetWindowPos" not in source
    assert "QTimer.singleShot(\n        0, lambda: window.setAttribute" in source


def test_ai_region_origin_stays_inside_browser_bounds() -> None:
    browser = (47, 400, 794, 556)
    assert clamp_ai_region_origin(0, 0, 360, browser) == (47, 400)
    assert clamp_ai_region_origin(9999, 9999, 360, browser) == (481, 596)


def test_ai_region_size_fits_small_browser_without_invalid_clamp() -> None:
    assert fit_ai_region_size(900, 794, 556) == 556
    assert fit_ai_region_size(360, 80, 60) == 60
    assert fit_ai_region_size(20, 794, 556) == 24


def test_capture_image_normalization_returns_contiguous_uint8_array() -> None:
    import numpy as np

    source = np.arange(4 * 6 * 4, dtype=np.uint16).reshape(4, 6, 4)[:, ::2]
    normalized = normalize_capture_image(source)
    assert normalized is not None
    assert normalized.dtype == np.uint8
    assert normalized.shape == (4, 3, 4)
    assert normalized.flags.c_contiguous


def test_ai_region_small_map_has_a_wider_drag_window() -> None:
    browser = (47, 400, 794, 556)
    assert clamp_ai_region_origin(9999, 9999, 100, browser) == (741, 856)


def test_ai_region_can_reach_both_edges_for_each_supported_size() -> None:
    browser = (47, 400, 794, 556)
    for size in (72, 180, 360, 556):
        assert clamp_ai_region_origin(-9999, -9999, size, browser) == (47, 400)
        assert clamp_ai_region_origin(9999, 9999, size, browser) == (
            47 + 794 - size,
            400 + 556 - size,
        )


def test_orb_locator_fallback_finds_exact_crop() -> None:
    import cv2
    import numpy as np

    rng = np.random.default_rng(42)
    large = rng.integers(0, 256, size=(600, 800, 3), dtype=np.uint8)
    cv2.circle(large, (400, 300), 60, (255, 255, 255), 4)
    small = large[200:400, 300:500].copy()
    result = orb_locate_center(large, small)
    assert result is not None
    center, _homography, confidence = result
    assert abs(float(center[0]) - 400) <= 12
    assert abs(float(center[1]) - 300) <= 12
    assert confidence > 0.5


def test_elevated_helper_uses_external_hooks_without_game_injection() -> None:
    helper = (ROOT / "elevated_input_helper.py").read_text(encoding="utf-8")
    assert "WH_KEYBOARD_LL" in helper
    assert "WH_MOUSE_LL" in helper
    assert "PostMessageW" in helper
    assert "WriteProcessMemory" not in helper
    assert "CreateRemoteThread" not in helper


def test_native_input_hidden_window_dispatches_without_focus() -> None:
    bridge = NativeInputBridge({"x": "fast_backward", "x2": "fast_forward"}, force_active=True)
    bridge.start()
    try:
        assert bridge.startup_error == ""
        assert bridge.hwnd
        assert bridge.mouse_registered
        assert bridge.raw_keyboard_registered
        assert bridge.keyboard_registered
        bridge.simulate_action("toggle_play")
        bridge.simulate_action("x")
        bridge.simulate_action("x2")
        deadline = time.monotonic() + 2
        actions = ()
        while time.monotonic() < deadline and len(actions) < 3:
            actions += bridge.drain()
            time.sleep(0.02)
        assert actions == ("toggle_play", "fast_backward", "fast_forward")
    finally:
        bridge.stop()


def test_duplicate_native_and_legacy_actions_are_debounced() -> None:
    calls = []
    callback = debounce_action(lambda value: calls.append(value), minimum_interval=0.08)
    callback("native")
    callback("legacy")
    assert calls == ["native"]
    time.sleep(0.12)
    callback("next")
    assert calls == ["native", "next"]


def test_bilibili_guest_mode_uses_preview_without_forging_login() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    script = (ROOT / "bili_guest_hd.user.js").read_text(encoding="utf-8")
    assert "try_look" in script
    assert "maxQn: 80" in script
    assert "credentials: 'omit'" in script
    assert "data-bili-overdrive-hd" in script
    assert ".bili-mini-mask" in source
    assert "data-mabao-hidden-login" in source
    assert "DedeUserID=" not in script
    assert "document.cookie =" not in script
    assert "SESSDATA" not in script
    assert "return CONFIG.maxQn" in script
    assert "hiStart > currentStart" in script
    assert "__mabaoBiliDiagnostics" in script
    assert "installInitialStateHook()" in script
    assert "initialStateIntercepts" in script
    assert "documentStartRecovery" in script
    assert "bootstrapHighestManifest()" in script
    assert "core.updateSource(high.dash)" in script
    assert "installHighestQualityGuard()" in script
    assert "document.addEventListener('play', ensure, true)" in script
    assert "setInterval(ensure, 4000)" in script
    assert "installLoginUiPolicy()" in script
    assert "if (!document.documentElement) return" in script
    assert ".bpx-player-toast-confirm-login" in script
    assert "data-mabao-hidden-login" in script
    assert "badge.style.setProperty('display', 'none', 'important')" in script
    assert (ROOT / "bili_guest_hd.LICENSE").read_text(encoding="utf-8").startswith("MIT License")
