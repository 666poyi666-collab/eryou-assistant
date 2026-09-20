"""系统托盘图标：无边框模式下最可靠的退出入口 + 常用开关。

为什么需要：无边框模式下右上角那个「还原」浮窗是独立的 Qt.Tool 窗口，
只要游戏以全屏/置顶方式盖在前面就看不见、点不到。托盘图标由 shell 绘制，
永远在任务栏通知区域，右键就能操作，不受游戏遮挡影响。

菜单：
  * 无边框模式（勾选项）—— 只留视频画面 / 恢复标题栏
  * 显示 / 隐藏窗口
  * 重新加载页面
  * 退出二游辅助

双击托盘图标 = 显示并激活主窗口。
"""

from __future__ import annotations

from typing import Any


def install_tray(
    main_window_module: Any,
    qt_core: Any,
    qt_gui: Any,
    qt_widgets: Any,
    logger: Any,
) -> None:
    window_type = getattr(main_window_module, "MainWindow", None)
    if window_type is None or getattr(window_type, "_mabao_tray_installed", False):
        return

    original_init = window_type.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            _install(self, qt_core, qt_gui, qt_widgets, logger)
        except Exception:  # noqa: BLE001
            logger.exception("托盘图标安装失败（其余功能不受影响）")

    patched_init._mabao_tray_installed = True
    window_type.__init__ = patched_init
    logger.info("托盘图标补丁已装载")


def _install(window: Any, qt_core: Any, qt_gui: Any, qt_widgets: Any, logger: Any) -> None:
    if getattr(window, "_mabao_tray_icon", None) is not None:
        return
    tray_type = getattr(qt_widgets, "QSystemTrayIcon", None)
    if tray_type is None:
        logger.warning("当前 Qt 没有 QSystemTrayIcon，跳过托盘")
        return
    try:
        available = bool(tray_type.isSystemTrayAvailable())
    except Exception:  # noqa: BLE001
        available = True
    if not available:
        logger.warning("系统托盘不可用，跳过托盘图标")
        return

    app = qt_widgets.QApplication.instance()
    icon = None
    try:
        icon = app.windowIcon() if app is not None else None
    except Exception:  # noqa: BLE001
        icon = None
    if icon is None or (hasattr(icon, "isNull") and icon.isNull()):
        icon = qt_gui.QIcon()

    tray = tray_type(icon, window)
    tray.setToolTip("二游辅助")
    menu = qt_widgets.QMenu(window)

    def borderless_state() -> dict:
        return getattr(window, "_mabao_borderless_state", None) or {}

    def is_borderless() -> bool:
        return bool(borderless_state().get("on"))

    def toggle_borderless() -> None:
        toggle = getattr(window, "_mabao_borderless_toggle", None)
        if callable(toggle):
            toggle()

    act_borderless = menu.addAction("无边框模式（只留画面）")
    act_borderless.setCheckable(True)
    act_borderless.setChecked(is_borderless())
    act_borderless.triggered.connect(lambda _checked=False: toggle_borderless())

    def toggle_visible() -> None:
        try:
            method = getattr(window, "toggle_visible", None)
            if callable(method):
                method()
                return
            if window.isVisible():
                window.hide()
            else:
                window.show()
                window.raise_()
                window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("托盘：切换窗口显示失败")

    act_visible = menu.addAction("显示 / 隐藏窗口")
    act_visible.triggered.connect(lambda _checked=False: toggle_visible())

    def reload_page() -> None:
        try:
            container = getattr(window, "webview_container", None)
            if container is None:
                return
            if hasattr(container, "load_url"):
                url = ""
                bar = getattr(window, "title_bar", None)
                if bar is not None and hasattr(bar, "url_input"):
                    url = bar.url_input.text().strip()
                container.load_url(url or "https://www.bilibili.com")
        except Exception:  # noqa: BLE001
            logger.exception("托盘：重新加载失败")

    act_reload = menu.addAction("重新加载页面")
    act_reload.triggered.connect(lambda _checked=False: reload_page())

    menu.addSeparator()

    def quit_app() -> None:
        try:
            window.close()
        except Exception:  # noqa: BLE001
            logger.exception("托盘：退出失败")
            qt_widgets.QApplication.quit()

    act_quit = menu.addAction("退出二游辅助")
    act_quit.triggered.connect(lambda _checked=False: quit_app())

    tray.setContextMenu(menu)

    def on_activated(reason: Any) -> None:
        try:
            if reason in (tray_type.ActivationReason.DoubleClick, tray_type.ActivationReason.Trigger):
                if not window.isVisible():
                    window.show()
                window.raise_()
                window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.debug("托盘点击处理失败", exc_info=True)

    try:
        tray.activated.connect(on_activated)
    except Exception:  # noqa: BLE001
        logger.debug("托盘 activated 信号连接失败", exc_info=True)

    # 同步勾选状态：无边框按钮 / F10 切换后，托盘菜单也要跟着变
    def sync_menu() -> None:
        try:
            act_borderless.setChecked(is_borderless())
        except Exception:  # noqa: BLE001
            pass

    timer = qt_core.QTimer(window)
    timer.setInterval(800)
    timer.timeout.connect(sync_menu)
    timer.start()

    tray.show()
    window._mabao_tray_icon = tray
    window._mabao_tray_menu = menu
    window._mabao_tray_timer = timer
    logger.info("托盘图标已就绪（右键菜单：无边框模式 / 显示隐藏 / 重新加载 / 退出）")
