# 旧版恢复证据

本次恢复以只读安装目录 `C:\Program Files (x86)\LanRenMaBao` 为证据源，所有 archive
提取和反汇编都在 `%LOCALAPPDATA%\Temp\eryou-mabao-re-20260814` 的副本上执行。

## 原件身份

- `mabao.exe` SHA-256：`3E1E2181D967650646FF8739C9CEF8D4F74E0C6BA5610676794530DE968EBD1D`
- `update.exe` SHA-256：`93353653BF3AFF74DAA6B6BF38F142F8A3CD83BA5FDD3B723254133B08447C4A`
- `updata.zip` SHA-256：`E96FCEDEEB7AAAE14C83A902E0E6E9D82B54B2EC24D0935481B2074FD80BBD26`
- 主程序是 Python 3.12 / PyInstaller / PyQt5 / WebView2，PYZ 中有 56 个 `app.*` 模块。
- `updata.zip` 是截断文件，仅有 `mabao.exe` local header，没有完整 central directory。

## 恢复模块

- 浏览器：`app.webview_container`、`app.js_bridger`、`app.bookmark_manager`、
  `app.history_manager`、收藏/历史对话框和视频控制。
- 方向：`app.subtitle_parser`、`app.direction_reminder`、`app.turn_reminder`、
  `app.enhanced_reminder`、`app.subtitle_sprite`。
- 自动对话：`app.auto_dialog.*`、`auto_dialog_games.json` 和四张模板。
- AI：`app.ai_nav.*`、`cone_angle_detector`、两个 ONNX 模型。
- 系统体验：`app.hotkey_manager`、`app.settings`、`app.immersive_*`、主题和窗口管理。

`tools/legacy_introspect.py` 可重复导出 PyInstaller 中自有模块的符号、字符串和递归反汇编。
反汇编结果用于恢复行为契约，不作为新项目的长期源码事实。

## 丢弃模块

卡密登录、心跳、每日免费时长、公告抓取、推广首页、UAC 提权、旧更新器以及黑色粒子
拼接/瓦解均未迁移。旧安装目录没有被写入、覆盖或卸载。
