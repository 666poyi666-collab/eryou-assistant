from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qtwebview2 import QtWebView2Widget
from qtwebview2 import _dotnet_bridge as webview2_dotnet

from eryou_assistant.core.auto_dialog import (
    AutoDialogEngine,
    foreground_window_snapshot,
    match_game,
)
from eryou_assistant.core.guides import GuideEntry, GuideStore, normalize_url
from eryou_assistant.core.settings import DEFAULT_HOTKEYS, SettingsStore
from eryou_assistant.core.subtitle import DirectionMatch, SubtitleParser
from eryou_assistant.core.vision import (
    ConeAngleDetector,
    FeatureLocator,
    ai_dependencies_available,
)
from eryou_assistant.ui.overlays import (
    DirectionOverlay,
    EnhancedOverlay,
    SubtitleOverlay,
    TurnOverlay,
)


class RequestBlocker:
    BLOCKED = (
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "adservice.",
        "/adserver/",
        "/advert/",
        "tracking.",
    )

    @classmethod
    def should_block(cls, target: str) -> bool:
        return any(marker in target.casefold() for marker in cls.BLOCKED)


class BrowserPage(QWidget):
    subtitle_changed = Signal(str)
    _web_url_changed = Signal(str)
    _web_title_changed = Signal(str)
    _navigate_requested = Signal(str)

    def __init__(self, store: GuideStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._title = ""
        self._last_subtitle = ""
        self._blocker = RequestBlocker()
        self._webview_core = None
        self._current_url = "about:blank"
        self._web_url_changed.connect(self._on_url_changed)
        self._web_title_changed.connect(self._on_title_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        self.back_button = self._tool_button(QStyle.StandardPixmap.SP_ArrowBack, self.go_back)
        self.forward_button = self._tool_button(
            QStyle.StandardPixmap.SP_ArrowForward, self.go_forward
        )
        self.reload_button = self._tool_button(QStyle.StandardPixmap.SP_BrowserReload, self.reload)
        self.address = QLineEdit()
        self.address.setPlaceholderText("网址")
        self.address.returnPressed.connect(self.navigate)
        self.bookmark_button = QPushButton("☆")
        self.bookmark_button.setFixedWidth(38)
        self.bookmark_button.clicked.connect(self.toggle_bookmark)
        bookmarks = QPushButton("收藏")
        bookmarks.clicked.connect(lambda: self._show_entries("收藏", self.store.bookmarks))
        history = QPushButton("历史")
        history.clicked.connect(
            lambda: self._show_entries("历史", list(reversed(self.store.history)))
        )
        for widget in (
            self.back_button,
            self.forward_button,
            self.reload_button,
            self.address,
            self.bookmark_button,
            bookmarks,
            history,
        ):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)

        media = QHBoxLayout()
        for label, callback in (
            ("上一集", self.previous_episode),
            ("快退", lambda: self.seek_video(-5)),
            ("播放/暂停", self.toggle_play),
            ("快进", lambda: self.seek_video(5)),
            ("下一集", self.next_episode),
            ("网页全屏", self.toggle_web_fullscreen),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            media.addWidget(button)
        media.addStretch(1)
        layout.addLayout(media)

        self.web = QtWebView2Widget(
            parent=self,
            lazyload=True,
            context_menus=True,
            handle_new_window=False,
            background_color="#ffffff",
            js_apis={"on_subtitle_change": self._on_subtitle_message},
            init_settings_hook=self._configure_webview,
        )
        self._navigate_requested.connect(self.web.load_url)
        self.web.bridge.domContentLoaded.connect(self._install_page_bridge)
        layout.addWidget(self.web, 1)
        if self.store.last_url.startswith(("http://", "https://")):
            self.web.load_url(self.store.last_url)
        else:
            self.web.load_html(self._home_html())

        self.subtitle_timer = QTimer(self)
        self.subtitle_timer.setInterval(800)
        self.subtitle_timer.timeout.connect(self._poll_subtitle)
        self.subtitle_timer.start()
        self._shutdown = False

    def _tool_button(self, icon, callback) -> QPushButton:
        button = QPushButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setFixedSize(36, 34)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _home_html() -> str:
        return """<!doctype html><html><head><meta charset='utf-8'><style>
        body{font-family:'Microsoft YaHei',sans-serif;background:#f7f8fa;color:#20242a;margin:0;
        display:grid;place-items:center;height:100vh}h1{font-size:28px;font-weight:600}
        </style></head><body><h1>二游辅助</h1></body></html>"""

    def navigate(self) -> None:
        try:
            target = normalize_url(self.address.text())
        except ValueError as error:
            QMessageBox.warning(self, "地址无效", str(error))
            return
        self.web.load_url(target)

    def _configure_webview(self, core) -> None:
        self._webview_core = core
        core.AddWebResourceRequestedFilter(
            "*", webview2_dotnet.Core.CoreWebView2WebResourceContext.All
        )
        core.WebResourceRequested += self._on_web_resource_requested
        core.NavigationCompleted += self._on_navigation_completed
        core.DocumentTitleChanged += self._on_document_title_changed
        core.NewWindowRequested += self._on_new_window_requested

    def _on_web_resource_requested(self, sender, args) -> None:
        if self._blocker.should_block(str(args.Request.Uri)):
            args.Response = sender.Environment.CreateWebResourceResponse(
                None, 403, "Blocked", "Content-Type: text/plain"
            )

    def _on_navigation_completed(self, sender, args) -> None:
        self._web_url_changed.emit(str(sender.Source))

    def _on_document_title_changed(self, sender, args) -> None:
        self._web_title_changed.emit(str(sender.DocumentTitle or ""))

    def _on_new_window_requested(self, sender, args) -> None:
        args.Handled = True
        self._navigate_requested.emit(str(args.Uri))

    def _install_page_bridge(self) -> None:
        self.web.evaluate_js(
            """
            if (window.__eryouSubtitleObserver) window.__eryouSubtitleObserver.disconnect();
            const selectors = [
              '.bili-subtitle-x-subtitle-panel-wrap span',
              '.bpx-player-subtitle-panel-text',
              '[class*="subtitle"] span'
            ];
            const adSelectors = [
              '.ad-report',
              '[class*="video-card-ad"]',
              '[class*="commercial-card"]',
              '[class*="slide-ad"]',
              'a[href*="cm.bilibili.com"]',
              'a[href*="ad.bilibili.com"]'
            ];
            const removeAds = () => {
              document.querySelectorAll(adSelectors.join(',')).forEach(node => {
                const card = node.closest('aside, article, li') || node;
                card.style.setProperty('display', 'none', 'important');
              });
              document.querySelectorAll('span, div').forEach(node => {
                if ((node.textContent || '').trim() !== '\\u5e7f\\u544a') return;
                const card = node.closest('a') || node.parentElement;
                if (card) card.style.setProperty('display', 'none', 'important');
              });
            };
            let lastText = '';
            const publish = () => {
              removeAds();
              for (const selector of selectors) {
                const text = [...document.querySelectorAll(selector)]
                  .map(node => node.innerText || node.textContent || '')
                  .join(' ').trim();
                if (text && text !== lastText) {
                  lastText = text;
                  window.qtwebview2.api.on_subtitle_change(text);
                  break;
                }
              }
            };
            window.__eryouSubtitleObserver = new MutationObserver(publish);
            window.__eryouSubtitleObserver.observe(document.documentElement, {
              childList: true, subtree: true, characterData: true
            });
            const subtitleButton = document.querySelector(
              'div.bpx-player-ctrl-subtitle-result'
            );
            if (subtitleButton) {
              subtitleButton.click();
              setTimeout(() => {
                const language = document.querySelector(
                  'div.bpx-player-ctrl-subtitle-language-item-text'
                );
                if (language) language.click();
              }, 350);
            }
            publish();
            return true;
            """
        )

    def _on_subtitle_message(self, text: str) -> bool:
        self._accept_subtitle({"success": True, "result": text})
        return True

    def _on_url_changed(self, text: str) -> None:
        self._current_url = text or "about:blank"
        if text and text != "about:blank":
            self.address.setText(text)
            self.bookmark_button.setText("★" if self.store.is_bookmarked(text) else "☆")
            try:
                self.store.record_visit(self._title or text, text)
            except ValueError:
                pass

    def _on_title_changed(self, title: str) -> None:
        self._title = title
        self.store.update_last_title(self._current_url, title)

    def toggle_bookmark(self) -> None:
        url = self._current_url
        if url == "about:blank":
            return
        added = self.store.toggle_bookmark(self._title or url, url)
        self.bookmark_button.setText("★" if added else "☆")

    def _show_entries(self, title: str, entries: list[GuideEntry]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(680, 440)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText("搜索")
        result_list = QListWidget()

        def refill(query: str = "") -> None:
            result_list.clear()
            for entry in entries:
                if query.casefold() not in f"{entry.title} {entry.url}".casefold():
                    continue
                item_text = f"{entry.title}\n{entry.url}"
                result_list.addItem(item_text)

        refill()
        search.textChanged.connect(refill)

        def open_selected() -> None:
            row = result_list.currentRow()
            filtered = [
                entry
                for entry in entries
                if search.text().casefold() in f"{entry.title} {entry.url}".casefold()
            ]
            if 0 <= row < len(filtered):
                self.web.load_url(filtered[row].url)
                dialog.accept()

        def delete_selected() -> None:
            row = result_list.currentRow()
            filtered = [
                entry
                for entry in entries
                if search.text().casefold() in f"{entry.title} {entry.url}".casefold()
            ]
            if not 0 <= row < len(filtered):
                return
            entry = filtered[row]
            if title == "收藏":
                self.store.remove_bookmark(entry.url)
            else:
                self.store.remove_history(entry.visited_at)
            entries[:] = [item for item in entries if item is not entry]
            refill(search.text())

        def clear_history() -> None:
            self.store.clear_history()
            entries.clear()
            refill()

        result_list.itemDoubleClicked.connect(lambda _: open_selected())
        layout.addWidget(search)
        layout.addWidget(result_list)
        actions = QHBoxLayout()
        delete_button = QPushButton("删除所选")
        delete_button.clicked.connect(delete_selected)
        actions.addWidget(delete_button)
        if title == "历史":
            clear_button = QPushButton("清空历史")
            clear_button.clicked.connect(clear_history)
            actions.addWidget(clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        dialog.show()
        self._entries_dialog = dialog

    def _poll_subtitle(self) -> None:
        if not self._current_url.startswith(("http://", "https://")):
            return
        script = """
        (() => {
          const selectors = [
            '.bili-subtitle-x-subtitle-panel-wrap span',
            '.bpx-player-subtitle-panel-text',
            '[class*="subtitle"] span'
          ];
          for (const selector of selectors) {
            const text = [...document.querySelectorAll(selector)]
              .map(node => node.innerText || node.textContent || '').join(' ').trim();
            if (text) return text;
          }
          return '';
        })();
        """
        self.web.evaluate_js(f"return {script}", self._accept_subtitle)

    def _accept_subtitle(self, response) -> None:
        text = response.get("result", "") if response.get("success") else ""
        value = str(text or "").strip()
        if value and value != self._last_subtitle:
            self._last_subtitle = value
            self.subtitle_changed.emit(value)

    def go_back(self) -> None:
        if self.web.is_ready and self.web._webview.CoreWebView2.CanGoBack:
            self.web._webview.CoreWebView2.GoBack()

    def go_forward(self) -> None:
        if self.web.is_ready and self.web._webview.CoreWebView2.CanGoForward:
            self.web._webview.CoreWebView2.GoForward()

    def reload(self) -> None:
        self.web.reload()

    def toggle_play(self) -> None:
        self.web.evaluate_js(
            "const v=document.querySelector('video');if(v){v.paused?v.play():v.pause()}"
        )

    def seek_video(self, seconds: int) -> None:
        script = (
            "const v=document.querySelector('video');"
            f"if(v){{v.currentTime=Math.max(0,v.currentTime+({seconds}))}}"
        )
        self.web.evaluate_js(script)

    def previous_episode(self) -> None:
        self.web.evaluate_js(
            """
            const button = document.querySelector(
              '.bpx-player-ctrl-prev, [aria-label*="上一集"], [title*="上一集"]'
            );
            if (button) button.click();
            else document.dispatchEvent(new KeyboardEvent('keydown',{key:'[',bubbles:true}));
            """
        )

    def next_episode(self) -> None:
        self.web.evaluate_js(
            """
            const button = document.querySelector(
              '.bpx-player-ctrl-next, [aria-label*="下一集"], [title*="下一集"]'
            );
            if (button) button.click();
            else document.dispatchEvent(new KeyboardEvent('keydown',{key:']',bubbles:true}));
            """
        )

    def toggle_web_fullscreen(self) -> None:
        self.web.evaluate_js(
            """
            const button = document.querySelector(
              'div.bpx-player-ctrl-web, [aria-label*="网页全屏"], [title*="网页全屏"]'
            );
            if (button) button.click();
            """
        )

    def probe_video(self, callback) -> None:
        self.web.evaluate_js(
            """
            const v = document.querySelector('video');
            return {
              found: Boolean(v),
              currentTime: v ? v.currentTime : 0,
              duration: v && Number.isFinite(v.duration) ? v.duration : 0,
              paused: v ? v.paused : true,
              readyState: v ? v.readyState : 0,
              h264: document.createElement('video').canPlayType('video/mp4; codecs="avc1.42E01E"'),
              aac: document.createElement('audio').canPlayType('audio/mp4; codecs="mp4a.40.2"'),
              unsupported: document.body.innerText.includes('不支持HTML5播放器') ||
                document.body.innerText.includes('不支持 HTML5 播放器')
            };
            """,
            callback,
        )

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.subtitle_timer.stop()
        try:
            self.web.bridge.domContentLoaded.disconnect(self._install_page_bridge)
        except (RuntimeError, TypeError):
            pass
        core = self._webview_core
        if core is not None:
            for event, handler in (
                (core.WebResourceRequested, self._on_web_resource_requested),
                (core.NavigationCompleted, self._on_navigation_completed),
                (core.DocumentTitleChanged, self._on_document_title_changed),
                (core.NewWindowRequested, self._on_new_window_requested),
            ):
                try:
                    event -= handler
                except (AttributeError, RuntimeError):
                    pass
            self._webview_core = None
        self.web.close()
        self.web.deleteLater()


class DirectionPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parser = SubtitleParser()
        self.direction_overlay = DirectionOverlay()
        self.turn_overlay = TurnOverlay()
        self.subtitle_overlay = SubtitleOverlay()
        self.enhanced_overlay = EnhancedOverlay(self.direction_overlay)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        toggles = QHBoxLayout()
        self.enabled = QCheckBox("方向提醒")
        self.enabled.setChecked(True)
        self.subtitle_enabled = QCheckBox("字幕浮窗")
        self.subtitle_enabled.setChecked(True)
        self.turn_enabled = QCheckBox("左右转提醒")
        self.turn_enabled.setChecked(True)
        self.enhanced_enabled = QCheckBox("增强提醒")
        self.enhanced_enabled.setChecked(True)
        for control in (
            self.enabled,
            self.subtitle_enabled,
            self.turn_enabled,
            self.enhanced_enabled,
        ):
            toggles.addWidget(control)
        toggles.addStretch(1)
        layout.addLayout(toggles)
        self.input = QLineEdit()
        self.input.setPlaceholderText("字幕文本")
        self.input.returnPressed.connect(lambda: self.consume_subtitle(self.input.text()))
        analyze = QPushButton("识别")
        analyze.clicked.connect(lambda: self.consume_subtitle(self.input.text()))
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(analyze)
        layout.addLayout(row)
        self.result = QLabel("等待字幕")
        self.result.setObjectName("featureResult")
        layout.addWidget(self.result)
        self.history = QListWidget()
        layout.addWidget(self.history, 1)

    def consume_subtitle(self, text: str) -> None:
        value = text.strip()
        if not value:
            return
        if self.subtitle_enabled.isChecked():
            self.subtitle_overlay.show_subtitle(value)
        if not self.enabled.isChecked():
            return
        match = self.parser.parse(value)
        if not match:
            self.result.setText("未识别到方向")
            return
        self.result.setText(f"{match.arrow} {match.name}  来源：{value}")
        self.history.insertItem(0, self.result.text())
        if match.key.endswith("_turn"):
            if self.turn_enabled.isChecked():
                self.turn_overlay.show_turn(match)
        else:
            self.direction_overlay.show_direction(match)
            if self.enhanced_enabled.isChecked():
                self.enhanced_overlay.mirror(match)

    def consume_pose(self, angle: float, confidence: float, location) -> None:
        if not self.enabled.isChecked() or confidence <= 0:
            return
        directions = (
            ("north", "↑", "北"),
            ("north_east", "↗", "东北"),
            ("east", "→", "东"),
            ("south_east", "↘", "东南"),
            ("south", "↓", "南"),
            ("south_west", "↙", "西南"),
            ("west", "←", "西"),
            ("north_west", "↖", "西北"),
        )
        key, arrow, name = directions[round(angle / 45) % 8]
        match = DirectionMatch(key, arrow, name, round(angle), "AI 小地图")
        self.direction_overlay.show_direction(match)
        position = ""
        if location is not None:
            position = f"，位置 ({location.x:.3f}, {location.y:.3f})"
        self.result.setText(f"{arrow} {name}  {angle:.1f}° / {confidence:.3f}{position}")
        if self.enhanced_enabled.isChecked():
            self.enhanced_overlay.mirror(match)

    def close_overlays(self) -> None:
        for overlay in (
            self.direction_overlay,
            self.turn_overlay,
            self.subtitle_overlay,
            self.enhanced_overlay,
        ):
            overlay.close()


class DialogPage(QWidget):
    _evaluation_ready = Signal(object, object, object)
    _calibration_ready = Signal(object, object)

    def __init__(self, config_dir: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = AutoDialogEngine(config_dir=config_dir)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        controls = QHBoxLayout()
        self.live = QCheckBox("持续识别")
        self.live.toggled.connect(self._toggle_live)
        self.real_input = QCheckBox("允许真实按键")
        verified, failures = self.engine.verify_bundled_templates()
        self.real_input.setEnabled(verified)
        self.real_input.toggled.connect(self._confirm_real_input)
        self.game = QComboBox()
        for key, profile in self.engine.profiles.items():
            self.game.addItem(profile.display_name, key)
        screenshot = QPushButton("检测截图")
        screenshot.clicked.connect(self._choose_screenshot)
        calibrate = QPushButton("校准截图")
        calibrate.clicked.connect(self._choose_calibration)
        for widget in (self.live, self.real_input, self.game, screenshot, calibrate):
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)
        check_text = (
            "内置识别链路自检通过" if verified else f"内置识别链路自检失败：{len(failures)} 项"
        )
        self.status = QLabel(f"dry-run：识别命中只记录，不发送按键；{check_text}")
        layout.addWidget(self.status)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self._scan_foreground)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dialog-scan")
        self._shutdown = False
        self._scan_pending = False
        self._candidate_template = ""
        self._candidate_hwnd: int | None = None
        self._candidate_hits = 0
        self._evaluation_ready.connect(self._finish_evaluation)
        self._calibration_ready.connect(self._finish_calibration)

    def _confirm_real_input(self, enabled: bool) -> None:
        if not enabled:
            return
        answer = QMessageBox.question(
            self,
            "启用真实按键",
            "仅在前台游戏窗口识别命中时发送按键。确认启用？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.real_input.setChecked(False)

    def _toggle_live(self, enabled: bool) -> None:
        self.timer.start() if enabled else self.timer.stop()

    def _choose_screenshot(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择截图", "", "图片 (*.png *.jpg *.jpeg)")
        if not path:
            return
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        profile = self.engine.profiles[self.game.currentData()]
        self._evaluate(profile, frame)

    def _choose_calibration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择包含对话图标的游戏截图", "", "图片 (*.png *.jpg *.jpeg)"
        )
        if not path or self._scan_pending:
            return
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if frame is None:
            self.status.setText("校准截图读取失败")
            return
        profile = self.engine.profiles[self.game.currentData()]
        self._scan_pending = True
        self.status.setText(f"{profile.display_name}：正在扫描模板缩放比例")
        future = self._executor.submit(self.engine.learn_from_frame, profile, frame)
        future.add_done_callback(
            lambda completed, selected=profile: self._calibration_done(selected, completed)
        )

    def _calibration_done(self, profile, completed) -> None:
        if self._shutdown:
            return
        self._calibration_ready.emit(profile, completed.exception() or completed.result())

    def _finish_calibration(self, profile, result) -> None:
        self._scan_pending = False
        if isinstance(result, Exception):
            self.status.setText(f"{profile.display_name}：校准异常 {result}")
            return
        summary = "，".join(
            f"{template_id}={value['score']:.3f}@{value['scale']:.3f}"
            for template_id, value in result.items()
        )
        self.status.setText(f"{profile.display_name}：校准已保存；{summary}")

    def _scan_foreground(self) -> None:
        snapshot = foreground_window_snapshot()
        if not snapshot:
            return
        profile = match_game(snapshot, self.engine.profiles)
        if not profile:
            self.status.setText("未检测到受支持的游戏窗口")
            return
        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(snapshot.hwnd)
        frame = _qimage_to_array(pixmap.toImage())
        self._evaluate(profile, frame, hwnd=snapshot.hwnd)

    def _evaluate(self, profile, frame, *, hwnd: int | None = None) -> None:
        if frame is None:
            self.status.setText("截图失败")
            return
        if self._scan_pending:
            return
        self._scan_pending = True
        future = self._executor.submit(self.engine.evaluate_frame, profile, frame)
        future.add_done_callback(
            lambda completed, selected=profile, target=hwnd: self._evaluation_done(
                selected, target, completed
            )
        )

    def _evaluation_done(self, profile, hwnd, completed) -> None:
        if self._shutdown:
            return
        self._evaluation_ready.emit(profile, hwnd, completed.exception() or completed.result())

    def _finish_evaluation(self, profile, hwnd, decision) -> None:
        self._scan_pending = False
        if isinstance(decision, Exception):
            self.status.setText(f"{profile.display_name}：识别异常 {decision}")
            return
        if not decision:
            self._candidate_template = ""
            self._candidate_hwnd = None
            self._candidate_hits = 0
            self.status.setText(f"{profile.display_name}：未命中")
            return
        if self.live.isChecked():
            if decision.template_id == self._candidate_template and hwnd == self._candidate_hwnd:
                self._candidate_hits += 1
            else:
                self._candidate_template = decision.template_id
                self._candidate_hwnd = hwnd
                self._candidate_hits = 1
            if self._candidate_hits < 2:
                self.status.setText(
                    f"{profile.display_name}：候选 {decision.template_id}，等待连续帧确认"
                )
                return
        allow_real_input = False
        if self.live.isChecked() and self.real_input.isChecked() and hwnd is not None:
            current = foreground_window_snapshot()
            allow_real_input = bool(
                current
                and current.hwnd == hwnd
                and match_game(current, self.engine.profiles) == profile
            )
        result = self.engine.trigger(decision, allow_real_input=allow_real_input)
        self.status.setText(f"{profile.display_name}：{result.message}，分数 {result.score:.3f}")
        self.log.append(self.status.text())

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)


class VisionPage(QWidget):
    pose_changed = Signal(float, float, object)
    region_changed = Signal(object)
    _analysis_ready = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.large_image = None
        self.small_image = None
        self.detector = None
        self.locator = None
        self.capture_region: QRect | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-nav")
        self._shutdown = False
        self._analysis_pending = False
        self._analysis_ready.connect(self._finish_analysis)
        self.timer = QTimer(self)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self._capture_live)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        row = QHBoxLayout()
        large = QPushButton("选择大地图")
        large.clicked.connect(lambda: self._load_image("large"))
        small = QPushButton("选择小地图")
        small.clicked.connect(lambda: self._load_image("small"))
        capture = QPushButton("框选小地图")
        capture.clicked.connect(self._select_screen_region)
        run = QPushButton("识别方向和位置")
        run.clicked.connect(self._run)
        self.live = QCheckBox("持续识别")
        self.live.toggled.connect(
            lambda enabled: self.timer.start() if enabled else self.timer.stop()
        )
        self.edge = QCheckBox("边缘增强")
        for widget in (large, small, capture, run, self.live, self.edge):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = QLabel(
            "CPU AI 依赖可用" if ai_dependencies_available() else "未安装可选 AI 依赖"
        )
        layout.addWidget(self.status)
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result, 1)

    def _load_image(self, target: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg)")
        if not path:
            return
        import cv2
        import numpy as np

        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        setattr(self, f"{target}_image", image)
        self.result.append(f"已载入{target}：{Path(path).name}")

    def _run(self) -> None:
        if not ai_dependencies_available():
            self.result.append("缺少 ai 可选依赖")
            return
        if self.small_image is None:
            self.result.append("请先选择小地图")
            return
        if self._analysis_pending:
            return
        self._analysis_pending = True
        large = None if self.large_image is None else self.large_image.copy()
        small = self.small_image.copy()
        future = self._executor.submit(self._analyze_images, large, small, self.edge.isChecked())
        future.add_done_callback(self._analysis_done)

    def _analysis_done(self, completed) -> None:
        if self._shutdown:
            return
        self._analysis_ready.emit(completed.exception() or completed.result())

    def _analyze_images(self, large, small, edge_enhance: bool):
        if self.detector is None:
            self.detector = ConeAngleDetector()
        angle = self.detector.predict(small)
        location = None
        if large is not None:
            if self.locator is None:
                self.locator = FeatureLocator(edge_enhance=edge_enhance)
            self.locator.edge_enhance = edge_enhance
            location = self.locator.locate(large, small)
        return angle, location

    def _finish_analysis(self, result) -> None:
        self._analysis_pending = False
        if isinstance(result, Exception):
            self.result.append(f"识别异常：{result}")
            return
        angle, location = result
        self.result.append(f"方向 {angle.angle:.1f}°，置信度 {angle.confidence:.3f}")
        if self.large_image is not None:
            if location:
                self.result.append(
                    f"位置 ({location.x:.3f}, {location.y:.3f})，内点率 {location.confidence:.3f}"
                )
            else:
                self.result.append("未能在大地图中定位小地图")
        self.pose_changed.emit(angle.angle, angle.confidence, location)

    def _select_screen_region(self) -> None:
        selector = ScreenRegionSelector()
        selector.region_selected.connect(self._capture_region)
        selector.showFullScreen()
        self._selector = selector

    def _capture_region(self, region: QRect) -> None:
        changed = self.capture_region != region
        self.capture_region = QRect(region)
        screen = QApplication.screenAt(region.center()) or QApplication.primaryScreen()
        pixmap = screen.grabWindow(0, region.x(), region.y(), region.width(), region.height())
        self.small_image = _qimage_to_array(pixmap.toImage())
        self.result.append(f"已截取小地图区域 {region.width()}×{region.height()}")
        if changed:
            self.region_changed.emit(QRect(region))

    def _capture_live(self) -> None:
        if self.capture_region is None:
            self.live.setChecked(False)
            self.result.append("请先框选小地图区域")
            return
        self._capture_region(self.capture_region)
        self._run()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)


