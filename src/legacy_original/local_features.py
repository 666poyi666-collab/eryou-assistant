from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    Structure,
    Union,
    WinDLL,
    byref,
    c_long,
    c_short,
    c_size_t,
    c_ssize_t,
    c_ubyte,
    c_ulong,
    c_ushort,
    c_void_p,
    cast,
    create_string_buffer,
    create_unicode_buffer,
    get_last_error,
    set_last_error,
    sizeof,
    wintypes,
)
from pathlib import Path

PLAYBACK_RATES = (1.0, 1.25, 1.5, 2.0)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_INPUT = 0x00FF
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312
WM_APP_ACTION = 0x8001
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIDEV_INPUTSINK = 0x00000100
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_5_DOWN = 0x0100
MOD_NOREPEAT = 0x4000
VK_OEM_3 = 0xC0
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
HOTKEY_ID = 0x4D42
TIMER_ID = 0x4D42
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_USER32 = WinDLL("user32", use_last_error=True)
_KERNEL32 = WinDLL("kernel32", use_last_error=True)


class RawInputDevice(Structure):
    _fields_ = (
        ("usage_page", c_ushort),
        ("usage", c_ushort),
        ("flags", wintypes.DWORD),
        ("target", wintypes.HWND),
    )


class RawInputHeader(Structure):
    _fields_ = (
        ("type", wintypes.DWORD),
        ("size", wintypes.DWORD),
        ("device", wintypes.HANDLE),
        ("wparam", wintypes.WPARAM),
    )


class RawMouseButtons(Structure):
    _fields_ = (("flags", c_ushort), ("data", c_ushort))


class RawMouseButtonsUnion(Union):
    _fields_ = (("buttons", c_ulong), ("detail", RawMouseButtons))


class RawMouse(Structure):
    _anonymous_ = ("button_union",)
    _fields_ = (
        ("flags", c_ushort),
        ("button_union", RawMouseButtonsUnion),
        ("raw_buttons", c_ulong),
        ("last_x", c_long),
        ("last_y", c_long),
        ("extra_information", c_ulong),
    )


class RawKeyboard(Structure):
    _fields_ = (
        ("make_code", c_ushort),
        ("flags", c_ushort),
        ("reserved", c_ushort),
        ("vkey", c_ushort),
        ("message", wintypes.UINT),
        ("extra_information", c_ulong),
    )


class RawInputData(Union):
    _fields_ = (
        ("mouse", RawMouse),
        ("keyboard", RawKeyboard),
        ("padding", c_ubyte * 48),
    )


class RawInput(Structure):
    _fields_ = (("header", RawInputHeader), ("data", RawInputData))


class WindowClass(Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("window_proc", c_void_p),
        ("class_extra", wintypes.INT),
        ("window_extra", wintypes.INT),
        ("instance", wintypes.HINSTANCE),
        ("icon", wintypes.HICON),
        ("cursor", wintypes.HANDLE),
        ("background", wintypes.HBRUSH),
        ("menu_name", wintypes.LPCWSTR),
        ("class_name", wintypes.LPCWSTR),
    )


def actions_from_mouse_flags(flags: int) -> tuple[str, ...]:
    actions = []
    if flags & RI_MOUSE_BUTTON_4_DOWN:
        actions.append("x")
    if flags & RI_MOUSE_BUTTON_5_DOWN:
        actions.append("x2")
    return tuple(actions)


def keyboard_action(vkey: int, message: int) -> str:
    if vkey == VK_OEM_3 and message in {WM_KEYDOWN, WM_SYSKEYDOWN}:
        return "toggle_play"
    return ""


def is_game_window(title: str, class_name: str, process_name: str) -> bool:
    values = (title.casefold(), process_name.casefold())
    markers = (
        "原神",
        "genshin impact",
        "yuanshen.exe",
        "genshinimpact.exe",
        "崩坏：星穹铁道",
        "honkai: star rail",
        "starrail.exe",
    )
    if any(marker in value for marker in markers for value in values):
        return True
    return class_name.casefold() == "unitywndclass" and any(
        marker in process_name.casefold() for marker in ("yuanshen", "genshin", "starrail")
    )


