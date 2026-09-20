from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from eryou_assistant.core.guides import GuideStore
from eryou_assistant.ui.pages import BrowserPage

TARGET = "https://www.bilibili.com/video/BV1hjgG6jEa6/"


def main() -> int:
    app = QApplication(sys.argv)
    artifact_dir = Path(__file__).parents[1] / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    page = BrowserPage(GuideStore(artifact_dir / "acceptance-guides.json"))
    page.setWindowTitle("二游辅助 WebView2 播放验收")
    page.resize(1200, 800)
    page.show()
    page.address.setText(TARGET)
    page.navigate()
    samples: list[dict] = []

    def receive(response: dict) -> None:
        if not response.get("success"):
            return
        state = response.get("result") or {}
        if not state.get("found") and not state.get("unsupported"):
            return
        state["sample"] = len(samples) + 1
        samples.append(state)
        if state.get("found") and len(samples) == 1:
            page.web.evaluate_js(
                "window.scrollTo(0,0);const v=document.querySelector('video');"
                "v.muted=true;return v.play()"
            )
            return
        if len(samples) < 2:
            return
        screenshot = artifact_dir / "bilibili-webview2-playback.png"
        origin = page.mapToGlobal(QPoint(0, 0))
        QApplication.primaryScreen().grabWindow(
            0, origin.x(), origin.y(), page.width(), page.height()
        ).save(str(screenshot))
        first, last = samples[-2:]
        passed = (
            not last.get("unsupported")
            and last.get("h264") in {"maybe", "probably"}
            and last.get("aac") in {"maybe", "probably"}
            and last.get("readyState", 0) >= 2
            and last.get("currentTime", 0) > first.get("currentTime", 0) + 0.5
        )
        result = {
            "passed": passed,
            "url": TARGET,
            "samples": samples,
            "screenshot": str(screenshot),
        }
        (artifact_dir / "bilibili-webview2-playback.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
        app.exit(0 if passed else 1)

    def poll() -> None:
        page.probe_video(receive)

    timer = QTimer()
    timer.setInterval(3000)
    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(60000, lambda: app.exit(2))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
