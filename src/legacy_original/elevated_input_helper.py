from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import (
    WINFUNCTYPE,
    Structure,
    byref,
    c_int,
    c_long,
    c_short,
    c_size_t,
    c_ssize_t,
    wintypes,
)
from pathlib import Path

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_XBUTTONDOWN = 0x020B
WM_QUIT = 0x0012
WM_APP_ACTION = 0x8001
VK_OEM_3 = 0xC0
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06
TASK_NAME = "MabaoLocalGameInput"
HELPER_NAME = "mabao-game-input-helper.exe"
WINDOW_CLASS_PREFIX = "MabaoNativeInput_"
KEY_ACTIONS = {VK_OEM_3: 1, VK_LEFT: 2, VK_RIGHT: 3}

USER32 = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
HOOKPROC = WINFUNCTYPE(c_ssize_t, c_int, c_size_t, c_ssize_t)
ENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_post_lock = threading.Lock()
_last_posted: dict[int, float] = {}


class Point(Structure):
    _fields_ = (("x", c_long), ("y", c_long))


class KeyboardHookData(Structure):
    _fields_ = (
        ("vk_code", wintypes.DWORD),
        ("scan_code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", c_size_t),
    )


class MouseHookData(Structure):
    _fields_ = (
        ("point", Point),
        ("mouse_data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", c_size_t),
    )