class NativeInputBridge:
    """Receive game-foreground hotkeys without activating the application."""

    _GAME_TITLES = ("原神", "Genshin Impact", "崩坏：星穹铁道", "Honkai: Star Rail")

    def __init__(self, side_actions: dict[str, str], force_active: bool = False) -> None:
        self.side_actions = dict(side_actions)
        self.force_active = force_active
        self.actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="MabaoNativeInput", daemon=True)
        self.hwnd = None
        self.thread_id = 0
        self.keyboard_registered = False
        self.hotkey_registered = False
        self.raw_keyboard_registered = False
        self.mouse_registered = False
        self.startup_error = ""
        self.last_hotkey_error = 0
        self.last_raw_input_error = 0
        self._active = False
        self._window_proc_callback = None
        self._last_hotkey_attempt = 0.0
        self._last_raw_registration = 0.0
        self._last_reported_hotkey_error = None
        self._last_foreground_identity = None
        self._last_foreground_check = 0.0
        self._last_action_at: dict[str, float] = {}
        self._async_down = {VK_OEM_3: False, VK_XBUTTON1: False, VK_XBUTTON2: False}
        self._logger = logging.getLogger("mabao.local.native_input")

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(3):
            self.startup_error = "native input thread did not become ready"

    def stop(self) -> None:
        if self.hwnd:
            _USER32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        elif self.thread_id:
            _USER32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread.is_alive():
            self.thread.join(timeout=2)

    def drain(self) -> tuple[str, ...]:
        result = []
        while True:
            try:
                result.append(self.actions.get_nowait())
            except queue.Empty:
                return tuple(result)

    def simulate_action(self, action: str) -> None:
        codes = {"toggle_play": 1, "x": 2, "x2": 3}
        if self.hwnd and action in codes:
            _USER32.PostMessageW(self.hwnd, WM_APP_ACTION, codes[action], 0)

    def _enqueue(self, action: str, source: str = "native") -> None:
        if action in {"x", "x2"}:
            action = self.side_actions.get(action, "")
        if action:
            now = time.monotonic()
            if now - self._last_action_at.get(action, 0.0) < 0.14:
                return
            self._last_action_at[action] = now
            self._logger.debug("Input accepted: source=%s action=%s", source, action)
            self.actions.put(action)

    def _foreground_snapshot(self) -> tuple[int, str, str, str]:
        hwnd = _USER32.GetForegroundWindow()
        if not hwnd:
            return 0, "", "", ""
        title = create_unicode_buffer(1024)
        class_name = create_unicode_buffer(256)
        _USER32.GetWindowTextW(hwnd, title, len(title))
        _USER32.GetClassNameW(hwnd, class_name, len(class_name))
        pid = wintypes.DWORD()
        _USER32.GetWindowThreadProcessId(hwnd, byref(pid))
        process_name = ""
        process = _KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if process:
            try:
                capacity = wintypes.DWORD(32768)
                path = create_unicode_buffer(capacity.value)
                if _KERNEL32.QueryFullProcessImageNameW(process, 0, path, byref(capacity)):
                    process_name = Path(path.value).name
            finally:
                _KERNEL32.CloseHandle(process)
        return int(hwnd), title.value, class_name.value, process_name

    def _is_game_foreground(self) -> bool:
        if self.force_active:
            return True
        _, title, class_name, process_name = self._foreground_snapshot()
        return is_game_window(title, class_name, process_name)

    def _register_hotkey(self) -> None:
        if self.hotkey_registered or not self.hwnd:
            return
        self._last_hotkey_attempt = time.monotonic()
        set_last_error(0)
        self.hotkey_registered = bool(
            _USER32.RegisterHotKey(self.hwnd, HOTKEY_ID, MOD_NOREPEAT, VK_OEM_3)
        )
        self.last_hotkey_error = 0 if self.hotkey_registered else get_last_error()
        if self.hotkey_registered:
            self._logger.info(
                "RegisterHotKey ready: vk=0x%X modifiers=0x%X", VK_OEM_3, MOD_NOREPEAT
            )
            self._last_reported_hotkey_error = None
        elif self.last_hotkey_error != self._last_reported_hotkey_error:
            self._logger.warning(
                "RegisterHotKey failed: vk=0x%X modifiers=0x%X winerror=%s; "
                "Raw Keyboard fallback remains active",
                VK_OEM_3,
                MOD_NOREPEAT,
                self.last_hotkey_error,
            )
            self._last_reported_hotkey_error = self.last_hotkey_error
        self.keyboard_registered = self.hotkey_registered or self.raw_keyboard_registered

    def _register_raw_devices(self) -> None:
        if not self.hwnd:
            return
        self._last_raw_registration = time.monotonic()
        devices = (RawInputDevice * 2)(
            RawInputDevice(1, 2, RIDEV_INPUTSINK, self.hwnd),
            RawInputDevice(1, 6, RIDEV_INPUTSINK, self.hwnd),
        )
        was_ready = self.mouse_registered and self.raw_keyboard_registered
        set_last_error(0)
        ready = bool(_USER32.RegisterRawInputDevices(devices, len(devices), sizeof(RawInputDevice)))
        self.last_raw_input_error = 0 if ready else get_last_error()
        self.mouse_registered = ready
        self.raw_keyboard_registered = ready
        self.keyboard_registered = self.hotkey_registered or self.raw_keyboard_registered
        if ready and not was_ready:
            self._logger.info("Raw Input ready: mouse=True keyboard=True hwnd=%s", self.hwnd)
        elif not ready:
            self._logger.warning(
                "RegisterRawInputDevices failed: hwnd=%s winerror=%s",
                self.hwnd,
                self.last_raw_input_error,
            )

    def _refresh_active(self) -> None:
        if self.force_active:
            snapshot = (0, "forced-active", "", "")
            active = True
        else:
            snapshot = self._foreground_snapshot()
            active = is_game_window(snapshot[1], snapshot[2], snapshot[3])
        identity = snapshot[:1] + snapshot[2:]
        if identity != self._last_foreground_identity:
            self._logger.info(
                "Foreground: hwnd=%s title=%r class=%r process=%r game=%s",
                snapshot[0],
                snapshot[1],
                snapshot[2],
                snapshot[3],
                active,
            )
            self._last_foreground_identity = identity
        if active != self._active:
            self._logger.info("Game input active: %s -> %s", self._active, active)
            self._active = active
        now = time.monotonic()
        if not self.hotkey_registered and now - self._last_hotkey_attempt >= 1.0:
            self._register_hotkey()
        if now - self._last_raw_registration >= 2.0:
            self._register_raw_devices()

    def _poll_async_input(self) -> None:
        mapping = {
            VK_OEM_3: "toggle_play",
            VK_XBUTTON1: "x",
            VK_XBUTTON2: "x2",
        }
        for vkey, action in mapping.items():
            down = bool(_USER32.GetAsyncKeyState(vkey) & 0x8000)
            if down and not self._async_down[vkey]:
                self._enqueue(action, "async-state")
            self._async_down[vkey] = down

    def _handle_raw_input(self, handle: int) -> None:
        size = wintypes.UINT()
        header_size = sizeof(RawInputHeader)
        if _USER32.GetRawInputData(handle, RID_INPUT, None, byref(size), header_size) != 0:
            return
        buffer = create_string_buffer(size.value)
        if (
            _USER32.GetRawInputData(handle, RID_INPUT, buffer, byref(size), header_size)
            != size.value
        ):
            return
        raw = cast(buffer, POINTER(RawInput)).contents
        if raw.header.type == RIM_TYPEMOUSE:
            flags = raw.data.mouse.detail.flags
            if flags:
                self._logger.debug("Raw mouse packet: button_flags=0x%X", flags)
            for button in actions_from_mouse_flags(flags):
                self._enqueue(button, "raw-mouse")
        elif raw.header.type == RIM_TYPEKEYBOARD:
            action = keyboard_action(raw.data.keyboard.vkey, raw.data.keyboard.message)
            if action:
                self._logger.debug(
                    "Raw keyboard packet: vkey=0x%X message=0x%X",
                    raw.data.keyboard.vkey,
                    raw.data.keyboard.message,
                )
                self._enqueue(action, "raw-keyboard")

    def _run(self) -> None:
        user32 = _USER32
        kernel32 = _KERNEL32
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.RegisterClassW.argtypes = (POINTER(WindowClass),)
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.INT,
            wintypes.INT,
            wintypes.INT,
            wintypes.INT,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        )
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.GetForegroundWindow.argtypes = ()
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextW.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            wintypes.INT,
        )
        user32.GetWindowTextW.restype = wintypes.INT
        user32.GetClassNameW.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            wintypes.INT,
        )
        user32.GetClassNameW.restype = wintypes.INT
        user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetAsyncKeyState.argtypes = (wintypes.INT,)
        user32.GetAsyncKeyState.restype = c_short
        user32.RegisterHotKey.argtypes = (
            wintypes.HWND,
            wintypes.INT,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, wintypes.INT)
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.RegisterRawInputDevices.argtypes = (
            POINTER(RawInputDevice),
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.RegisterRawInputDevices.restype = wintypes.BOOL
        user32.GetRawInputData.argtypes = (
            wintypes.HANDLE,
            wintypes.UINT,
            wintypes.LPVOID,
            POINTER(wintypes.UINT),
            wintypes.UINT,
        )
        user32.GetRawInputData.restype = wintypes.UINT
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            c_size_t,
            c_ssize_t,
        )
        user32.PostMessageW.restype = wintypes.BOOL
        user32.SetTimer.argtypes = (
            wintypes.HWND,
            c_size_t,
            wintypes.UINT,
            c_void_p,
        )
        user32.SetTimer.restype = c_size_t
        user32.GetMessageW.argtypes = (
            POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = (POINTER(wintypes.MSG),)
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = (POINTER(wintypes.MSG),)
        user32.DispatchMessageW.restype = c_ssize_t
        user32.DefWindowProcW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            c_size_t,
            c_ssize_t,
        )
        user32.DefWindowProcW.restype = c_ssize_t
        self.thread_id = kernel32.GetCurrentThreadId()
        window_proc_type = WINFUNCTYPE(
            c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            c_size_t,
            c_ssize_t,
        )

        def window_proc(hwnd, message, wparam, lparam):
            if message == WM_TIMER:
                now = time.monotonic()
                if now - self._last_foreground_check >= 0.12:
                    self._last_foreground_check = now
                    self._refresh_active()
                self._poll_async_input()
                return 0
            if message == WM_HOTKEY and wparam == HOTKEY_ID:
                self._enqueue("toggle_play", "register-hotkey")
                return 0
            if message == WM_INPUT:
                self._handle_raw_input(lparam)
                return 0
            if message == WM_APP_ACTION:
                action = {1: "toggle_play", 2: "x", 3: "x2"}.get(int(wparam), "")
                self._enqueue(action)
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        try:
            self._window_proc_callback = window_proc_type(window_proc)
            class_name = f"MabaoNativeInput_{os.getpid()}_{id(self)}"
            instance = kernel32.GetModuleHandleW(None)
            window_class = WindowClass(
                0,
                cast(self._window_proc_callback, c_void_p),
                0,
                0,
                instance,
                None,
                None,
                None,
                None,
                class_name,
            )
            if not user32.RegisterClassW(byref(window_class)):
                raise OSError("RegisterClassW failed")
            self.hwnd = user32.CreateWindowExW(
                0, class_name, class_name, 0, 0, 0, 0, 0, None, None, instance, None
            )
            if not self.hwnd:
                raise OSError("CreateWindowExW failed")
            self._register_raw_devices()
            self._register_hotkey()
            user32.SetTimer(self.hwnd, TIMER_ID, 15, None)
            self._refresh_active()
            self.ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(byref(message))
                user32.DispatchMessageW(byref(message))
        except Exception as exc:
            self.startup_error = str(exc)
            self.ready.set()
        finally:
            if self.hotkey_registered:
                user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self.hotkey_registered = False
            self.raw_keyboard_registered = False
            self.keyboard_registered = False
            self.hwnd = None


