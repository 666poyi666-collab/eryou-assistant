# 二游辅助（跟图跑视频辅助工具）

攻略视频 + 方向提醒 + 自动对话 + 本地图像定位（AI 导航）的 Windows 桌面工具。
本次整理把下载目录里的便携版搬进项目，修掉了「复制链接进去不跳转视频」的问题，
并把乱码文件名全部还原。

## 目录

| 路径 | 内容 |
|---|---|
| `app/` | 可直接运行的便携版（`二游辅助.exe` + `_internal/`，7233 个文件 / 528 MB） |
| `src/` | 源码快照（仓库 tag `v0.2.0`）：新的 `eryou_assistant` 源码 + `legacy_original` 打包层 |
| `tools/` | 解压/分析工具（`extract_portable.py` 等） |
| `发布存档/` | 原始发布包 `eryou-assistant-v0.2.0-win64-portable.zip`（214 MB，本地留档） |
| `app-清单.json` | `app/` 的文件清单（含源 zip 的 sha256、文件名修复对照） |
| `诊断与修复报告.md` | 三个问题的根因、证据与修法 |
| `启动二游辅助.cmd` | 双击启动（纯 ASCII，避免 cmd 中文乱码） |

## 怎么用

1. 双击 `启动二游辅助.cmd`（或直接 `app\二游辅助.exe`）。
2. 在地址栏粘贴攻略链接（B 站视频 / 网页）后回车。
3. 播放时 `~` 播放/暂停，`=` 循环倍速（1x / 1.25x / 1.5x / 2x），鼠标侧键 X1/X2 后退/前进。
4. 日志在 `%LOCALAPPDATA%\MabaoLocal\logs\<yyyy-MM-dd>.log`，设置在同目录。

## 关键修复（2026-09-20）

| 问题 | 根因 | 处理 |
|---|---|---|
| 解压后一堆乱码 | zip 条目名是 UTF-8 但没有 UTF-8 标志位，资源管理器按 CP936 解码 | 用 `tools\extract_portable.py` 直接读原始字节还原（8 个中文名全部还原，含 4 张模板图） |
| 放在下载目录 | 便携版被解压在 `Downloads` | 搬进 `03_二游辅助\app`，原 zip 归档到 `发布存档\`，下载目录里的解压件已删除 |
| 复制链接进去不跳转视频 | 下载来的 zip 在解压时给 7230/7231 个文件打上了「来自 Internet」标记（`Zone.Identifier`），.NET Framework 拒绝加载 `pythonnet\runtime\Python.Runtime.dll`，WebView2 初始化直接崩（`WebviewInitException`） | 重新解压（不再带标记）+ 清除 MOTW；实测 B 站游客 1080P 正常播放 |

复现/验收脚本见 `诊断与修复报告.md` 末尾。

## 重新解压（换机器 / 换版本时）

```powershell
python tools\extract_portable.py `
  --src .\发布存档\eryou-assistant-v0.2.0-win64-portable.zip `
  --dest .\app --strip-top --manifest .\app-清单.json
```

脚本会顺带清掉 `Zone.Identifier`。**不要用资源管理器「全部解压缩」**：中文名会乱码，
而且会把 MOTW 标记带进去，浏览器直接起不来。
