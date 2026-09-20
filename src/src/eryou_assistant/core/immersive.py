from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMainWindow


class ImmersiveController(QObject):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.enabled = False
        self.hole_enabled = True
        self.hole_radius = 250
        self.smart_dodge = False
        self.anti_occlude = True
        self.base_opacity = 1.0
        self._last_dodge_at = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)

    def configure(self, settings: dict, *, base_opacity: float) -> None:
        self.hole_enabled = bool(settings.get("hole_enabled", True))
        self.hole_radius = max(40, int(settings.get("hole_radius", 250)))
        self.smart_dodge = bool(settings.get("smart_dodge", False))
        self.anti_occlude = bool(settings.get("anti_occlude", True))
        self.base_opacity = base_opacity

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self.timer.start()
        else:
            self.timer.stop()
            self.window.setWindowOpacity(self.base_opacity)
            self._clear_hole()

    def toggle(self) -> None:
        self.set_enabled(not self.enabled)

    def _tick(self) -> None:
        cursor = QCursor.pos()
        local = self.window.mapFromGlobal(cursor)
        inside = self.window.rect().contains(local)
        if self.hole_enabled and inside:
            self._set_hole(local)
        else:
            self._clear_hole()
        if self.anti_occlude:
            self.window.setWindowOpacity(
                min(self.base_opacity, 0.45) if inside else self.base_opacity
            )
        if self.smart_dodge and inside and time.monotonic() - self._last_dodge_at > 0.8:
            self._dodge(cursor)

    def _dodge(self, cursor: QPoint) -> None:
        screen = self.window.screen().availableGeometry()
        left = (
            screen.left() + 20
            if cursor.x() > screen.center().x()
            else screen.right() - self.window.width() - 20
        )
        top = (
            screen.top() + 20
            if cursor.y() > screen.center().y()
            else screen.bottom() - self.window.height() - 20
        )
        self.window.move(left, top)
        self._last_dodge_at = time.monotonic()

    def _set_hole(self, center: QPoint) -> None:
        if sys.platform != "win32" or not self.window.winId():
            return
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        width, height = self.window.width(), self.window.height()
        base = gdi32.CreateRectRgn(0, 0, width, height)
        hole = gdi32.CreateEllipticRgn(
            center.x() - self.hole_radius,
            center.y() - self.hole_radius,
            center.x() + self.hole_radius,
            center.y() + self.hole_radius,
        )
        combined = gdi32.CreateRectRgn(0, 0, 0, 0)
        gdi32.CombineRgn(combined, base, hole, 4)
        user32.SetWindowRgn(int(self.window.winId()), combined, True)
        gdi32.DeleteObject(base)
        gdi32.DeleteObject(hole)

    def _clear_hole(self) -> None:
        if sys.platform == "win32" and self.window.winId():
            ctypes.windll.user32.SetWindowRgn(int(self.window.winId()), 0, True)


def set_click_through(window: QMainWindow, enabled: bool) -> None:
    window.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
    window.show()
