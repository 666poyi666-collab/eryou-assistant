from concurrent.futures import Future

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QFrame, QLabel

from eryou_assistant import __version__
from eryou_assistant.core.features import FEATURES
from eryou_assistant.ui.main_window import MainWindow


def test_main_window_has_one_page_per_feature(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ERYOU_ASSISTANT_CONFIG_DIR", str(tmp_path))
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "二游辅助"
    assert window.pages.count() == len(FEATURES)
    sidebar = window.findChild(QFrame, "sidebar")
    assert sidebar is not None
    assert __version__ in sidebar.findChildren(QLabel)[-1].text()
    _destroy_window(window, qtbot)


def test_pages_are_real_tools_and_browser_starts_local(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ERYOU_ASSISTANT_CONFIG_DIR", str(tmp_path))
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.browser_page._current_url.startswith(("http://", "https://"))
    assert window.direction_page.parser is not None
    assert window.dialog_page.engine.profiles.keys() == {"genshin", "starrail"}
    assert window.settings_page.hotkey_edits["toggle_visible"].text() == "F9"
    _destroy_window(window, qtbot)


def test_runtime_feature_toggles_persist(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ERYOU_ASSISTANT_CONFIG_DIR", str(tmp_path))
    window = MainWindow()
    qtbot.addWidget(window)

    window.direction_page.enhanced_enabled.setChecked(False)
    window.dialog_page.live.setChecked(True)
    assert window.settings_store.active_preset["direction"]["enhanced_enabled"] is False
    assert window.settings_store.active_preset["dialog"]["enabled"] is True
    assert window.settings_page.enhanced_enabled.isChecked() is False

    _destroy_window(window, qtbot)


def test_browser_subtitle_drives_direction_workflow(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ERYOU_ASSISTANT_CONFIG_DIR", str(tmp_path))
    window = MainWindow()
    qtbot.addWidget(window)

    window.browser_page._on_subtitle_message("往东北方向走")
    assert "东北" in window.direction_page.result.text()
    assert window.direction_page.direction_overlay.isVisible()
    assert window.direction_page.enhanced_overlay.isVisible()

    _destroy_window(window, qtbot)


def test_background_callbacks_are_ignored_after_shutdown(qtbot, tmp_path) -> None:
    from eryou_assistant.ui.pages import DialogPage, VisionPage

    dialog = DialogPage(tmp_path)
    vision = VisionPage()
    qtbot.addWidget(dialog)
    qtbot.addWidget(vision)
    dialog.shutdown()
    vision.shutdown()

    completed = Future()
    completed.set_result(None)
    dialog._evaluation_done(dialog.engine.profiles["genshin"], None, completed)
    dialog._calibration_done(dialog.engine.profiles["genshin"], completed)
    vision._analysis_done(completed)


def _destroy_window(window: MainWindow, qtbot) -> None:
    window.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(20)