def debounce_action(method, minimum_interval: float = 0.18):
    last_called = 0.0

    def wrapped(*args, **kwargs):
        nonlocal last_called
        now = time.monotonic()
        if now - last_called < minimum_interval:
            return None
        last_called = now
        return method(*args, **kwargs)

    return wrapped


def default_settings_path() -> Path:
    override = os.environ.get("MABAO_LOCAL_SETTINGS_PATH", "").strip()
    if override:
        return Path(override)
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "MabaoLocal" / "settings.json"


class PlaybackSpeedState:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self.rate = self._load()

    def _load(self) -> float:
        try:
            value = float(json.loads(self.path.read_text(encoding="utf-8"))["playback_rate"])
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return PLAYBACK_RATES[0]
        return value if value in PLAYBACK_RATES else PLAYBACK_RATES[0]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"playback_rate": self.rate}, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def cycle(self) -> float:
        index = PLAYBACK_RATES.index(self.rate)
        self.rate = PLAYBACK_RATES[(index + 1) % len(PLAYBACK_RATES)]
        self._save()
        return self.rate


def playback_speed_script(rate: float) -> str:
    value = f"{rate:g}"
    return f"""
(() => {{
  window.__mabaoPlaybackRate = {value};
  const apply = () => document.querySelectorAll('video').forEach(video => {{
    video.defaultPlaybackRate = window.__mabaoPlaybackRate;
    video.playbackRate = window.__mabaoPlaybackRate;
  }});
  apply();
  if (window.__mabaoPlaybackObserver) window.__mabaoPlaybackObserver.disconnect();
  if (window.__mabaoPlaybackApply) {{
    document.removeEventListener('play', window.__mabaoPlaybackApply, true);
  }}
  window.__mabaoPlaybackApply = apply;
  document.addEventListener('play', window.__mabaoPlaybackApply, true);
  window.__mabaoPlaybackObserver = new MutationObserver(apply);
  window.__mabaoPlaybackObserver.observe(document.documentElement, {{
    childList: true, subtree: true, attributes: true, attributeFilter: ['src']
  }});
  return window.__mabaoPlaybackRate;
}})();
"""