def log_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / "MabaoLocal" / "logs" / "game-input-helper.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging() -> None:
    logging.basicConfig(
        filename=log_path(),
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def find_bridge_window() -> int:
    found = 0

    @ENUMPROC
    def visit(hwnd, _lparam):
        nonlocal found
        class_name = ctypes.create_unicode_buffer(256)
        USER32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value.startswith(WINDOW_CLASS_PREFIX):
            found = int(hwnd)
            return False
        return True

    USER32.EnumWindows(visit, 0)
    return found


def post_action(code: int, source: str) -> None:
    now = time.monotonic()
    with _post_lock:
        if now - _last_posted.get(code, 0.0) < 0.12:
            return
        _last_posted[code] = now
    hwnd = find_bridge_window()
    if hwnd and USER32.PostMessageW(hwnd, WM_APP_ACTION, code, 0):
        logging.info("posted source=%s action_code=%s hwnd=%s", source, code, hwnd)
    else:
        logging.debug("no bridge target source=%s action_code=%s", source, code)


def install_task() -> int:
    """（需要管理员）注册一个「提权启动器」任务，然后立刻跑起来。

    2026-09-20 安全性调整：
      * 不再把 helper 复制到 Program Files，直接在程序目录里运行（删程序就干净）；
      * 任务用 /SC ONCE + 2030 年的日期，等于「永不自动触发」，只作为
        schtasks /Run 的提权入口 —— 不再是 ONLOGON 常驻自启；
      * helper 自己会在主程序消失 30~60 秒后退出，提权钩子的存活期 = 主程序存活期。
    """
    source = Path(sys.executable).resolve()
    subprocess.run(
        ["schtasks", "/End", "/TN", TASK_NAME],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    task_action = f'"{source}" --daemon'
    result = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONCE",
            "/SD",
            "2030/01/01",
            "/ST",
            "00:00",
            "/RL",
            "HIGHEST",
            "/IT",
            "/TR",
            task_action,
            "/F",
        ],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    logging.info(
        "install task returncode=%s stdout=%r stderr=%r",
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if result.returncode:
        return result.returncode
    run = subprocess.run(
        ["schtasks", "/Run", "/TN", TASK_NAME],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    logging.info("start task returncode=%s", run.returncode)
    return run.returncode


def run_daemon() -> int:
    USER32.EnumWindows.argtypes = (ENUMPROC, wintypes.LPARAM)
    USER32.EnumWindows.restype = wintypes.BOOL
    USER32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, c_int)
    USER32.GetClassNameW.restype = c_int
    USER32.PostMessageW.argtypes = (
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    USER32.PostMessageW.restype = wintypes.BOOL
    USER32.SetWindowsHookExW.argtypes = (
        c_int,
        HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    )
    USER32.SetWindowsHookExW.restype = wintypes.HANDLE
    USER32.CallNextHookEx.argtypes = (
        wintypes.HANDLE,
        c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    USER32.CallNextHookEx.restype = c_ssize_t
    USER32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
    USER32.UnhookWindowsHookEx.restype = wintypes.BOOL
    USER32.GetMessageW.argtypes = (
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    )
    USER32.GetMessageW.restype = wintypes.BOOL
    USER32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    USER32.TranslateMessage.restype = wintypes.BOOL
    USER32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    USER32.DispatchMessageW.restype = c_ssize_t
    USER32.PostThreadMessageW.argtypes = (
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    USER32.PostThreadMessageW.restype = wintypes.BOOL
    USER32.GetAsyncKeyState.argtypes = (c_int,)
    USER32.GetAsyncKeyState.restype = c_short
    KERNEL32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    KERNEL32.CreateMutexW.restype = wintypes.HANDLE
    KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    KERNEL32.CloseHandle.restype = wintypes.BOOL
    mutex = KERNEL32.CreateMutexW(None, False, r"Local\MabaoLocalGameInputHelper")
    if not mutex or ctypes.get_last_error() == 183:
        return 0

    thread_id = KERNEL32.GetCurrentThreadId()
    keyboard_down: set[int] = set()

    @HOOKPROC
    def keyboard_proc(code, message, data_pointer):
        if code == HC_ACTION:
            data = ctypes.cast(data_pointer, ctypes.POINTER(KeyboardHookData)).contents
            action = KEY_ACTIONS.get(data.vk_code)
            if action:
                if message in {WM_KEYDOWN, WM_SYSKEYDOWN} and data.vk_code not in keyboard_down:
                    keyboard_down.add(data.vk_code)
                    post_action(action, f"elevated-keyboard-vk-{data.vk_code:02x}")
                elif message in {WM_KEYUP, WM_SYSKEYUP}:
                    keyboard_down.discard(data.vk_code)
        return USER32.CallNextHookEx(None, code, message, data_pointer)

    @HOOKPROC
    def mouse_proc(code, message, data_pointer):
        if code == HC_ACTION and message == WM_XBUTTONDOWN:
            data = ctypes.cast(data_pointer, ctypes.POINTER(MouseHookData)).contents
            button = (data.mouse_data >> 16) & 0xFFFF
            if button == 1:
                post_action(2, "elevated-x1")
            elif button == 2:
                post_action(3, "elevated-x2")
        return USER32.CallNextHookEx(None, code, message, data_pointer)

    keyboard_hook = USER32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, None, 0)
    keyboard_error = 0 if keyboard_hook else ctypes.get_last_error()
    mouse_hook = USER32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, None, 0)
    mouse_error = 0 if mouse_hook else ctypes.get_last_error()
    logging.info(
        "helper ready pid=%s keyboard=%s keyboard_error=%s mouse=%s mouse_error=%s",
        os.getpid(),
        bool(keyboard_hook),
        keyboard_error,
        bool(mouse_hook),
        mouse_error,
    )
    if not keyboard_hook or not mouse_hook:
        return 2

    def poll_key_state() -> None:
        down = {key: False for key in (*KEY_ACTIONS, VK_XBUTTON1, VK_XBUTTON2)}
        mapping = {
            **KEY_ACTIONS,
            VK_XBUTTON1: 2,
            VK_XBUTTON2: 3,
        }
        while True:
            for key, action in mapping.items():
                current = bool(USER32.GetAsyncKeyState(key) & 0x8000)
                if current and not down[key]:
                    post_action(action, f"elevated-async-vk-{key:02x}")
                down[key] = current
            time.sleep(0.01)

    threading.Thread(target=poll_key_state, name="MabaoHelperKeyState", daemon=True).start()

    def monitor_target() -> None:
        seen = False
        started = time.monotonic()
        missing_since = 0.0
        while True:
            if find_bridge_window():
                seen = True
                missing_since = 0.0
            elif seen:
                missing_since = missing_since or time.monotonic()
                if time.monotonic() - missing_since >= 30:
                    USER32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
                    return
            elif time.monotonic() - started >= 60:
                USER32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
                return
            time.sleep(2)

    threading.Thread(target=monitor_target, name="MabaoHelperMonitor", daemon=True).start()
    message = wintypes.MSG()
    while USER32.GetMessageW(byref(message), None, 0, 0) > 0:
        USER32.TranslateMessage(byref(message))
        USER32.DispatchMessageW(byref(message))
    USER32.UnhookWindowsHookEx(keyboard_hook)
    USER32.UnhookWindowsHookEx(mouse_hook)
    KERNEL32.CloseHandle(mutex)
    return 0


def main() -> int:
    configure_logging()
    if "--install-task" in sys.argv:
        return install_task()
    return run_daemon()


if __name__ == "__main__":
    raise SystemExit(main())
