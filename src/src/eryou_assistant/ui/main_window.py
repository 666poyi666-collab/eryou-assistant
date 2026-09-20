from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from eryou_assistant import __version__
from eryou_assistant.core.features import FEATURES
from eryou_assistant.core.guides import GuideStore
from eryou_assistant.core.hotkeys import GlobalHotkeyManager
from eryou_assistant.core.immersive import ImmersiveController, set_click_through
from eryou_assistant.core.settings import SettingsStore
from eryou_assistant.ui.pages import (
    BrowserPage,
    DialogPage,
    DirectionPage,
    SettingsPage,
    VisionPage,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("二游辅助")
        self.setMinimumSize(QSize(960, 620))
        self.settings_store = SettingsStore()
        self.guide_store = GuideStore(self.settings_store.config_dir / "guides.json")
        self._mouse_passthrough = False
        self._local_shortcuts: list[QShortcut] = []

        preset_window = self.settings_store.active_preset["window"]
        self.resize(int(preset_window["width"]), int(preset_window["height"]))
        if isinstance(preset_window.get("x"), int) and isinstance(preset_window.get("y"), int):
            self.move(int(preset_window["x"]), int(preset_window["y"]))

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.browser_page = BrowserPage(self.guide_store)
        self.direction_page = DirectionPage()
        self.dialog_page = DialogPage(self.settings_store.config_dir)
        self.vision_page = VisionPage()
        self.settings_page = SettingsPage(self.settings_store)
        for page in (
            self.browser_page,
            self.direction_page,
            self.dialog_page,
            self.vision_page,
            self.settings_page,
        ):
            self.pages.addWidget(page)
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self.browser_page.subtitle_changed.connect(self.direction_page.consume_subtitle)
        self.vision_page.pose_changed.connect(self.direction_page.consume_pose)
        self.vision_page.region_changed.connect(self._persist_ai_region)
        self.settings_page.settings_applied.connect(self.apply_settings)
        for control in (
            self.direction_page.enabled,
            self.direction_page.subtitle_enabled,
            self.direction_page.turn_enabled,
            self.direction_page.enhanced_enabled,
            self.dialog_page.live,
            self.vision_page.live,
            self.vision_page.edge,
        ):
            control.toggled.connect(self._persist_runtime_controls)
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplication must exist before MainWindow")
        self.hotkeys = GlobalHotkeyManager(app)
        self.immersive = ImmersiveController(self)
        self.apply_settings()
        self._apply_styles()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(8)

        brand = QLabel("二游辅助")
        brand.setObjectName("brand")
        brand.setFont(QFont(self.font().family(), 15, QFont.Weight.DemiBold))
        layout.addWidget(brand)
        layout.addSpacing(18)

        group = QButtonGroup(self)
        group.setExclusive(True)
        icons = (
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_ArrowUp,
            QStyle.StandardPixmap.SP_MediaPlay,
            QStyle.StandardPixmap.SP_DriveNetIcon,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        for index, (feature, icon) in enumerate(zip(FEATURES, icons, strict=True)):
            button = QPushButton(feature.title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(self.style().standardIcon(icon))
            button.setIconSize(QSize(18, 18))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setFixedHeight(42)
            button.clicked.connect(
                lambda checked=False, page=index: self.pages.setCurrentIndex(page)
            )
            group.addButton(button)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        layout.addStretch(1)
        footer = QLabel(f"免费开源 · {__version__}")
        footer.setObjectName("footer")
        layout.addWidget(footer)
        return sidebar

    def apply_settings(self) -> None:
        preset = self.settings_store.active_preset
        window = preset["window"]
        self.setWindowOpacity(int(window["transparency"]) / 100)
        self.immersive.configure(
            preset["immersive"],
            base_opacity=int(window["transparency"]) / 100,
        )
        self._mouse_passthrough = bool(window.get("mouse_passthrough", False))
        direction = preset["direction"]
        self.direction_page.enabled.setChecked(bool(direction["enabled"]))
        self.direction_page.subtitle_enabled.setChecked(bool(direction["subtitle_sprite"]))
        self.direction_page.turn_enabled.setChecked(bool(direction["turn_enabled"]))
        self.direction_page.enhanced_enabled.setChecked(bool(direction["enhanced_enabled"]))
        dialog = preset["dialog"]
        self.dialog_page.live.setChecked(bool(dialog["enabled"]))
        self.dialog_page.real_input.setChecked(
            bool(dialog["allow_real_input"]) and self.dialog_page.real_input.isEnabled()
        )
        vision = preset["vision"]
        self.vision_page.edge.setChecked(bool(vision["edge_enhance"]))
        region = vision.get("region")
        if isinstance(region, list) and len(region) == 4:
            self.vision_page.capture_region = QRect(*map(int, region))
        self.vision_page.live.setChecked(bool(vision.get("live", False)))
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            bool(window["always_on_top"]),
        )
        set_click_through(self, self._mouse_passthrough)
        self.immersive.set_enabled(self._mouse_passthrough)
        self.hotkeys.unregister_all()
        for shortcut in self._local_shortcuts:
            shortcut.deleteLater()
        self._local_shortcuts.clear()
        seconds = int(preset["video_skip_seconds"])
        callbacks = {
            "toggle_play": self.browser_page.toggle_play,
            "fast_forward": lambda: self.browser_page.seek_video(seconds),
            "fast_backward": lambda: self.browser_page.seek_video(-seconds),
            "next_episode": self.browser_page.next_episode,
            "prev_episode": self.browser_page.previous_episode,
            "toggle_visible": self.toggle_visible,
            "toggle_mouse_passthrough": self.toggle_mouse_passthrough,
            "toggle_auto_dialog": lambda: self.dialog_page.live.toggle(),
            "toggle_always_on_top": self.toggle_always_on_top,
        }
        for action, hotkey in preset["hotkeys"].items():
            if action in callbacks and hotkey:
                function_keys = {f"F{index}" for index in range(1, 25)}
                if len(hotkey) == 1 and hotkey.upper() not in function_keys:
                    shortcut = QShortcut(QKeySequence(hotkey), self)
                    shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                    shortcut.activated.connect(callbacks[action])
                    self._local_shortcuts.append(shortcut)
                else:
                    self.hotkeys.register(hotkey, callbacks[action])
        self._apply_styles()
        if self.isVisible():
            self.show()

    def toggle_visible(self) -> None:
        self.hide() if self.isVisible() else self.show()

    def toggle_always_on_top(self) -> None:
        window = self.settings_store.active_preset["window"]
        window["always_on_top"] = not bool(window["always_on_top"])
        self.settings_store.save()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, window["always_on_top"])
        self.show()

    def _persist_runtime_controls(self) -> None:
        preset = self.settings_store.active_preset
        preset["direction"] = {
            "enabled": self.direction_page.enabled.isChecked(),
            "subtitle_sprite": self.direction_page.subtitle_enabled.isChecked(),
            "turn_enabled": self.direction_page.turn_enabled.isChecked(),
            "enhanced_enabled": self.direction_page.enhanced_enabled.isChecked(),
        }
        preset["dialog"]["enabled"] = self.dialog_page.live.isChecked()
        preset["vision"] = {
            "live": self.vision_page.live.isChecked(),
            "edge_enhance": self.vision_page.edge.isChecked(),
            "region": preset["vision"].get("region"),
        }
        self.settings_page.direction_enabled.setChecked(self.direction_page.enabled.isChecked())
        self.settings_page.subtitle_enabled.setChecked(
            self.direction_page.subtitle_enabled.isChecked()
        )
        self.settings_page.turn_enabled.setChecked(self.direction_page.turn_enabled.isChecked())
        self.settings_page.enhanced_enabled.setChecked(
            self.direction_page.enhanced_enabled.isChecked()
        )
        self.settings_page.dialog_enabled.setChecked(self.dialog_page.live.isChecked())
        self.settings_page.vision_live.setChecked(self.vision_page.live.isChecked())
        self.settings_page.vision_edge.setChecked(self.vision_page.edge.isChecked())
        self.settings_store.save()

    def _persist_ai_region(self, region: QRect) -> None:
        self.settings_store.active_preset["vision"]["region"] = [
            region.x(),
            region.y(),
            region.width(),
            region.height(),
        ]
        self.settings_store.save()

    def toggle_mouse_passthrough(self) -> None:
        self._mouse_passthrough = not self._mouse_passthrough
        self.settings_store.active_preset["window"]["mouse_passthrough"] = self._mouse_passthrough
        self.settings_store.save()
        set_click_through(self, self._mouse_passthrough)
        self.immersive.set_enabled(self._mouse_passthrough)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.hotkeys.unregister_all()
        self.browser_page.shutdown()
        self.dialog_page.shutdown()
        self.vision_page.shutdown()
        self.direction_page.close_overlays()
        window = self.settings_store.active_preset["window"]
        window["width"] = self.width()
        window["height"] = self.height()
        window["x"] = self.x()
        window["y"] = self.y()
        self.settings_store.save()
        super().closeEvent(event)

    def _apply_styles(self) -> None:
        dark = self.settings_store.active_preset["window"].get("theme") == "dark"
        page = "#20242a" if dark else "#f7f8fa"
        panel = "#2b3037" if dark else "#ffffff"
        text = "#f1f3f5" if dark else "#20242a"
        muted = "#b0b6be" if dark else "#4d555f"
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {page}; color: {text}; }}
            QFrame#sidebar {{ background: {panel}; border-right: 1px solid #59616b; }}
            QLabel#brand {{ color: {text}; }}
            QPushButton#navButton {{
                background: transparent; border: 0; border-radius: 6px; padding: 0 12px;
                text-align: left; color: {muted}; font-size: 14px;
            }}
            QPushButton#navButton:hover {{ background: #3a414a; color: {text}; }}
            QPushButton#navButton:checked {{ background: #2f6654; color: #ffffff; }}
            QPushButton {{ min-height: 30px; border: 1px solid #59616b; border-radius: 6px;
                background: {panel}; padding: 0 10px; }}
            QPushButton:hover {{ background: #3a414a; }}
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox {{
                background: {panel}; border: 1px solid #59616b; border-radius: 5px; padding: 6px;
            }}
            QLabel#featureResult {{ font-size: 18px; font-weight: 600; color: #38a77b; }}
            QLabel#footer {{ color: #89929d; font-size: 12px; }}
            """
        )
