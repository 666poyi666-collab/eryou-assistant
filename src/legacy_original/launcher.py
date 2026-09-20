from __future__ import annotations

import hashlib
import importlib
import os
import subprocess
import sys
import time
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    byref,
    c_int,
    c_long,
    create_unicode_buffer,
    windll,
    wintypes,
)
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from local_features import (
    NativeInputBridge,
    PlaybackSpeedState,
    debounce_action,
    default_settings_path,
    playback_speed_script,
)


def load_bilibili_guest_hd_script() -> str:
    candidates = (
        runtime_root() / "bili_guest_hd.user.js",
        Path(sys.executable).resolve().parent / "bili_guest_hd.user.js",
        Path(__file__).resolve().parent / "bili_guest_hd.user.js",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(
        "Bilibili guest script is missing from: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def rewrite_bilibili_playurl(url: str) -> str:
    """Route Bilibili media manifests through its anonymous preview endpoint."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.hostname != "api.bilibili.com" or not (
        "/x/player/" in parts.path or "/pgc/player/" in parts.path
    ):
        return url
    if not parts.path.endswith("/playurl"):
        return url
    path = parts.path.replace("/x/player/wbi/playurl", "/x/player/playurl")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("w_rid", None)
    query.pop("wts", None)
    query.update(qn="80", fnval="4048", fnver="0", fourk="1", try_look="1")
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))


AD_SCRIPT = r"""
(() => {
  const selectors = [
    '.ad-report', '[class*="video-card-ad"]', '[class*="commercial-card"]',
    '[class*="slide-ad"]', 'a[href*="cm.bilibili.com"]',
    'a[href*="ad.bilibili.com"]', '[data-ad-report]'
  ];
  const hide = (node) => {
    if (node.style.getPropertyValue('display') !== 'none' ||
        node.style.getPropertyPriority('display') !== 'important') {
      node.style.setProperty('display', 'none', 'important');
    }
  };
  const clean = () => {
    document.querySelectorAll(selectors.join(',')).forEach(node => {
      const card = node.closest('aside, article, li') || node;
      hide(card);
    });
    document.querySelectorAll('span, div').forEach(node => {
      if ((node.textContent || '').trim() !== '\u5e7f\u544a') return;
      const card = node.closest('a') || node.parentElement;
      if (card) hide(card);
    });
    const protectedPlayer = [
      'video', '.bpx-player-container', '.bpx-player-video-wrap',
      '.bpx-player-control-wrap', '.bpx-player-subtitle-wrap', '[class*="bpx-player-ctrl"]'
    ].join(',');
    const loginSelectors = [
      '.bili-mini-mask', '.bili-mini-content-wp', '.bili-mini-login-right-wp',
      '.bili-mini-customer-title', '.bili-mini-close-icon',
      '[role="dialog"][class*="login"]', '[class*="login-mask"]',
      '[class*="login-panel"]', '[class*="login-popover"]'
    ];
    const playerLoginSelectors = [
      '.bpx-player-toast-confirm-login',
      '.bpx-player-toast-wrap:has(.bpx-player-toast-confirm-login)'
    ];
    document.querySelectorAll(playerLoginSelectors.join(',')).forEach(node => {
      hide(node);
      if (!node.hasAttribute('data-mabao-hidden-login')) {
        node.setAttribute('data-mabao-hidden-login', 'true');
      }
    });
    document.querySelectorAll(loginSelectors.join(',')).forEach(node => {
      if (node.closest(protectedPlayer)) return;
      const text = (node.textContent || '').slice(0, 300);
      if (!node.matches('[class^="bili-mini"], [class*=" bili-mini"]') &&
          !/\u767b\u5f55|\u626b\u7801/.test(text)) return;
      hide(node);
      if (!node.hasAttribute('data-mabao-hidden-login')) {
        node.setAttribute('data-mabao-hidden-login', 'true');
      }
    });
    if (document.body) {
      document.body.style.removeProperty('overflow');
      document.body.style.removeProperty('pointer-events');
    }
  };
  clean();
  if (window.__mabaoLocalAdObserver) window.__mabaoLocalAdObserver.disconnect();
  window.__mabaoLocalAdObserver = new MutationObserver(clean);
  window.__mabaoLocalAdObserver.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ['class', 'style', 'hidden']
  });
  document.addEventListener('fullscreenchange', clean, true);
  window.addEventListener('resize', clean, { passive: true });
  return true;
})();
"""

LOCAL_HOME_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<title>二游辅助</title><style>
html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#f7f8fa;
color:#20242a;font-family:'Microsoft YaHei',sans-serif}h1{font-size:28px;font-weight:600}
</style></head><body><h1>二游辅助</h1></body></html>"""

_DLL_DIRECTORIES = []
GAME_INPUT_TASK = "MabaoLocalGameInput"
VK_CONTROL = 0x11
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
SINGLE_INSTANCE_MUTEX = r"Local\MabaoLocalMainWindow"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MEDIA_SINGLETON_SCRIPT = r"""
(() => {
  const media = () => [...document.querySelectorAll('video,audio')];
  const primary = () => {
    try {
      const current = window.player && window.player.mediaElement &&
        window.player.mediaElement();
      if (current) return current;
    } catch (_) {}
    return media().find(node => node.offsetParent !== null) || media()[0] || null;
  };
  const keepOnly = (active) => media().forEach(node => {
    if (node !== active && !node.paused) node.pause();
  });
  if (window.__mabaoMediaPlayGuard) {
    document.removeEventListener('play', window.__mabaoMediaPlayGuard, true);
  }
  window.__mabaoMediaPlayGuard = (event) => keepOnly(event.target);
  document.addEventListener('play', window.__mabaoMediaPlayGuard, true);
  const current = primary();
  if (current) {
    keepOnly(current);
    current.muted = false;
  }
  return true;
})();
"""

PAUSE_ALL_MEDIA_SCRIPT = r"""
document.querySelectorAll('video,audio').forEach(media => media.pause());
"""

TOGGLE_PRIMARY_MEDIA_SCRIPT = r"""
(() => {
  const all = [...document.querySelectorAll('video,audio')];
  let active = null;
  try {
    active = window.player && window.player.mediaElement && window.player.mediaElement();
  } catch (_) {}
  active = active || all.find(media => media.offsetParent !== null) || all[0] || null;
  if (!active) return false;
  if (active.paused) {
    all.forEach(media => { if (media !== active) media.pause(); });
    active.play();
  } else {
    all.forEach(media => media.pause());
  }
  return true;
})();
"""

REMOVED_UI_MARKERS = (
    "粒子拼接特效",
    "粒子瓦解特效",
    "账号信息",
    "卡密信息",
    "卡密",
    "卡号",
    "绑机数",
    "取消自动登录",
    "自动登录",
    "最新公告",
    "免费进入",
    "购买卡密",
    "购卡",
    "铁粉群",
    "打赏",
    "发现新版本",
    "开启后：方向提醒浮窗内容",
    "方向或 AI 定位每次变化时",
    "启用后就可以实时识别攻略视频上玩家的朝向",
    "启用后就可以实时识别攻略视频上玩家的定位",
    "用于验证 AI 截取区域和识别结果是否正确",
    "原理：需要设置两个截图区域",
)


