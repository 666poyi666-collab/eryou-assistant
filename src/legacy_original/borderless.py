"""一键无边框：收起标题栏和其余界面元素，只留视频画面，窗口仍可拖动/缩放。

实现方式与 launcher.py 里其它 install_* 一致：运行时给 app.main_window.MainWindow
打补丁，不改原版字节码。所有异常都吞掉并写日志，绝不能影响主程序启动。

交互：
  * 标题栏右侧出现一个「⛶」按钮，点一下进入无边框（只留浏览器画面）
  * 无边框时右上角浮出一个「还原」小窗（Qt.Tool + 置顶，能盖在 WebView2 原生窗口上）
  * 也可以按 F10 来回切换
"""

from __future__ import annotations

import importlib
from typing import Any


def install_borderless(main_window_module: Any, qt_core: Any, qt_widgets: Any, logger: Any) -> None:
    window_type = getattr(main_window_module, "MainWindow", None)
    if window_type is None or getattr(window_type, "_mabao_borderless_installed", False):
        return

    original_init = window_type.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            _install(self, qt_core, qt_widgets, logger)
        except Exception:  # noqa: BLE001
            logger.exception("无边框按钮安装失败（其余功能不受影响）")

    patched_init._mabao_borderless_installed = True
    window_type.__init__ = patched_init
    logger.info("无边框模式补丁已装载")


def _install(window: Any, qt_core: Any, qt_widgets: Any, logger: Any) -> None:
    bar = getattr(window, "title_bar", None)
    web = getattr(window, "webview_container", None)
    if bar is None or web is None:
        logger.warning("找不到 title_bar/webview_container，跳过无边框功能")
        return
    if getattr(window, "_mabao_borderless_state", None) is not None:
        return

    state: dict[str, Any] = {"on": False, "hidden": [], "restore": None, "button": None}
    window._mabao_borderless_state = state

    # ---------- 工具函数 ----------
    def chrome_widgets() -> list[Any]:
        """主窗口布局里除浏览器画面之外的所有控件。"""
        result: list[Any] = []
        try:
            central = window.centralWidget()
            layout = central.layout() if central is not None else None
            if layout is None:
                return result
            for index in range(layout.count()):
                item = layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None and widget is not web:
                    result.append(widget)
        except Exception:  # noqa: BLE001
            logger.debug("枚举界面控件失败", exc_info=True)
        return result

    def ensure_restore_window() -> Any:
        if state["restore"] is not None:
            return state["restore"]
        flags = qt_core.Qt.Tool | qt_core.Qt.FramelessWindowHint | qt_core.Qt.WindowStaysOnTopHint
        holder = qt_widgets.QWidget(None, flags)
        holder.setAttribute(qt_core.Qt.WA_TranslucentBackground, True)
        holder.setWindowTitle("二游辅助 · 退出无边框")
        layout = qt_widgets.QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        button = None
        try:
            game_button = importlib.import_module("app.game_button")
            button = game_button.GameButton("还原", holder)
        except Exception:  # noqa: BLE001
            logger.debug("GameButton 不可用，用普通按钮代替", exc_info=True)
        if button is None:
            button = qt_widgets.QToolButton(holder)
            button.setText("还原")
            button.setStyleSheet(
                "QToolButton{background:rgba(24,26,32,220);color:#e8eaed;"
                "border:1px solid rgba(255,255,255,60);border-radius:6px;padding:4px 10px;}"
                "QToolButton:hover{background:rgba(48,52,62,235);}"
            )
        button.setToolTip("退出无边框（也可以按 F10）")
        button.clicked.connect(lambda: set_borderless(False))
        layout.addWidget(button)
        holder.resize(max(76, button.sizeHint().width() + 8), max(30, button.sizeHint().height() + 6))
        state["restore"] = holder
        return holder

    def reposition_restore() -> None:
        holder = state["restore"]
        if holder is None or not holder.isVisible():
            return
        try:
            geometry = window.frameGeometry()
            holder.move(geometry.right() - holder.width() - 10, geometry.top() + 10)
        except Exception:  # noqa: BLE001
            logger.debug("还原按钮定位失败", exc_info=True)

    def set_borderless(enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == state["on"]:
            return
        try:
            if enabled:
                if hasattr(bar, "hide_titlebar"):
                    bar.hide_titlebar()
                else:
                    bar.hide()
                hidden = []
                for widget in chrome_widgets():
                    if widget.isVisible():
                        hidden.append(widget)
                        widget.hide()
                state["hidden"] = hidden
                holder = ensure_restore_window()
                reposition_restore()
                holder.show()
                holder.raise_()
                state["on"] = True
                logger.info("已进入无边框模式（只留画面，仍可拖动缩放）")
            else:
                if hasattr(bar, "show_titlebar"):
                    bar.show_titlebar()
                else:
                    bar.show()
                for widget in state.get("hidden", []):
                    try:
                        widget.show()
                    except Exception:  # noqa: BLE001
                        logger.debug("恢复控件失败", exc_info=True)
                state["hidden"] = []
                if state["restore"] is not None:
                    state["restore"].hide()
                state["on"] = False
                logger.info("已退出无边框模式")
            button = state.get("button")
            if button is not None:
                button.setToolTip("退出无边框（F10）" if state["on"] else "一键无边框：只留视频画面（F10）")
        except Exception:  # noqa: BLE001
            logger.exception("切换无边框失败")

    def toggle() -> None:
        set_borderless(not state["on"])

    # ---------- 标题栏按钮 ----------
    button = None
    maker = getattr(bar, "_make_button", None)
    if maker is not None:
        for arguments in (("⛶", "borderless_btn"), ("⛶",)):
            try:
                button = maker(*arguments)
                break
            except TypeError:
                continue
            except Exception:  # noqa: BLE001
                logger.debug("_make_button 调用失败", exc_info=True)
                break
    if button is None:
        button = qt_widgets.QToolButton(bar)
        button.setText("⛶")
        button.setFixedSize(26, 26)
        button.setCursor(qt_core.Qt.PointingHandCursor)
        button.setStyleSheet(
            "QToolButton{background:transparent;border:none;color:#e8eaed;font-size:14px;}"
            "QToolButton:hover{color:#8ab4f8;}"
        )
    try:
        button.setToolTip("一键无边框：只留视频画面（F10）")
        button.clicked.connect(toggle)
        bar_layout = bar.layout()
        minimize = getattr(bar, "btn_minimize", None)
        if bar_layout is not None:
            index = bar_layout.indexOf(minimize) if minimize is not None else -1
            if index >= 0:
                bar_layout.insertWidget(index, button)
            else:
                bar_layout.addWidget(button)
        state["button"] = button
    except Exception:  # noqa: BLE001
        logger.exception("把无边框按钮插进标题栏失败")

    # ---------- F10 热键 ----------
    try:
        manager = getattr(window, "hotkey_manager", None)
        if manager is not None and hasattr(manager, "register"):
            manager.register("F10", "toggle_borderless", window._safe_ui(toggle))
    except Exception:  # noqa: BLE001
        logger.debug("注册 F10 无边框热键失败", exc_info=True)

    # ---------- 跟随主窗口移动 ----------
    try:
        timer = qt_core.QTimer(window)
        timer.setInterval(300)
        timer.timeout.connect(reposition_restore)
        timer.start()
        window._mabao_borderless_timer = timer
    except Exception:  # noqa: BLE001
        logger.debug("还原按钮跟随定时器启动失败", exc_info=True)

    logger.info("无边框按钮已就绪（标题栏 ⛶ / F10）")
