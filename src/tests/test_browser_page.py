from PySide6.QtCore import QCoreApplication, QEvent, QUrl

from eryou_assistant.core.guides import GuideStore
from eryou_assistant.ui.pages import BrowserPage, RequestBlocker


def test_request_blocker_filters_common_ad_hosts() -> None:
    assert RequestBlocker.should_block("https://pagead2.googlesyndication.com/ad.js")
    assert RequestBlocker.should_block("https://example.com/adserver/banner")
    assert not RequestBlocker.should_block("https://www.bilibili.com/video/BV1")


def test_browser_local_navigation_history_and_bookmark(qtbot, tmp_path) -> None:
    local_page = tmp_path / "guide.html"
    local_page.write_text(
        "<html><title>本地攻略</title><body>guide</body></html>", encoding="utf-8"
    )
    store = GuideStore(tmp_path / "guides.json")
    page = BrowserPage(store)
    qtbot.addWidget(page)
    page.show()
    page.address.setText(QUrl.fromLocalFile(str(local_page)).toString())
    page.navigate()
    qtbot.waitUntil(lambda: page.web.is_ready, timeout=10000)
    qtbot.waitUntil(lambda: page._current_url.startswith("file:"), timeout=10000)
    qtbot.waitUntil(lambda: page._title == "本地攻略", timeout=10000)
    page.toggle_bookmark()

    assert store.history[-1].url.startswith("file:")
    assert store.bookmarks[-1].title == "本地攻略"
    page.shutdown()
    page.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_browser_backend_is_edge_webview2() -> None:
    assert BrowserPage.__module__ == "eryou_assistant.ui.pages"
    assert "QtWebView2Widget" in BrowserPage.__init__.__globals__


def test_subtitle_bridge_emits_new_text(qtbot, tmp_path) -> None:
    page = BrowserPage(GuideStore(tmp_path / "guides.json"))
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.subtitle_changed, timeout=1000) as signal:
        page._on_subtitle_message("向东北方向走")
    assert signal.args == ["向东北方向走"]
    page.shutdown()


def test_webview_dom_subtitle_reaches_python(qtbot, tmp_path) -> None:
    page = BrowserPage(GuideStore(tmp_path / "guides.json"))
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.web.is_ready, timeout=10000)
    with qtbot.waitSignal(page.subtitle_changed, timeout=10000) as signal:
        page.web.load_html(
            "<html><body><span class='bpx-player-subtitle-panel-text'>往东北方向走</span>"
            "</body></html>"
        )
    assert signal.args == ["往东北方向走"]
    page.shutdown()


def test_webview_bridge_hides_same_origin_ad_cards(qtbot, tmp_path) -> None:
    page = BrowserPage(GuideStore(tmp_path / "guides.json"))
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.web.is_ready, timeout=10000)
    page.web.load_html("<html><body><aside class='ad-report'>广告</aside></body></html>")
    qtbot.wait(500)
    result = []
    page.web.evaluate_js(
        "return getComputedStyle(document.querySelector('.ad-report')).display",
        lambda response: result.append(response.get("result", "")),
    )
    qtbot.waitUntil(lambda: bool(result), timeout=10000)
    assert result[-1] == "none"
    page.shutdown()
