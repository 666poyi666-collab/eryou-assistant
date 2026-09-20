from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from eryou_assistant.core.subtitle import DirectionMatch, subtitle_display_ms


class _Overlay(QWidget):
    def __init__(self, width: int, height: int) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setFixedSize(width, height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "background: rgba(20, 24, 28, 188); color: white; "
            "border: 1px solid rgba(255,255,255,90); border-radius: 8px;"
        )
        layout.addWidget(self.label)


class DirectionOverlay(_Overlay):
    def __init__(self) -> None:
        super().__init__(180, 180)
        self.label.setFont(QFont(self.font().family(), 38, QFont.Weight.Bold))
        self.label.setText("·")
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._collapse)

    def _expand(self) -> None:
        self.label.setStyleSheet(
            "background: rgba(20, 24, 28, 188); color: white; "
            "border: 1px solid rgba(255,255,255,90); border-radius: 80px;"
        )

    def _collapse(self) -> None:
        self.label.setStyleSheet("background: transparent; color: white; border: 0;")

    def show_direction(self, match: DirectionMatch) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        if not self.isVisible():
            self.move(screen.left() + 48, screen.top() + 48)
        self.label.setText(f"{match.arrow}\n{match.name}")
        self._expand()
        self.show()
        self._collapse_timer.start(3000)


class TurnOverlay(_Overlay):
    def __init__(self) -> None:
        super().__init__(360, 200)
        self.label.setFont(QFont(self.font().family(), 46, QFont.Weight.Bold))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_turn(self, match: DirectionMatch) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - self.width() - 60
        if match.key == "right_turn":
            x = screen.center().x() + 60
        self.move(x, screen.center().y() - self.height() // 2)
        self.label.setText(f"{match.arrow}  {match.name}")
        self.show()
        self._timer.start(3000)


class SubtitleOverlay(_Overlay):
    def __init__(self) -> None:
        super().__init__(420, 56)
        self.label.setFont(QFont(self.font().family(), 12))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_subtitle(self, text: str) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(900, max(280, self.label.fontMetrics().horizontalAdvance(text) + 48))
        self.setFixedWidth(width)
        self.move(screen.left() + screen.width() // 3, screen.top() + screen.height() * 3 // 4)
        self.label.setText(text)
        self.show()
        self._timer.start(subtitle_display_ms(text))


class EnhancedOverlay(_Overlay):
    def __init__(self, source: QWidget) -> None:
        super().__init__(240, 96)
        self.source = source
        self.label.setFont(QFont(self.font().family(), 24, QFont.Weight.Bold))
        self.label.setScaledContents(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def mirror(self, match: DirectionMatch) -> None:
        screen = (
            QApplication.screenAt(self.source.geometry().center()) or QApplication.primaryScreen()
        )
        origin = self.source.mapToGlobal(self.source.rect().topLeft())
        pixmap = screen.grabWindow(
            0, origin.x(), origin.y(), self.source.width(), self.source.height()
        )
        if pixmap.isNull():
            self.label.setText(f"{match.arrow} {match.name}")
        else:
            self.label.setPixmap(pixmap)
        area = screen.availableGeometry()
        self.move(area.left() + area.width() // 3, area.top() + area.height() * 2 // 3)
        self.show()
        self._timer.start(2000)
