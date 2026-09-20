from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from eryou_assistant.ui.main_window import MainWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    QApplication.setApplicationName("二游辅助")
    QApplication.setOrganizationName("eryou-assistant")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    icon_candidates = (
        Path(__file__).with_name("resources") / "eryou_assistant_icon.ico",
        Path(__file__).parents[3] / "assets" / "eryou_assistant_icon.ico",
    )
    for icon_path in icon_candidates:
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break
    _configure_font(app)
    return app


def _configure_font(app: QApplication) -> None:
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))


def main() -> int:
    app = create_application()
    window = MainWindow()
    window.show()
    return app.exec()
