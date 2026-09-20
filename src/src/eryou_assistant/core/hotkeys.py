from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
PUNCTUATION = {"~": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "/": 0xBF}
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B}


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    if not parts:
        raise KeyError("empty hotkey")
    modifiers = 0
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise KeyError(f"unknown modifier: {part}")
        modifiers |= MODIFIERS[part]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        virtual_key = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 0x6F + int(key[1:])
    else:
        virtual_key = PUNCTUATION.get(key, NAMED_KEYS.get(key, 0))
    if not virtual_key:
        raise KeyError(f"unknown key: {key}")
    return modifiers, virtual_key


class GlobalHotkeyManager(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 0x4200
        app.installNativeEventFilter(self)

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        if sys.platform != "win32" or not hotkey:
            return False
        try:
            modifiers, virtual_key = parse_hotkey(hotkey)
        except KeyError:
            return False
        hotkey_id = self._next_id
        if not ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key):
            return False
        self._callbacks[hotkey_id] = callback
        self._next_id += 1
        return True

    def unregister_all(self) -> None:
        if sys.platform == "win32":
            for hotkey_id in self._callbacks:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if sys.platform == "win32" and event_type in {
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        }:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and int(msg.wParam) in self._callbacks:
                self._callbacks[int(msg.wParam)]()
                return True, 0
        return False, 0
