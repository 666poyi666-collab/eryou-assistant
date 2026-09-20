"""播放全屏守卫：网页全屏被"弹窗/脚本"踢出来时，尽量自动回到全屏，并把现场记进日志。

现象（用户反馈）：看着看着就自动退出网页全屏，登录/广告弹窗已经被 CSS 隐藏了，
但"还是会发生"。

做法分两层：
  1. document-start 注入守卫脚本（launcher 里的 FULLSCREEN_GUARD_SCRIPT）：
     * 记录 fullscreenchange（进入/退出/自动回全屏成功失败）；
     * 把被隐藏的弹窗从焦点链里摘出去（focusin 拦截 + blur），避免弹窗抢焦点；
     * 不是用户按 Esc 导致的退出，就在 500ms 后尝试重新 requestFullscreen
       （Chromium 需要用户手势，失败会把原因记下来，便于继续定位）。
  2. Python 侧每 4 秒读一次页面里的守卫状态，状态有变化就写进程序日志，
     方便对着日志看"到底是播放器重建、还是弹窗抢焦点"。

注意：没有用户手势时 requestFullscreen 可能被浏览器拒绝 —— 这是 Chromium 的安全策略，
所以这里不承诺 100% 自动回全屏，而是把原因记录清楚；真要彻底修，需要先确认触发者。
"""

from __future__ import annotations

import json
from typing import Any

POLL_INTERVAL_MS = 4000


def install_playback_guard(main_window_module: Any, qt_core: Any, logger: Any) -> None:
    window_type = getattr(main_window_module, "MainWindow", None)
    if window_type is None or getattr(window_type, "_mabao_playback_guard_installed", False):
        return

    original_init = window_type.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            _install(self, qt_core, logger)
        except Exception:  # noqa: BLE001
            logger.exception("播放全屏守卫安装失败（其余功能不受影响）")

    patched_init._mabao_playback_guard_installed = True
    window_type.__init__ = patched_init
    logger.info("播放全屏守卫补丁已装载")


def _install(window: Any, qt_core: Any, logger: Any) -> None:
    container = getattr(window, "webview_container", None)
    if container is None:
        logger.warning("找不到 webview_container，跳过播放守卫")
        return
    last = {"signature": None}

    def poll() -> None:
        try:
            # WebViewContainer.execute_js 不一定支持回调，优先直接用底层 evaluate_js
            runner = getattr(container, "evaluate_js", None)
            if callable(runner):
                runner(
                    "(typeof window.__mabaoFullscreenStatus === 'function')"
                    " ? window.__mabaoFullscreenStatus() : ''",
                    lambda payload: _handle(payload, last, logger),
                )
                return
            container.execute_js(
                "(typeof window.__mabaoFullscreenStatus === 'function')"
                " ? window.__mabaoFullscreenStatus() : ''"
            )
        except Exception:  # noqa: BLE001
            logger.debug("读取全屏守卫状态失败", exc_info=True)

    timer = qt_core.QTimer(window)
    timer.setInterval(POLL_INTERVAL_MS)
    timer.timeout.connect(poll)
    timer.start()
    window._mabao_playback_guard_timer = timer
    logger.info("播放全屏守卫已启动（每 %s ms 巡检一次全屏状态）", POLL_INTERVAL_MS)


def _handle(payload: Any, last: dict, logger: Any) -> None:
    text = _as_text(payload)
    if not text:
        return
    try:
        state = json.loads(text)
    except (TypeError, ValueError):
        return
    if not isinstance(state, dict):
        return
    log = state.get("log") or []
    signature = json.dumps(log[-3:], ensure_ascii=False, sort_keys=True) if log else ""
    if signature == last["signature"]:
        return
    last["signature"] = signature
    fullscreen = state.get("fullscreen")
    blocked = state.get("blocked")
    for entry in log[-3:]:
        if not isinstance(entry, dict):
            continue
        event = entry.get("event")
        if event in {"exit", "reenter-failed", "reenter-threw"}:
            logger.warning(
                "网页全屏事件: event=%s 用户按Esc=%s 详情=%s（累计拦截弹窗抢焦点 %s 次）",
                event,
                entry.get("byUser"),
                {k: v for k, v in entry.items() if k not in {"event", "t"}},
                blocked,
            )
        elif event in {"enter", "reenter"}:
            logger.info("网页全屏事件: event=%s 当前全屏=%s", event, fullscreen)


def _as_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (list, tuple)) and payload:
        return _as_text(payload[0])
    if isinstance(payload, dict):
        for key in ("result", "value", "data"):
            if key in payload:
                return _as_text(payload[key])
    return ""