class SettingsPage(QWidget):
    settings_applied = Signal()

    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        preset_row = QHBoxLayout()
        self.presets = QComboBox()
        self._reload_presets()
        activate = QPushButton("切换")
        activate.clicked.connect(self._activate)
        create = QPushButton("新建")
        create.clicked.connect(self._create)
        delete = QPushButton("删除")
        delete.clicked.connect(self._delete)
        for widget in (self.presets, activate, create, delete):
            preset_row.addWidget(widget)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        form = QFormLayout()
        self.always_on_top = QCheckBox()
        self.theme = QComboBox()
        self.theme.addItem("浅色", "light")
        self.theme.addItem("深色", "dark")
        self.transparency = QSlider()
        self.transparency.setOrientation(Qt.Orientation.Horizontal)
        self.transparency.setRange(35, 100)
        self.video_skip = QSpinBox()
        self.video_skip.setRange(1, 60)
        form.addRow("窗口置顶", self.always_on_top)
        form.addRow("主题", self.theme)
        form.addRow("窗口不透明度", self.transparency)
        form.addRow("快进/快退秒数", self.video_skip)
        self.hole_enabled = QCheckBox()
        self.hole_radius = QSpinBox()
        self.hole_radius.setRange(40, 500)
        self.smart_dodge = QCheckBox()
        self.anti_occlude = QCheckBox()
        form.addRow("沉浸挖孔", self.hole_enabled)
        form.addRow("挖孔半径", self.hole_radius)
        form.addRow("智能避让", self.smart_dodge)
        form.addRow("智能防遮挡", self.anti_occlude)
        self.direction_enabled = QCheckBox()
        self.subtitle_enabled = QCheckBox()
        self.turn_enabled = QCheckBox()
        self.enhanced_enabled = QCheckBox()
        form.addRow("方向提醒总开关", self.direction_enabled)
        form.addRow("网页字幕浮窗", self.subtitle_enabled)
        form.addRow("左右转提醒", self.turn_enabled)
        form.addRow("增强提醒", self.enhanced_enabled)
        self.dialog_enabled = QCheckBox()
        self.dialog_real_input = QCheckBox()
        form.addRow("启动自动对话识别", self.dialog_enabled)
        form.addRow("允许自动对话按键", self.dialog_real_input)
        self.vision_live = QCheckBox()
        self.vision_edge = QCheckBox()
        form.addRow("AI 持续识别", self.vision_live)
        form.addRow("AI 定位边缘增强", self.vision_edge)
        self.hotkey_edits: dict[str, QLineEdit] = {}
        labels = {
            "toggle_play": "播放/暂停",
            "fast_backward": "快退",
            "fast_forward": "快进",
            "prev_episode": "上一集",
            "next_episode": "下一集",
            "toggle_visible": "显示/隐藏",
            "toggle_mouse_passthrough": "切换沉浸",
            "toggle_auto_dialog": "自动对话",
            "toggle_always_on_top": "切换置顶",
        }
        for action, default in DEFAULT_HOTKEYS.items():
            edit = QLineEdit(default)
            edit.setMaximumWidth(180)
            self.hotkey_edits[action] = edit
            form.addRow(labels[action], edit)
        layout.addLayout(form)
        save = QPushButton("保存设置")
        save.clicked.connect(self._save)
        layout.addWidget(save)
        layout.addStretch(1)
        self._load_values()

    def _reload_presets(self) -> None:
        self.presets.clear()
        self.presets.addItems(self.store.data["presets"].keys())
        self.presets.setCurrentText(self.store.active_preset_name)

    def _load_values(self) -> None:
        preset = self.store.active_preset
        self.always_on_top.setChecked(bool(preset["window"]["always_on_top"]))
        self.theme.setCurrentIndex(max(0, self.theme.findData(preset["window"]["theme"])))
        self.transparency.setValue(int(preset["window"]["transparency"]))
        self.video_skip.setValue(int(preset["video_skip_seconds"]))
        immersive = preset["immersive"]
        self.hole_enabled.setChecked(bool(immersive["hole_enabled"]))
        self.hole_radius.setValue(int(immersive["hole_radius"]))
        self.smart_dodge.setChecked(bool(immersive["smart_dodge"]))
        self.anti_occlude.setChecked(bool(immersive["anti_occlude"]))
        direction = preset["direction"]
        self.direction_enabled.setChecked(bool(direction["enabled"]))
        self.subtitle_enabled.setChecked(bool(direction["subtitle_sprite"]))
        self.turn_enabled.setChecked(bool(direction["turn_enabled"]))
        self.enhanced_enabled.setChecked(bool(direction["enhanced_enabled"]))
        dialog = preset["dialog"]
        self.dialog_enabled.setChecked(bool(dialog["enabled"]))
        self.dialog_real_input.setChecked(bool(dialog["allow_real_input"]))
        vision = preset["vision"]
        self.vision_live.setChecked(bool(vision.get("live", False)))
        self.vision_edge.setChecked(bool(vision["edge_enhance"]))
        for action, edit in self.hotkey_edits.items():
            edit.setText(str(preset["hotkeys"].get(action, "")))

    def _save(self) -> None:
        preset = self.store.active_preset
        preset["window"]["always_on_top"] = self.always_on_top.isChecked()
        preset["window"]["theme"] = self.theme.currentData()
        preset["window"]["transparency"] = self.transparency.value()
        preset["video_skip_seconds"] = self.video_skip.value()
        preset["immersive"] = {
            "hole_enabled": self.hole_enabled.isChecked(),
            "hole_radius": self.hole_radius.value(),
            "smart_dodge": self.smart_dodge.isChecked(),
            "anti_occlude": self.anti_occlude.isChecked(),
        }
        preset["direction"] = {
            "enabled": self.direction_enabled.isChecked(),
            "subtitle_sprite": self.subtitle_enabled.isChecked(),
            "turn_enabled": self.turn_enabled.isChecked(),
            "enhanced_enabled": self.enhanced_enabled.isChecked(),
        }
        preset["dialog"] = {
            "enabled": self.dialog_enabled.isChecked(),
            "allow_real_input": self.dialog_real_input.isChecked(),
        }
        preset["vision"] = {
            "live": self.vision_live.isChecked(),
            "edge_enhance": self.vision_edge.isChecked(),
            "region": preset["vision"].get("region"),
        }
        preset["hotkeys"] = {
            action: edit.text().strip() for action, edit in self.hotkey_edits.items()
        }
        self.store.save()
        self.settings_applied.emit()

    def _activate(self) -> None:
        self.store.activate_preset(self.presets.currentText())
        self._load_values()
        self.settings_applied.emit()

    def _create(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建预设", "名称")
        if accepted:
            try:
                self.store.create_preset(name)
            except ValueError as error:
                QMessageBox.warning(self, "无法新建", str(error))
            self._reload_presets()

    def _delete(self) -> None:
        try:
            self.store.delete_preset(self.presets.currentText())
        except ValueError as error:
            QMessageBox.warning(self, "无法删除", str(error))
        self._reload_presets()
        self._load_values()


def _qimage_to_array(image: QImage):
    import numpy as np

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    view = converted.bits()
    array = np.frombuffer(view, dtype=np.uint8).reshape(
        converted.height(), converted.bytesPerLine()
    )
    return (
        array[:, : converted.width() * 4].reshape(converted.height(), converted.width(), 4).copy()
    )


class ScreenRegionSelector(QWidget):
    region_selected = Signal(QRect)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin = QPoint()
        self._region = QRect()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._origin = event.position().toPoint()
        self._region = QRect(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._region = QRect(self._origin, event.position().toPoint()).normalized()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._region = QRect(self._origin, event.position().toPoint()).normalized()
        if self._region.width() >= 16 and self._region.height() >= 16:
            top_left = self.mapToGlobal(self._region.topLeft())
            self.region_selected.emit(QRect(top_left, self._region.size()))
        self.close()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setPen(QPen(Qt.GlobalColor.green, 2))
        painter.drawRect(self._region)