def activate_existing_instance() -> bool:
    """Restore the already-running main window after a duplicate launch."""
    user32 = windll.user32
    callback_type = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, c_int)
    user32.GetWindowTextW.restype = c_int
    kernel32 = windll.kernel32
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    current_pid = os.getpid()
    current_executable = os.path.normcase(os.path.abspath(sys.executable))
    found = []

    def visit(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        if not pid.value or pid.value == current_pid:
            return True
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        executable = ""
        if process:
            try:
                capacity = wintypes.DWORD(32768)
                path = create_unicode_buffer(capacity.value)
                if kernel32.QueryFullProcessImageNameW(process, 0, path, byref(capacity)):
                    executable = os.path.normcase(os.path.abspath(path.value))
            finally:
                kernel32.CloseHandle(process)
        title_length = user32.GetWindowTextLengthW(hwnd)
        title = create_unicode_buffer(title_length + 1)
        if title_length > 0:
            user32.GetWindowTextW(hwnd, title, len(title))
        same_executable = executable == current_executable
        development_window = not getattr(sys, "frozen", False) and title.value.startswith(
            "二游辅助"
        )
        if same_executable or development_window:
            found.append(hwnd)
            return False
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def acquire_single_instance() -> tuple[int | None, bool]:
    """Return the held mutex and whether this process may create a window."""
    kernel32 = windll.kernel32
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    if not mutex:
        return None, True
    if kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
        return int(mutex), True
    activate_existing_instance()
    kernel32.CloseHandle(mutex)
    return None, False


AI_NAV_INTERVAL_MS = 500
AI_NAV_SAVE_DEBOUNCE_MS = 160
AI_NAV_FOLLOW_COALESCE_MS = 0
NATIVE_INPUT_INTERVAL_MS = 50
AI_NAV_DEFAULT_SIZE = 180
AI_NAV_MIN_SIZE = 72


def fit_ai_region_size(
    size: int, browser_width: int, browser_height: int, min_size: int = 24
) -> int:
    """Return a square size that can actually fit inside the browser widget."""
    available = min(int(browser_width), int(browser_height))
    if available <= 0:
        return 0
    return max(min(int(size), available), min(int(min_size), available))


def clamp_ai_region_origin(
    x: int, y: int, size: int, browser_rect: tuple[int, int, int, int]
) -> tuple[int, int]:
    """Clamp a logical screen origin while keeping the complete square in ``browser_rect``."""
    left, top, width, height = (int(value) for value in browser_rect)
    safe_size = max(1, min(int(size), max(1, width), max(1, height)))
    max_x = left + max(0, width - safe_size)
    max_y = top + max(0, height - safe_size)
    return max(left, min(int(x), max_x)), max(top, min(int(y), max_y))


def normalize_capture_image(image):
    """Convert a screenshot-like object into a contiguous uint8 ndarray."""
    if image is None:
        return None
    try:
        import numpy as np

        array = np.array(image, dtype=np.uint8, copy=True, order="C")
    except (TypeError, ValueError):
        return None
    if array.ndim not in (2, 3) or array.size == 0:
        return None
    if array.ndim == 3 and array.shape[2] not in (3, 4):
        return None
    return array


def orb_locate_center(img1, img2):
    """Locate ``img2`` in ``img1`` as a bounded fallback for failed XFeat matches."""
    import cv2
    import numpy as np

    def gray(image):
        if image is None:
            return None
        if image.ndim == 2:
            return image
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    large_gray = gray(normalize_capture_image(img1))
    small_gray = gray(normalize_capture_image(img2))
    if large_gray is None or small_gray is None:
        return None
    detector = cv2.ORB_create(nfeatures=1400, fastThreshold=10)
    key_small, descriptor_small = detector.detectAndCompute(small_gray, None)
    key_large, descriptor_large = detector.detectAndCompute(large_gray, None)
    if descriptor_small is None or descriptor_large is None:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(descriptor_small, descriptor_large, k=2)
    good = [first for first, second in pairs if first.distance < 0.75 * second.distance]
    if len(good) < 8:
        return None
    source = np.float32([key_small[item.queryIdx].pt for item in good]).reshape(-1, 1, 2)
    target = np.float32([key_large[item.trainIdx].pt for item in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
    if homography is None or mask is None:
        return None
    confidence = float(mask.ravel().mean())
    if confidence < 0.35:
        return None
    height, width = small_gray.shape[:2]
    center = cv2.perspectiveTransform(np.float32([[[width / 2, height / 2]]]), homography)[0, 0]
    if not (0 <= center[0] < large_gray.shape[1] and 0 <= center[1] < large_gray.shape[0]):
        return None
    return center, homography, confidence


def runtime_root() -> Path:
    override = os.environ.get("MABAO_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))


def prepare_imports() -> None:
    root = runtime_root()
    legacy_override = os.environ.get("MABAO_LEGACY_LIB", "").strip()
    legacy = Path(legacy_override).resolve() if legacy_override else root
    legacy_value = str(legacy)
    if legacy_value not in sys.path:
        sys.path.insert(0, legacy_value)
    for path in (root, root / "win32", root / "Pythonwin"):
        value = str(path)
        if value not in sys.path:
            sys.path.append(value)
    dll_paths = (
        root,
        root / "numpy.libs",
        root / "PyQt5" / "Qt5" / "bin",
        root / "pywin32_system32",
    )
    qt_root = root / "PyQt5" / "Qt5"
    os.environ["QT_PLUGIN_PATH"] = str(qt_root / "plugins")
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_root / "plugins" / "platforms")
    os.environ.setdefault("QML2_IMPORT_PATH", str(qt_root / "qml"))
    os.environ["PATH"] = os.pathsep.join(
        [*(str(path) for path in dll_paths), os.environ.get("PATH", "")]
    )
    if hasattr(os, "add_dll_directory"):
        for path in dll_paths:
            if path.is_dir():
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(path)))


def setup_runtime_logging() -> None:
    log_dir = default_settings_path().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    importlib.import_module("app.logger").setup_logging(log_dir=log_dir)


def start_elevated_input_helper() -> None:
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("MABAO_LOCAL_SELF_TEST") == "1" or os.environ.get(
        "MABAO_LOCAL_BILI_TEST_URL"
    ):
        return
    helper = Path(sys.executable).with_name("mabao-game-input-helper.exe")
    if not helper.is_file():
        return
    secure_helper = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "MabaoLocalInputHelper"
        / "mabao-game-input-helper.exe"
    )
    logger = importlib.import_module("app.logger").get_logger("local.game_input_helper")
    query = subprocess.run(
        ["schtasks", "/Query", "/TN", GAME_INPUT_TASK],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    helper_matches = False
    if secure_helper.is_file():
        helper_matches = (
            hashlib.sha256(helper.read_bytes()).digest()
            == hashlib.sha256(secure_helper.read_bytes()).digest()
        )
    if query.returncode == 0 and helper_matches:
        run = subprocess.run(
            ["schtasks", "/Run", "/TN", GAME_INPUT_TASK],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        logger.info("Elevated input helper task start: returncode=%s", run.returncode)
        return
    result = windll.shell32.ShellExecuteW(
        None,
        "runas",
        str(helper),
        "--install-task",
        str(helper.parent),
        0,
    )
    logger.info(
        "Elevated input helper setup requested: task_exists=%s helper_matches=%s shell_result=%s",
        query.returncode == 0,
        helper_matches,
        result,
    )


def should_prevent_window_activation(game_foreground: bool, control_down: bool) -> bool:
    return game_foreground and not control_down


def install_application_identity(app, qt_gui) -> None:
    app.setApplicationName("二游辅助")
    icon_path = runtime_root() / "eryou_assistant_icon.ico"
    if icon_path.is_file():
        app.setWindowIcon(qt_gui.QIcon(str(icon_path)))


def sync_game_no_activate(window, bridge: NativeInputBridge) -> None:
    user32 = windll.user32
    user32.GetWindowLongW.argtypes = (wintypes.HWND, c_int)
    user32.GetWindowLongW.restype = c_long
    user32.SetWindowLongW.argtypes = (wintypes.HWND, c_int, c_long)
    user32.SetWindowLongW.restype = c_long
    user32.SetWindowPos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        c_int,
        c_int,
        c_int,
        c_int,
        wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    enum_proc_type = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (enum_proc_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    control_down = bool(windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
    desired = should_prevent_window_activation(bridge._active, control_down)
    process_windows: set[int] = set()

    @enum_proc_type
    def collect(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(process_id))
        if process_id.value == os.getpid():
            process_windows.add(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    process_windows.add(int(window.winId()))
    previous = getattr(window, "_mabao_no_activate_windows", set())
    for hwnd in process_windows | previous:
        enable = desired and hwnd in process_windows
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        new_style = style | WS_EX_NOACTIVATE if enable else style & ~WS_EX_NOACTIVATE
        if new_style == style:
            continue
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    window._mabao_no_activate_windows = process_windows if desired else set()


def install_settings_focus_guard(main_window_module, qt_core, bridge, window) -> None:
    """Prevent show_settings() from activating a dialog before the sync tick."""
    dialog_type = getattr(main_window_module, "BlurDialog", None)
    if dialog_type is None or getattr(dialog_type, "_mabao_focus_guard", False):
        return

    original_show = dialog_type.show
    original_activate = dialog_type.activateWindow

    def game_blocks_activation() -> bool:
        control_down = bool(windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        return should_prevent_window_activation(bool(bridge._active), control_down)

    def guarded_show(self, *args, **kwargs):
        guarded = game_blocks_activation()
        if guarded:
            self.setAttribute(qt_core.Qt.WA_ShowWithoutActivating, True)
        result = original_show(self, *args, **kwargs)
        if guarded:
            sync_game_no_activate(window, bridge)
        return result

    def guarded_activate(self, *args, **kwargs):
        if game_blocks_activation():
            sync_game_no_activate(window, bridge)
            return False
        self.setAttribute(qt_core.Qt.WA_ShowWithoutActivating, False)
        return original_activate(self, *args, **kwargs)

    dialog_type.show = guarded_show
    dialog_type.activateWindow = guarded_activate
    dialog_type._mabao_focus_guard = True


def force_cpu_onnxruntime() -> None:
    onnxruntime = importlib.import_module("onnxruntime")
    original = onnxruntime.InferenceSession
    if getattr(original, "_mabao_cpu_only", False):
        return

    def cpu_only_session(*args, **kwargs):
        if len(args) < 2 and "sess_options" not in kwargs:
            options = onnxruntime.SessionOptions()
            try:
                thread_count = int(os.environ.get("MABAO_AI_THREADS", "4"))
            except ValueError:
                thread_count = 4
            options.intra_op_num_threads = max(1, min(thread_count, os.cpu_count() or 1))
            options.inter_op_num_threads = 1
            kwargs["sess_options"] = options
        if len(args) >= 3:
            args = (*args[:2], ["CPUExecutionProvider"], *args[3:])
            kwargs.pop("providers", None)
        else:
            kwargs["providers"] = ["CPUExecutionProvider"]
        return original(*args, **kwargs)

    cpu_only_session._mabao_cpu_only = True
    onnxruntime.InferenceSession = cpu_only_session


def extend_original_hotkey_names() -> None:
    hotkeys = importlib.import_module("app.hotkey_manager")
    hotkeys._KEY_TO_VK.update(
        {
            "left": 0x25,
            "up": 0x26,
            "right": 0x27,
            "down": 0x28,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pagedown": 0x22,
            "insert": 0x2D,
            "delete": 0x2E,
        }
    )


def enable_ai_navigation_defaults() -> None:
    settings = importlib.import_module("app.settings")
    manager = settings.SettingsManager

    if (
        not os.environ.get("MABAO_LOCAL_DISABLE_AI_BOOTSTRAP")
        and not os.environ.get("MABAO_LOCAL_SELF_TEST")
        and not os.environ.get("MABAO_LOCAL_BILI_TEST_URL")
    ):
        try:
            settings_manager = manager()
            window_settings = settings_manager.get_window_settings()
            ai_values = window_settings.get("ai_nav", {})
            region = ai_values.get("region") if isinstance(ai_values, dict) else None
            bootstrap_key = "_mabao_local_ai_bootstrap_v2"
            if isinstance(region, dict) and not ai_values.get(bootstrap_key):
                ai_values["enabled_direction"] = bool(ai_values.get("enabled_direction")) or True
                ai_values["enabled_location"] = bool(ai_values.get("enabled_location")) or True
                direction = window_settings.setdefault("direction_reminder", {})
                direction["enabled"] = True
                ai_values[bootstrap_key] = True
                settings_manager.save_window_settings(window_settings)
                importlib.import_module("app.logger").get_logger("local.ai_navigation").info(
                    "AI navigation first-run bootstrap v2: "
                    "region_found=true direction=true location=true"
                )
        except Exception:
            importlib.import_module("app.logger").get_logger("local.ai_navigation").exception(
                "AI navigation first-run bootstrap failed"
            )

    def enabled(self, key):
        values = self._get_ai_nav()
        return bool(values[key]) if key in values else True

    manager.get_ai_nav_direction = lambda self: enabled(self, "enabled_direction")
    manager.get_ai_nav_location = lambda self: enabled(self, "enabled_location")


def install_ai_navigation_runtime(main_window, qt_core, qt_gui) -> None:
    """Patch the extracted navigation modules without replacing their recognition logic."""
    window_type = main_window.MainWindow
    if getattr(window_type, "_mabao_ai_runtime_patched", False):
        return

    selector_module = importlib.import_module("app.ai_nav.ai_region_selector")
    worker_module = importlib.import_module("app.ai_nav.ai_nav_worker")
    screenshot_module = importlib.import_module("app.ai_nav.screenshot")
    qt_widgets = importlib.import_module("PyQt5.QtWidgets")
    selector_type = selector_module.AIRegionSelector
    save_button_type = selector_module.SaveIconButton
    worker_type = worker_module.AINavWorker
    logger = importlib.import_module("app.logger").get_logger("local.ai_navigation")
    worker_module.DEFAULT_INTERVAL_MS = AI_NAV_INTERVAL_MS
    selector_module.DEFAULT_SIZE = AI_NAV_DEFAULT_SIZE
    selector_module.MIN_SIZE = AI_NAV_MIN_SIZE

    def position_status(window):
        status = getattr(window, "_local_ai_nav_status", None)
        if status is None:
            return
        width = min(220, max(188, int(window.width()) - 24))
        if status.width() != width:
            status.setFixedWidth(width)
        position = qt_core.QPoint(
            max(12, int(window.width()) - width - 14),
            max(10, int(window.height()) - status.height() - 14),
        )
        if status.pos() != position:
            status.move(position)
        status.raise_()

    def ensure_status(window):
        status = getattr(window, "_local_ai_nav_status", None)
        if status is not None:
            position_status(window)
            return status
        status = qt_widgets.QLabel(window)
        status.setObjectName("mabaoAiNavStatus")
        status.setAlignment(qt_core.Qt.AlignCenter)
        status.setFixedHeight(24)
        status.setFixedWidth(204)
        status.setAttribute(qt_core.Qt.WA_TransparentForMouseEvents, True)
        status.setAttribute(qt_core.Qt.WA_ShowWithoutActivating, True)
        status.setFont(qt_gui.QFont("Microsoft YaHei", 8))
        status.hide()
        window._local_ai_nav_status = status
        window._local_ai_nav_status_key = None
        window._local_ai_nav_status_level = None
        position_status(window)
        return status

    def update_status(window, text, level="idle", *, force=False):
        status = ensure_status(window)
        key = (str(text), str(level))
        if not force and key == getattr(window, "_local_ai_nav_status_key", None):
            return
        colors = {
            "idle": (34, 40, 48, 220),
            "busy": (30, 84, 120, 225),
            "ok": (34, 105, 82, 225),
            "warn": (126, 84, 28, 230),
        }
        red, green, blue, alpha = colors.get(level, colors["idle"])
        if level != getattr(window, "_local_ai_nav_status_level", None):
            status.setStyleSheet(
                "QLabel#mabaoAiNavStatus {"
                f"background: rgba({red}, {green}, {blue}, {alpha});"
                "color: #f5f7fa; border: 1px solid rgba(255,255,255,80);"
                "border-radius: 6px; padding: 1px 8px; }"
            )
            window._local_ai_nav_status_level = level
        status.setText(str(text))
        position_status(window)
        if not status.isVisible():
            status.show()
            status.raise_()
        window._local_ai_nav_status_key = key

    original_resize_event = getattr(window_type, "resizeEvent", None)

    if original_resize_event is not None:

        def resize_event_with_ai_status(self, event):
            result = original_resize_event(self, event)
            position_status(self)
            return result

        window_type.resizeEvent = resize_event_with_ai_status

    original_locator = worker_module.locate_img2_center_in_img1
    original_ensure_models = worker_type._ensure_models
    orb_only_sentinel = object()

    def ensure_bgr_capture(image):
        image = normalize_capture_image(image)
        if image is None:
            return None
        try:
            import cv2

            if image.ndim == 2:
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.shape[2] == 4:
                return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image
        except Exception:
            # A bad bundled ABI or an unexpected screenshot buffer must skip a
            # frame, never escape the worker and kill the whole launcher.
            logger.debug("AI navigation BGR conversion failed; frame skipped", exc_info=True)
            return None

    # The extracted worker imports ensure_bgr into its own module namespace.  Patch
    # that alias as well as the capture boundary so mixed screenshot buffer types
    # cannot escape into the bundled OpenCV binding.
    worker_module.ensure_bgr = ensure_bgr_capture

    def locate_with_orb_fallback(xfeat, img1, img2, min_cossim, edge_enhance=False):
        result = (None, None, 0.0)
        if xfeat is not orb_only_sentinel:
            try:
                result = original_locator(
                    xfeat,
                    img1,
                    img2,
                    min_cossim=min_cossim,
                    edge_enhance=edge_enhance,
                )
                if result[0] is not None and float(result[2]) >= 0.35:
                    return result
            except Exception:
                logger.debug("AI navigation XFeat locator failed; trying ORB", exc_info=True)
        fallback = orb_locate_center(img1, img2)
        if fallback is not None:
            logger.info(
                "AI navigation locator fallback: backend=orb confidence=%.3f",
                float(fallback[2]),
            )
            return fallback
        return result

    worker_module.locate_img2_center_in_img1 = locate_with_orb_fallback

    def ensure_models_with_orb_fallback(self, *args, **kwargs):
        if getattr(self, "_mabao_models_attempted", False):
            return None
        self._mabao_models_attempted = True
        try:
            result = original_ensure_models(self, *args, **kwargs)
        except Exception as error:
            logger.warning(
                "AI navigation model initialization failed; using safe fallback: %s",
                error,
                exc_info=True,
            )
            if getattr(self, "_detector", None) is None:
                self._detector = False
            if getattr(self, "_xfeat", None) in (None, False):
                self._xfeat = orb_only_sentinel
            self._mabao_model_error = str(error)
            result = None
        if getattr(self, "_xfeat", None) is False:
            self._xfeat = orb_only_sentinel
            logger.warning("AI navigation locator backend: orb-only (XFeat unavailable)")
        detector_ready = bool(getattr(self, "_detector", None))
        locator_ready = getattr(self, "_xfeat", None) is not None
        self._mabao_model_state = (
            "xfeat+angle"
            if detector_ready and locator_ready and self._xfeat is not orb_only_sentinel
            else "orb+angle"
            if detector_ready
            else "orb-only"
        )
        logger.info(
            "AI navigation model state: backend=%s detector=%s error=%s",
            self._mabao_model_state,
            detector_ready,
            getattr(self, "_mabao_model_error", "none"),
        )
        return result

    worker_type._ensure_models = ensure_models_with_orb_fallback

    def accent_color():
        try:
            value = tuple(
                int(channel) for channel in selector_module.theme_manager().get_accent_color()
            )
            if len(value) == 3:
                return value
        except Exception:
            pass
        return 52, 122, 246

    def paint_save_button(self, _event):
        painter = qt_gui.QPainter(self)
        painter.setRenderHint(qt_gui.QPainter.Antialiasing, True)
        size = float(min(self.width(), self.height()))
        radius = max(10.0, size / 2.0 - 2.0)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        ar, ag, ab = accent_color()
        fill_alpha = 220 if not getattr(self, "_pressed", False) else 245
        painter.setPen(qt_gui.QPen(qt_gui.QColor(ar, ag, ab, 245), 2.0))
        painter.setBrush(qt_gui.QBrush(qt_gui.QColor(255, 255, 255, fill_alpha)))
        painter.drawEllipse(qt_core.QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
        pen = qt_gui.QPen(qt_gui.QColor(ar, ag, ab, 255), max(2.0, size * 0.075))
        pen.setCapStyle(qt_core.Qt.RoundCap)
        pen.setJoinStyle(qt_core.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            int(cx - radius * 0.38),
            int(cy + radius * 0.02),
            int(cx - radius * 0.08),
            int(cy + radius * 0.32),
        )
        painter.drawLine(
            int(cx - radius * 0.08),
            int(cy + radius * 0.32),
            int(cx + radius * 0.48),
            int(cy - radius * 0.34),
        )
        painter.end()

    save_button_type.paintEvent = paint_save_button

    def paint_selector(self, _event):
        painter = qt_gui.QPainter(self)
        painter.setRenderHint(qt_gui.QPainter.Antialiasing, True)
        side = float(min(self.width(), self.height()))
        ar, ag, ab = accent_color()
        if getattr(self, "_mabao_boundary_hit", False):
            ar, ag, ab = 238, 142, 55
        margin = max(4.0, min(12.0, side * 0.045))
        right = max(margin + 1.0, side - margin)
        bottom = max(margin + 1.0, side - margin)
        border = qt_gui.QPen(qt_gui.QColor(ar, ag, ab, 228), max(1.4, min(2.4, side * 0.009)))
        border.setJoinStyle(qt_core.Qt.RoundJoin)
        painter.setPen(border)
        painter.setBrush(qt_gui.QBrush(qt_gui.QColor(238, 247, 255, 30)))
        painter.drawRoundedRect(
            qt_core.QRectF(margin, margin, right - margin, bottom - margin),
            min(10.0, side * 0.08),
            min(10.0, side * 0.08),
        )
        painter.setBrush(qt_gui.QBrush(qt_gui.QColor(ar, ag, ab, 205)))
        handle = max(14.0, min(28.0, side * 0.14))
        handle_pen = qt_gui.QPen(qt_gui.QColor(ar, ag, ab, 245), max(2.0, side * 0.012))
        handle_pen.setCapStyle(qt_core.Qt.RoundCap)
        painter.setPen(handle_pen)
        for x1, y1, x2, y2 in (
            (margin, margin + handle, margin, margin),
            (margin, margin, margin + handle, margin),
            (right - handle, margin, right, margin),
            (right, margin, right, margin + handle),
            (margin, bottom - handle, margin, bottom),
            (margin, bottom, margin + handle, bottom),
            (right - handle, bottom, right, bottom),
            (right, bottom - handle, right, bottom),
        ):
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        painter.end()

    selector_type.paintEvent = paint_selector

    original_selector_init = selector_type.__init__

    def selector_init(self, *args, **kwargs):
        original_selector_init(self, *args, **kwargs)
        self.setAttribute(qt_core.Qt.WA_ShowWithoutActivating, True)
        self.setToolTip("拖动任意空白处移动 · 滚轮调整大小 · 点击中间保存 · Esc取消")
        self.setMouseTracking(True)
        self._ok_btn.setToolTip("保存区域")
        self._mabao_follow_pending = False
        self._mabao_pending_save = False
        self._mabao_boundary_hit = False
        self._mabao_wheel_grab_rect = None
        self._mabao_last_boundary_status = 0.0
        self._mabao_drag_offset = qt_core.QPoint()
        app = qt_widgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._mabao_event_app = app

    selector_type.__init__ = selector_init

    original_clamp = selector_type._clamp_to_browser

    def clamp_to_browser(self, x, y):
        rect = self._get_browser_screen_rect()
        if rect is None:
            return original_clamp(self, x, y)
        size = fit_ai_region_size(
            getattr(self, "_logic_size", selector_module.DEFAULT_SIZE),
            rect.width(),
            rect.height(),
            min_size=getattr(selector_module, "MIN_SIZE", 24),
        )
        if size <= 0:
            return int(x), int(y)
        if size != getattr(self, "_logic_size", size) and not getattr(self, "_dragging", False):
            self._logic_size = size
            if self.width() != size or self.height() != size:
                self.resize(size, size)
            self._reposition_ok_button()
            logger.debug(
                "AI region resized to fit browser: browser=%sx%s size=%s",
                rect.width(),
                rect.height(),
                size,
            )
        result = clamp_ai_region_origin(
            x, y, size, (rect.x(), rect.y(), rect.width(), rect.height())
        )
        if getattr(self, "_dragging", False) and result != (int(x), int(y)):
            self._mabao_boundary_hit = True
            self.update()
            if not getattr(self, "_mabao_boundary_timer_active", False):
                self._mabao_boundary_timer_active = True

                def clear_boundary():
                    self._mabao_boundary_timer_active = False
                    self._mabao_boundary_hit = False
                    if self.isVisible():
                        self.update()

                qt_core.QTimer.singleShot(220, clear_boundary)
            owner = self.parent()
            if owner is None and getattr(self, "_browser_widget", None) is not None:
                owner = self._browser_widget.window()
            now = time.monotonic()
            if owner is not None and now - getattr(self, "_mabao_last_boundary_status", 0.0) >= 0.7:
                update_status(owner, "AI导航 · 已到浏览器边界", "warn")
                self._mabao_last_boundary_status = now
        return result

    selector_type._clamp_to_browser = clamp_to_browser

    def reposition_ok_button(self):
        button_size = max(32, min(56, int(getattr(self, "_logic_size", 360) * 0.14)))
        self._ok_btn.set_icon_size(button_size)
        self._ok_btn.move(
            int(self.width() / 2 - button_size / 2),
            int(self.height() / 2 - button_size / 2),
        )

    selector_type._reposition_ok_button = reposition_ok_button

    original_mouse_press = selector_type.mousePressEvent
    original_mouse_move = selector_type.mouseMoveEvent
    original_mouse_release = selector_type.mouseReleaseEvent

    def move_selector_from_global(self, global_pos):
        offset = getattr(self, "_mabao_drag_offset", qt_core.QPoint())
        requested = (
            int(global_pos.x()) - int(offset.x()),
            int(global_pos.y()) - int(offset.y()),
        )
        clamped = self._clamp_to_browser(*requested)
        self.move(*clamped)
        self._update_offset()
        if clamped != requested:
            self._mabao_boundary_hit = True
            self.update()
        return clamped, requested

    def finish_selector_drag(self):
        if not getattr(self, "_dragging", False):
            return
        self._dragging = False
        try:
            self.releaseMouse()
        except Exception:
            logger.debug("AI region mouse release unavailable", exc_info=True)
        self.setCursor(qt_core.Qt.ArrowCursor)
        self._update_offset()
        self.save_state()

    def mouse_press_event(self, event):
        if event.button() != qt_core.Qt.LeftButton:
            return original_mouse_press(self, event)
        if self._ok_btn.geometry().contains(event.pos()):
            return original_mouse_press(self, event)
        self._dragging = True
        self._mabao_drag_offset = event.globalPos() - self.frameGeometry().topLeft()
        self._mabao_boundary_hit = False
        self.setCursor(qt_core.Qt.SizeAllCursor)
        try:
            self.grabMouse()
        except Exception:
            logger.debug("AI region mouse grab unavailable", exc_info=True)
        event.accept()

    def mouse_move_event(self, event):
        if self._dragging and event.buttons() & qt_core.Qt.LeftButton:
            move_selector_from_global(self, event.globalPos())
            event.accept()
            return
        if self._ok_btn.geometry().contains(event.pos()):
            self.setCursor(qt_core.Qt.PointingHandCursor)
        else:
            self.setCursor(qt_core.Qt.SizeAllCursor)
        original_mouse_move(self, event)

    def mouse_release_event(self, event):
        if event.button() == qt_core.Qt.LeftButton and self._dragging:
            finish_selector_drag(self)
            event.accept()
            return
        original_mouse_release(self, event)

    selector_type.mousePressEvent = mouse_press_event
    selector_type.mouseMoveEvent = mouse_move_event
    selector_type.mouseReleaseEvent = mouse_release_event

    def wheel_event(self, event):
        delta = int(event.angleDelta().y())
        if delta == 0:
            return
        old_size = max(1, int(getattr(self, "_logic_size", selector_module.DEFAULT_SIZE)))
        step = getattr(selector_module, "WHEEL_STEP", 16)
        requested = old_size + (step if delta > 0 else -step)
        rect = self._get_browser_screen_rect()
        if rect is not None:
            new_size = fit_ai_region_size(
                requested,
                rect.width(),
                rect.height(),
                min_size=getattr(selector_module, "MIN_SIZE", AI_NAV_MIN_SIZE),
            )
        else:
            new_size = max(
                getattr(selector_module, "MIN_SIZE", AI_NAV_MIN_SIZE),
                min(getattr(selector_module, "MAX_SIZE", 900), requested),
            )
        if new_size != old_size:
            global_pos = event.globalPos()
            local_pos = self.mapFromGlobal(global_pos)
            anchor_x = max(0.0, min(1.0, float(local_pos.x()) / old_size))
            anchor_y = max(0.0, min(1.0, float(local_pos.y()) / old_size))
            self._mabao_wheel_grab_rect = self.frameGeometry()
            qt_core.QTimer.singleShot(
                420,
                lambda: setattr(self, "_mabao_wheel_grab_rect", None),
            )
            self._logic_size = new_size
            self.resize(new_size, new_size)
            new_x = int(global_pos.x() - anchor_x * new_size)
            new_y = int(global_pos.y() - anchor_y * new_size)
            new_x, new_y = self._clamp_to_browser(new_x, new_y)
            self.move(new_x, new_y)
            self._update_offset()
            self._reposition_ok_button()
            self.save_state()
            logger.debug(
                "AI region resize: browser=%s size=%s->%s anchor=(%.2f,%.2f)",
                None if rect is None else (rect.x(), rect.y(), rect.width(), rect.height()),
                old_size,
                new_size,
                anchor_x,
                anchor_y,
            )
        event.accept()

    selector_type.wheelEvent = wheel_event

    original_save_state = selector_type.save_state

    def flush_save(self):
        if not getattr(self, "_mabao_pending_save", False):
            return
        self._mabao_pending_save = False
        self._mabao_save_immediately = True
        try:
            original_save_state(self)
        finally:
            self._mabao_save_immediately = False

    def save_state(self):
        if getattr(self, "_mabao_save_immediately", False):
            self._mabao_pending_save = False
            return original_save_state(self)
        timer = getattr(self, "_mabao_save_timer", None)
        if timer is None:
            timer = qt_core.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: flush_save(self))
            self._mabao_save_timer = timer
        self._mabao_pending_save = True
        timer.start(AI_NAV_SAVE_DEBOUNCE_MS)
        return None

    selector_type.save_state = save_state

    original_ok = selector_type._on_ok

    def on_ok(self):
        self._mabao_save_immediately = True
        try:
            result = original_ok(self)
            owner = self.parent()
            if owner is None and getattr(self, "_browser_widget", None) is not None:
                owner = self._browser_widget.window()
            if owner is not None and hasattr(owner, "_apply_ai_nav_settings"):
                update_status(owner, "AI导航 · 区域已保存", "ok", force=True)
                qt_core.QTimer.singleShot(0, owner._apply_ai_nav_settings)
            return result
        finally:
            self._mabao_save_immediately = False

    selector_type._on_ok = on_ok

    original_close_event = selector_type.closeEvent

    def close_event(self, event):
        self._mabao_save_immediately = True
        try:
            if getattr(self, "_dragging", False):
                self._dragging = False
                try:
                    self.releaseMouse()
                except Exception:
                    logger.debug("AI region close mouse release unavailable", exc_info=True)
            return original_close_event(self, event)
        finally:
            self._mabao_save_immediately = False
            app = getattr(self, "_mabao_event_app", None)
            if app is not None:
                app.removeEventFilter(self)

    selector_type.closeEvent = close_event

    original_event_filter = selector_type.eventFilter

    def run_follow(self):
        self._mabao_follow_pending = False
        if self.isVisible() and not getattr(self, "_dragging", False):
            self._follow_browser()

    def event_filter(self, watched, event):
        event_type = event.type()
        if event_type == qt_core.QEvent.Wheel and self.isVisible():
            try:
                global_pos = event.globalPos()
                current_rect = self.frameGeometry()
                previous_rect = getattr(self, "_mabao_wheel_grab_rect", None)
                if (
                    previous_rect is not None
                    and not current_rect.contains(global_pos)
                    and previous_rect.contains(global_pos)
                ):
                    self.wheelEvent(event)
                    return True
            except Exception:
                logger.debug("AI region wheel routing failed", exc_info=True)
        if getattr(self, "_dragging", False) and event_type == qt_core.QEvent.MouseMove:
            try:
                move_selector_from_global(self, event.globalPos())
                return True
            except Exception:
                logger.debug("AI region global drag routing failed", exc_info=True)
        if (
            getattr(self, "_dragging", False)
            and event_type == qt_core.QEvent.MouseButtonRelease
            and event.button() == qt_core.Qt.LeftButton
        ):
            finish_selector_drag(self)
            return True
        if event_type in (qt_core.QEvent.Move, qt_core.QEvent.Resize):
            if getattr(self, "_dragging", False):
                return False
            if not getattr(self, "_mabao_follow_pending", False):
                self._mabao_follow_pending = True
                qt_core.QTimer.singleShot(AI_NAV_FOLLOW_COALESCE_MS, lambda: run_follow(self))
            return False
        return original_event_filter(self, watched, event)

    selector_type.eventFilter = event_filter

    original_open_selector = window_type._open_ai_region_selector

    def open_selector_without_activation(self):
        selector = getattr(self, "_ai_region_selector", None)
        if selector is not None and selector.isVisible():
            selector.show()
            selector.raise_()
            return None
        try:
            selector = selector_type(
                self.settings_manager,
                parent=self,
                browser_widget=self.webview_container,
            )
            self._ai_region_selector = selector
            selector.show()
            selector.raise_()
            logger.info("AI navigation region selector shown without activation")
            return None
        except Exception:
            logger.exception("AI navigation region selector open override failed")
            return original_open_selector(self)

    window_type._open_ai_region_selector = open_selector_without_activation

    original_ai_init = window_type._init_ai_nav
    original_ai_apply = window_type._apply_ai_nav_settings
    original_ai_pose = window_type._on_ai_pose_ready

    def ai_init(self, *args, **kwargs):
        result = original_ai_init(self, *args, **kwargs)
        worker = getattr(self, "_ai_worker", None)
        if worker is not None and getattr(worker, "_timer", None) is not None:
            worker._timer.setInterval(AI_NAV_INTERVAL_MS)
        self._local_ai_nav_capture_count = 0
        self._local_ai_nav_last_capture_log = 0.0
        self._local_ai_nav_last_result_key = None
        self._local_ai_nav_last_result_log = 0.0
        self._local_ai_nav_last_status_update = 0.0
        self._local_ai_nav_region = None
        self._local_ai_nav_model_state = ""
        capture_timer = qt_core.QTimer(self)
        capture_timer.setTimerType(qt_core.Qt.CoarseTimer)
        capture_timer.setInterval(AI_NAV_INTERVAL_MS)
        capture_timer.timeout.connect(lambda: ai_capture_request(self))
        self._local_ai_nav_capture_timer = capture_timer
        ensure_status(self)
        logger.info("AI navigation pipeline ready: interval_ms=%s", AI_NAV_INTERVAL_MS)
        return result

    def ai_apply(self, *args, **kwargs):
        result = original_ai_apply(self, *args, **kwargs)
        worker = getattr(self, "_ai_worker", None)
        state = (False, False, False)
        if worker is not None:
            state = (
                bool(getattr(worker, "_enabled_dir", False)),
                bool(getattr(worker, "_enabled_loc", False)),
                bool(getattr(worker, "_edge_enhance", False)),
            )
            if state != getattr(self, "_local_ai_nav_settings_state", None):
                self._local_ai_nav_settings_state = state
                logger.info(
                    "AI navigation settings: direction=%s location=%s edge_enhance=%s",
                    *state,
                )
        any_enabled = any(state[:2])
        if worker is not None and any_enabled:
            try:
                window_settings = self.settings_manager.get_window_settings()
                ai_values = window_settings.get("ai_nav", {})
                region = ai_values.get("region") if isinstance(ai_values, dict) else None
                self._local_ai_nav_region = dict(region) if isinstance(region, dict) else None
                model_state = str(getattr(worker, "_mabao_model_state", ""))
                if model_state and model_state != self._local_ai_nav_model_state:
                    self._local_ai_nav_model_state = model_state
                    logger.info("AI navigation UI backend: %s", model_state)
                direction_reminder = getattr(self, "direction_reminder", None)
                if direction_reminder is None and isinstance(region, dict):
                    self._create_direction_reminder_instance()
                    direction_reminder = getattr(self, "direction_reminder", None)
                if not isinstance(region, dict):
                    update_status(self, "AI导航 · 请先框选小地图", "warn")
                else:
                    capture_timer = getattr(self, "_local_ai_nav_capture_timer", None)
                    if capture_timer is not None and not capture_timer.isActive():
                        capture_timer.start()
                        ai_capture(self)
                        worker.stop()
                        logger.info(
                            "AI navigation capture timer active: reason=region_ready "
                            "direction_overlay_visible=%s",
                            bool(direction_reminder is not None and direction_reminder.isVisible()),
                        )
                    if (
                        time.monotonic() - getattr(self, "_local_ai_nav_last_status_update", 0.0)
                        >= 1.0
                    ):
                        update_status(self, "AI导航 · 等待识别结果", "busy")
                        self._local_ai_nav_last_status_update = time.monotonic()
            except Exception:
                logger.exception("AI navigation worker activation failed")
        elif worker is not None:
            capture_timer = getattr(self, "_local_ai_nav_capture_timer", None)
            if capture_timer is not None:
                capture_timer.stop()
            worker.stop()
            status = getattr(self, "_local_ai_nav_status", None)
            if status is not None:
                status.hide()
        return result

    def ai_capture_request(self, *args, **kwargs):
        self._local_ai_nav_capture_count = getattr(self, "_local_ai_nav_capture_count", 0) + 1
        return ai_capture(self, *args, **kwargs)

    def ai_capture(self, *args, **kwargs):
        started = time.monotonic()
        worker = getattr(self, "_ai_worker", None)
        img1 = None
        img2 = None
        if worker is not None and getattr(worker, "_busy", False):
            self._local_ai_nav_busy_skipped = getattr(self, "_local_ai_nav_busy_skipped", 0) + 1
            now = time.monotonic()
            if now - getattr(self, "_local_ai_nav_last_status_update", 0.0) >= 0.8:
                update_status(self, "AI导航 · 识别中", "busy")
                self._local_ai_nav_last_status_update = now
            return None
        try:
            direction_reminder = getattr(self, "direction_reminder", None)
            if direction_reminder is not None:
                capture_rect = direction_reminder.get_capture_rect_logical()
                img1 = screenshot_module.capture_screen_rect(*capture_rect)
            region = getattr(self, "_local_ai_nav_region", None)
            if not isinstance(region, dict):
                window_settings = self.settings_manager.get_window_settings()
                ai_values = window_settings.get("ai_nav", {})
                region = ai_values.get("region") if isinstance(ai_values, dict) else None
            if isinstance(region, dict) and worker is not None:
                main_hwnd = int(self.winId())
                browser_top_left = self.webview_container.mapToGlobal(qt_core.QPoint(0, 0))
                browser_width = int(self.webview_container.width())
                browser_height = int(self.webview_container.height())
                size = fit_ai_region_size(
                    int(region.get("size", AI_NAV_DEFAULT_SIZE)),
                    browser_width,
                    browser_height,
                    min_size=AI_NAV_MIN_SIZE,
                )
                offset_x, offset_y = clamp_ai_region_origin(
                    int(region.get("x", 0)),
                    int(region.get("y", 0)),
                    size,
                    (0, 0, browser_width, browser_height),
                )
                abs_x = int(browser_top_left.x()) + offset_x
                abs_y = int(browser_top_left.y()) + offset_y
                if main_hwnd and size > 0:
                    img2 = screenshot_module.capture_window_region(
                        main_hwnd,
                        abs_x,
                        abs_y,
                        abs_x + size,
                        abs_y + size,
                    )
            img1 = normalize_capture_image(img1)
            img2 = normalize_capture_image(img2)
            if worker is not None:
                worker.set_images(img1, img2)
            if img1 is None or img2 is None:
                update_status(self, "AI导航 · 等待有效采集区域", "warn")
            elif time.monotonic() - getattr(self, "_local_ai_nav_last_status_update", 0.0) >= 0.8:
                update_status(self, "AI导航 · 采样中", "busy")
                self._local_ai_nav_last_status_update = time.monotonic()
        except Exception:
            logger.exception("AI navigation capture failed")
            if worker is not None:
                worker.set_images(None, None)
            update_status(self, "AI导航 · 采集失败", "warn")
        now = time.monotonic()
        if now - getattr(self, "_local_ai_nav_last_capture_log", 0.0) >= 2.0:
            logger.info(
                "AI navigation capture requested: requests=%s worker_busy=%s "
                "img1=%s img2=%s elapsed_ms=%.1f",
                getattr(self, "_local_ai_nav_capture_count", 0),
                bool(getattr(worker, "_busy", False)),
                getattr(img1, "shape", None),
                getattr(img2, "shape", None),
                (now - started) * 1000,
            )
            self._local_ai_nav_last_capture_log = now
        return None

    def ai_pose(self, angle, angle_conf, pos_norm, loc_conf, *args, **kwargs):
        now = time.monotonic()
        worker = getattr(self, "_ai_worker", None)
        model_state = str(getattr(worker, "_mabao_model_state", ""))
        if model_state and model_state != getattr(self, "_local_ai_nav_model_state", ""):
            self._local_ai_nav_model_state = model_state
            logger.info("AI navigation UI backend: %s", model_state)
        result_key = (
            angle is not None,
            pos_norm is not None,
            round(float(angle_conf), 1),
            round(float(loc_conf), 1),
        )
        last_key = getattr(self, "_local_ai_nav_last_result_key", None)
        if (
            result_key != last_key
            and now - getattr(self, "_local_ai_nav_last_result_log", 0.0) >= 1.0
        ):
            angle_text = "--" if angle is None else f"{float(angle):.1f}°"
            pos_text = (
                "--"
                if pos_norm is None
                else "(" + ",".join(f"{float(value):.2f}" for value in pos_norm) + ")"
            )
            logger.info(
                "AI navigation result: angle=%s angle_conf=%.3f position=%s location_conf=%.3f",
                angle_text,
                float(angle_conf),
                pos_text,
                float(loc_conf),
            )
            self._local_ai_nav_last_result_key = result_key
            self._local_ai_nav_last_result_log = now
        self._local_ai_nav_last_result = (angle, angle_conf, pos_norm, loc_conf)
        if angle is None and pos_norm is None:
            backend_hint = " · ORB备用" if model_state == "orb-only" else ""
            status_text = f"AI导航{backend_hint} · 暂未匹配到地图"
            status_level = "warn"
        else:
            angle_text = "--" if angle is None else f"{float(angle):.0f}°"
            backend_hint = " · ORB备用" if model_state == "orb-only" else ""
            status_text = f"AI导航{backend_hint} · 方向 {angle_text} · 定位 {float(loc_conf):.0%}"
            status_level = "ok" if pos_norm is not None or angle is not None else "warn"
        if now - getattr(self, "_local_ai_nav_last_status_update", 0.0) >= 0.8:
            update_status(self, status_text, status_level)
            self._local_ai_nav_last_status_update = now
        direction_reminder = getattr(self, "direction_reminder", None)
        if direction_reminder is None:
            return None
        try:
            if direction_reminder.isVisible():
                return original_ai_pose(angle, angle_conf, pos_norm, loc_conf, *args, **kwargs)
            direction_reminder.set_ai_mode(True)
            direction_reminder.set_player_pose(angle, pos_norm, angle_conf, loc_conf)
        except Exception:
            logger.exception("AI navigation pose display failed")
        return None

    window_type._init_ai_nav = ai_init
    window_type._apply_ai_nav_settings = ai_apply
    window_type._on_ai_request_capture = ai_capture_request
    window_type._ai_do_capture = ai_capture
    window_type._on_ai_pose_ready = ai_pose
    window_type._mabao_ai_runtime_patched = True


def install_web_runtime(playback_state: PlaybackSpeedState) -> None:
    module = importlib.import_module("app.webview_container")
    module._UNMUTE_SCRIPT = MEDIA_SINGLETON_SCRIPT
    container = module.WebViewContainer
    original = container._on_dom_content_loaded
    original_load_url = container.load_url

    def on_dom_content_loaded(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            self.execute_js(AD_SCRIPT)
            self.execute_js(MEDIA_SINGLETON_SCRIPT)
            self.execute_js(playback_speed_script(playback_state.rate))
        except Exception:
            pass
        return result

    container._on_dom_content_loaded = on_dom_content_loaded

    def load_url(self, url):
        if not getattr(self, "_local_initial_navigation_done", False):
            self._local_initial_navigation_done = True
            return self.load_html(LOCAL_HOME_HTML)
        return original_load_url(self, url)

    container.load_url = load_url


def install_media_controls(main_window) -> None:
    def pause_all_media(self):
        try:
            self.webview_container.execute_js(PAUSE_ALL_MEDIA_SCRIPT)
        except Exception:
            pass

    def toggle_primary_media(self):
        try:
            self.webview_container.execute_js(TOGGLE_PRIMARY_MEDIA_SCRIPT)
        except Exception:
            pass

    main_window.MainWindow._pause_video_only = pause_all_media
    main_window.MainWindow.toggle_play = toggle_primary_media


def install_document_start_script() -> None:
    widget_module = importlib.import_module("qtwebview2.widget")
    widget = widget_module.QtWebView2Widget
    original = widget._on_webview_ready
    if getattr(original, "_mabao_guest_hd", False):
        return
    logger = importlib.import_module("app.logger").get_logger("local.bilibili")
    bridge = importlib.import_module("qtwebview2._dotnet_bridge")

    def on_webview_ready(self, sender, args):
        if args.IsSuccess:
            try:
                core = sender.CoreWebView2
                if not getattr(self, "_mabao_bili_request_rewrite", False):
                    core.AddWebResourceRequestedFilter(
                        "*",
                        bridge.Core.CoreWebView2WebResourceContext.All,
                    )

                    def rewrite_request(_sender, event_args):
                        try:
                            original_uri = str(event_args.Request.Uri)
                            rewritten_uri = rewrite_bilibili_playurl(original_uri)
                            if rewritten_uri != original_uri:
                                event_args.Request.Uri = rewritten_uri
                                count = getattr(self, "_mabao_bili_rewrite_count", 0) + 1
                                self._mabao_bili_rewrite_count = count
                                logger.info("Bilibili playurl request rewritten: count=%s", count)
                        except Exception:
                            logger.exception("Bilibili playurl request rewrite failed")

                    core.WebResourceRequested += rewrite_request
                    self._mabao_bili_request_handler = rewrite_request
                    self._mabao_bili_request_rewrite = True
                script = load_bilibili_guest_hd_script()
                registration = core.AddScriptToExecuteOnDocumentCreatedAsync(script)
                logger.info(
                    "Bilibili guest script registration queued: task=%s bytes=%s sha256=%s",
                    registration,
                    len(script.encode("utf-8")),
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                )
            except Exception:
                logger.exception("Bilibili guest script registration failed")
        return original(self, sender, args)

    on_webview_ready._mabao_guest_hd = True
    widget._on_webview_ready = on_webview_ready


def install_playback_hotkey(window, playback_state: PlaybackSpeedState) -> None:
    def cycle_playback_speed():
        try:
            rate = playback_state.cycle()
            window.js_bridger.inject_script(playback_speed_script(rate))
            toast = getattr(window, "_status_toast", None)
            if toast is not None and toast.is_enabled():
                toast.show_message(f"倍速 {rate:g}x")
        except Exception:
            importlib.import_module("app.logger").get_logger("local.playback").exception(
                "倍速热键执行失败"
            )

    callback = window._safe_ui(cycle_playback_speed)
    window.hotkey_manager.register("=", "cycle_playback_speed", callback)
    window._local_playback_speed_state = playback_state
    importlib.import_module("app.logger").get_logger("local.playback").info(
        "倍速热键已注册: key=%s action=%s",
        window.hotkey_manager.get_hotkey_for_action("cycle_playback_speed"),
        "cycle_playback_speed",
    )


def install_playback_hotkey_lifecycle(main_window, playback_state) -> None:
    original = main_window.MainWindow._init_hotkeys

    def init_hotkeys_with_playback_speed(self):
        original(self)
        install_playback_hotkey(self, playback_state)

    main_window.MainWindow._init_hotkeys = init_hotkeys_with_playback_speed


def install_action_debounce(main_window) -> None:
    for name in ("toggle_play", "fast_backward", "fast_forward"):
        original = getattr(main_window.MainWindow, name)
        setattr(main_window.MainWindow, name, debounce_action(original))


def start_native_input() -> NativeInputBridge:
    settings = importlib.import_module("app.settings").SettingsManager()
    bridge = NativeInputBridge(
        settings.get_side_buttons(),
        force_active=os.environ.get("MABAO_NATIVE_INPUT_TEST_ALWAYS_ACTIVE") == "1",
    )
    bridge.start()
    return bridge


def install_native_input(window, qt_core, bridge: NativeInputBridge) -> None:
    timer = qt_core.QTimer(window)
    timer.setInterval(NATIVE_INPUT_INTERVAL_MS)
    logger = importlib.import_module("app.logger").get_logger("local.native_input")
    sync_state = {"active": None, "control": None, "next_sync": 0.0}

    def dispatch():
        now = time.monotonic()
        active = bool(bridge._active)
        control_down = bool(windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        should_sync = (
            active != sync_state["active"]
            or control_down != sync_state["control"]
            or (active and now >= sync_state["next_sync"])
        )
        if should_sync:
            sync_game_no_activate(window, bridge)
            sync_state.update(active=active, control=control_down, next_sync=now + 0.25)
        callbacks = {
            "toggle_play": window.toggle_play,
            "fast_backward": window.fast_backward,
            "fast_forward": window.fast_forward,
        }
        for action in bridge.drain():
            callback = callbacks.get(action)
            if callback is not None:
                logger.info("Native input action: %s", action)
                callback()

    timer.timeout.connect(dispatch)
    timer.start()
    window._native_input_bridge = bridge
    window._native_input_timer = timer
    logger.info(
        "Native input ready: mouse=%s keyboard=%s hotkey=%s raw_keyboard=%s "
        "hotkey_error=%s raw_error=%s error=%s",
        bridge.mouse_registered,
        bridge.keyboard_registered,
        bridge.hotkey_registered,
        bridge.raw_keyboard_registered,
        bridge.last_hotkey_error,
        bridge.last_raw_input_error,
        bridge.startup_error or "none",
    )


def schedule_bilibili_runtime_probe(window, qt_core) -> bool:
    url = os.environ.get("MABAO_LOCAL_BILI_TEST_URL", "").strip()
    if not url:
        return False
    logger = importlib.import_module("app.logger").get_logger("local.bilibili")

    def navigate():
        window.webview_container.load_url(url)

    def expose_state():
        window.webview_container.execute_js(
            r"""
(() => {
  const installed = Boolean(window.__mabaoBiliOverdriveLoaded);
  let video = document.querySelector('video');
  try {
    video = window.player && window.player.mediaElement &&
      window.player.mediaElement() || video;
  } catch (_) {}
  const qualityText = String(
    (document.querySelector('.bpx-player-ctrl-quality') || {}).textContent || ''
  ).trim().replace(/\s+/g, ' ');
  let playerQuality = '';
  let diagnostics = '';
  let coreInfo = '';
  try {
    const value = window.player && window.player.getQuality && window.player.getQuality();
    playerQuality = JSON.stringify(value || '').slice(0, 80);
  } catch (_) {}
  try {
    diagnostics = JSON.stringify(window.__mabaoBiliDiagnostics || {}).slice(0, 260);
  } catch (_) {}
  try {
    const core = window.player && window.player.__core && window.player.__core();
    const methods = core ? Object.getOwnPropertyNames(Object.getPrototypeOf(core))
      .filter(name => /quality|manifest|source|load|dash/i.test(name)).slice(0, 30) : [];
    const tracks = core && core.getQualityList ? core.getQualityList('video') : [];
    const signatures = {};
    ['processManifest', 'updateSource', 'appendSource', 'switchSource'].forEach(name => {
      if (core && typeof core[name] === 'function') {
        signatures[name] = String(core[name]).slice(0, 360);
      }
    });
    coreInfo = JSON.stringify({
      methods: methods, tracks: tracks, signatures: signatures
    }).slice(0, 1800);
  } catch (_) {}
  const selectors = [
    '.bili-mini-mask', '.bili-mini-content-wp', '.bili-mini-login-right-wp',
    '[role="dialog"][class*="login"]', '[class*="login-mask"]',
    '[class*="login-panel"]', '[class*="login-popover"]'
  ];
  const visibleLogin = [...document.querySelectorAll(selectors.join(','))].filter(node => {
    const style = getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }).length;
  document.title = [
    'MABAO_BILI_PROBE', 'installed=' + installed,
    'height=' + Number(video && video.videoHeight || 0),
    'ready=' + Number(video && video.readyState || 0),
    'login=' + visibleLogin, 'quality=' + qualityText.slice(0, 18),
    'injected=' + Number(window.__mabaoInjectedHighQn || 0), 'player=' + playerQuality,
    'diag=' + diagnostics, 'core=' + coreInfo
  ].join('|');
  return document.title;
})();
"""
        )
        qt_core.QTimer.singleShot(
            1000,
            lambda: logger.info("Bilibili runtime probe: %s", window.windowTitle()),
        )

    def start_playback():
        window.webview_container.execute_js(
            """
(() => {
  try {
    const video = window.player && window.player.mediaElement &&
      window.player.mediaElement() || document.querySelector('video');
    if (video) video.play();
  } catch (_) {}
})();
"""
        )

    qt_core.QTimer.singleShot(3000, navigate)
    qt_core.QTimer.singleShot(9000, start_playback)
    qt_core.QTimer.singleShot(15000, expose_state)
    qt_core.QTimer.singleShot(19000, window.close)
    return True


def install_safe_close(main_window) -> None:
    original = main_window.MainWindow.closeEvent

    def close_event_with_ai_shutdown(self, event):
        try:
            self.webview_container.execute_js(PAUSE_ALL_MEDIA_SCRIPT)
        except Exception:
            pass
        bridge = getattr(self, "_native_input_bridge", None)
        if bridge is not None:
            bridge.stop()
        if not getattr(self, "_is_closing", False):
            self._shutdown_ai_nav(force_terminate=True)
        return original(self, event)

    main_window.MainWindow.closeEvent = close_event_with_ai_shutdown


def schedule_runtime_self_test(app, window, playback_state, qt_core) -> None:
    if os.environ.get("MABAO_LOCAL_BILI_TEST_URL", "").strip():
        return
    if os.environ.get("MABAO_LOCAL_SELF_TEST") != "1":
        return

    def run():
        action = "cycle_playback_speed"
        manager = window.hotkey_manager
        assert manager.get_hotkey_for_action(action) == "="
        manager.callbacks[action]()

        bridge = window._native_input_bridge
        observed = {"toggle_play": 0, "fast_backward": 0, "fast_forward": 0}
        originals = {name: getattr(window, name) for name in observed}
        original_side_actions = bridge.side_actions
        bridge.side_actions = {"x": "fast_backward", "x2": "fast_forward"}
        for name in observed:
            setattr(
                window,
                name,
                lambda current=name: observed.__setitem__(current, observed[current] + 1),
            )
        bridge.simulate_action("toggle_play")
        bridge.simulate_action("x")
        bridge.simulate_action("x2")

        def rebuild():
            bridge.side_actions = original_side_actions
            assert observed == {"toggle_play": 1, "fast_backward": 1, "fast_forward": 1}
            for name, original_callback in originals.items():
                setattr(window, name, original_callback)
            manager.unregister_all()
            window._init_hotkeys()
            assert manager.get_hotkey_for_action(action) == "="
            manager.callbacks[action]()

            def finish():
                importlib.import_module("app.logger").get_logger("local.self_test").info(
                    "SELF_TEST_PASS playback_rate=%s", playback_state.rate
                )
                window.close()

            qt_core.QTimer.singleShot(200, finish)

        qt_core.QTimer.singleShot(200, rebuild)

    qt_core.QTimer.singleShot(300, run)


def disable_particle_effects() -> None:
    particle = importlib.import_module("app.particle_splash")

    def no_show_effect(*args, **kwargs):
        return None

    def no_close_effect(*args, on_finished=None, **kwargs):
        if callable(on_finished):
            on_finished()
        return None

    particle.play_show_effect = no_show_effect
    particle.play_close_effect = no_close_effect
    settings = importlib.import_module("app.settings")
    manager = settings.SettingsManager
    manager.get_particle_effect_show = lambda self: False
    manager.get_particle_effect_close = lambda self: False
    manager.set_particle_effect_show = lambda self, value: None
    manager.set_particle_effect_close = lambda self, value: None


def install_ui_sanitizer(app, qt_core, qt_widgets) -> None:
    class UiSanitizer(qt_core.QObject):
        def __init__(self, parent=None):
            super().__init__(parent or app)
            self._pending = False

        def eventFilter(self, watched, event):
            if event.type() in (qt_core.QEvent.Show, qt_core.QEvent.ChildAdded):
                if not self._pending:
                    self._pending = True
                    qt_core.QTimer.singleShot(0, self._run_sanitize)
            return False

        def _run_sanitize(self):
            self._pending = False
            self.sanitize()

        def sanitize(self):
            text_types = (qt_widgets.QAbstractButton, qt_widgets.QLabel, qt_widgets.QGroupBox)
            for top_level in app.topLevelWidgets():
                widgets = [top_level, *top_level.findChildren(qt_core.QObject)]
                for widget in widgets:
                    if not isinstance(widget, text_types):
                        continue
                    text_method = getattr(widget, "text", None)
                    title_method = getattr(widget, "title", None)
                    text = ""
                    if callable(text_method):
                        text = str(text_method())
                    elif callable(title_method):
                        text = str(title_method())
                    if any(marker in text for marker in REMOVED_UI_MARKERS):
                        widget.hide()

    sanitizer = UiSanitizer(app)
    app.installEventFilter(sanitizer)
    app._local_ui_sanitizer = sanitizer
    app._local_ui_sanitizer_timer = None


def main() -> int:
    instance_mutex, is_primary = acquire_single_instance()
    if not is_primary:
        return 0
    prepare_imports()
    setup_runtime_logging()
    force_cpu_onnxruntime()
    extend_original_hotkey_names()
    enable_ai_navigation_defaults()
    playback_state = PlaybackSpeedState()
    qt_core = importlib.import_module("PyQt5.QtCore")
    qt_gui = importlib.import_module("PyQt5.QtGui")
    qt_widgets = importlib.import_module("PyQt5.QtWidgets")
    qt_core.QCoreApplication.setAttribute(qt_core.Qt.AA_EnableHighDpiScaling, True)
    qt_core.QCoreApplication.setAttribute(qt_core.Qt.AA_UseHighDpiPixmaps, True)
    disable_particle_effects()
    install_document_start_script()
    install_web_runtime(playback_state)
    main_window = importlib.import_module("app.main_window")
    install_ai_navigation_runtime(main_window, qt_core, qt_gui)
    install_playback_hotkey_lifecycle(main_window, playback_state)
    install_media_controls(main_window)
    install_action_debounce(main_window)
    install_safe_close(main_window)
    app = qt_widgets.QApplication(sys.argv)
    install_application_identity(app, qt_gui)
    app.setQuitOnLastWindowClosed(True)
    install_ui_sanitizer(app, qt_core, qt_widgets)
    native_input_bridge = start_native_input()
    window = main_window.MainWindow(creation_mouse_pos=qt_gui.QCursor.pos())
    if not app.windowIcon().isNull():
        window.setWindowIcon(app.windowIcon())
    window._tiandun_auth = None
    window._local_full_access = True
    install_native_input(window, qt_core, native_input_bridge)
    install_settings_focus_guard(main_window, qt_core, native_input_bridge, window)
    window.setAttribute(qt_core.Qt.WA_ShowWithoutActivating, True)
    window.show()
    qt_core.QTimer.singleShot(500, start_elevated_input_helper)
    schedule_bilibili_runtime_probe(window, qt_core)
    schedule_runtime_self_test(app, window, playback_state, qt_core)
    qt_core.QTimer.singleShot(0, window._kick_webview_layout)
    qt_core.QTimer.singleShot(200, window._apply_ai_nav_settings)
    try:
        return int(app.exec_())
    finally:
        if instance_mutex:
            windll.kernel32.CloseHandle(instance_mutex)


if __name__ == "__main__":
    raise SystemExit(main())
