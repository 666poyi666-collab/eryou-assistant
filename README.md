# 二游辅助（跟图跑视频辅助工具）

攻略视频 + 方向提醒 + 自动对话 + 本地图像定位（AI 导航）的 Windows 桌面工具。
既修好了「乱码 / 放错目录 / 粘贴链接不跳转视频」，也补齐了界面与安全方面的一批改动
（一键无边框、登录态与画质、切窗口/任务栏、鼠标侧键）。

## 目录

| 路径 | 内容 |
|---|---|
| `app/` | 可直接运行的便携版（`二游辅助.exe` + `_internal/`，7239 个文件 / 528 MB） |
| `app.previous/` | 上一次构建的便携版（回滚用：删掉 `app`、把 `app.previous` 改名回 `app`） |
| `src/` | 源码快照（tag `v0.2.0`）：重写版 `eryou_assistant` + `legacy_original` 打包/补丁层 |
| `tools/` | 解压、体检、重建辅助脚本（`extract_portable.py`、`check_motw.py`、`inspect_pyz.py` 等） |
| `build/` | 本地构建环境（venv、PyInstaller 产物；不进版本库） |
| `发布存档/` | 最初的 `eryou-assistant-v0.2.0-win64-portable.zip`（214 MB，本地留档） |
| `app-清单.json` | `app/` 的文件清单（含源 zip 的 sha256、文件名修复对照） |
| `诊断与修复报告.md` | 第一轮：乱码 / 位置 / 浏览器起不来（MOTW） |
| [`修复报告-界面与安全.md`](修复报告-界面与安全.md) | 第二轮：无边框、登录画质、任务栏、侧键、提权助手清理 |
| `启动二游辅助.cmd` | 双击启动（纯 ASCII，避免 cmd 中文乱码） |

## 怎么用

1. 双击 `启动二游辅助.cmd`（或直接 `app\二游辅助.exe`）。
2. 在地址栏粘贴攻略链接（B 站视频 / 网页）后回车。
3. 播放时 `~` 播放/暂停，`=` 循环倍速（1x / 1.25x / 1.5x / 2x），鼠标侧键 X1/X2 快退/快进
   （映射来自 `~\.mabao\hotkeys.json` 的 `side_buttons`）。
4. 标题栏 `⛶` 进入**一键无边框**（只留画面、仍可缩放），右上角「还原」或 `F10` 切回。
5. 登录态存在 `%LOCALAPPDATA%\懒宝浏览器\WebView2_UserData`（可用环境变量
   `MABAO_WEBVIEW_PROFILE` 固定到别处）；登录后画质不再被压在 1080P。
6. 日志在 `%LOCALAPPDATA%\MabaoLocal\logs\<yyyy-MM-dd>.log`，设置在同目录（`~\.mabao\`）。

## 改源码后怎么生效（重要）

`src\legacy_original\*.py` 是**补丁层**，冻结在 EXE 里，改完必须重建：

```powershell
powershell -File src\legacy_original\build-portable.ps1 -Deploy
# 只构建不替换：去掉 -Deploy；回滚：删 app、把 app.previous 改名回 app
```

依赖（PyQt5/pythonnet/numpy/cv2/onnxruntime + 原版 app 字节码）直接复用现有便携包的
`_internal`，所以一次重建只要几十秒；`tools\inspect_pyz.py` 会保证新旧包的 PYZ 模块集合一致
（漏掉 stdlib 会让 XFeat 退回 ORB）。

## 关键修复（2026-09-20）

| 问题 | 根因 | 处理 |
|---|---|---|
| 解压后一堆乱码 | zip 条目名是 UTF-8 但没有 UTF-8 标志位，资源管理器按 CP936 解码 | 用 `tools\extract_portable.py` 直接读原始字节还原（8153 个条目全部还原） |
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

## 仓库与发布

* 本目录是独立仓库：https://github.com/666poyi666-collab/eryou-assistant
* 便携版发布包走 Releases（`v0.2.0`），不入源码树；本地留档在 `发布存档\`
* 上级目录 `..\`（`二游自动`）是另一个仓库 `er-you-auto-workspace`（原神/异环自动化），
  它用 `.gitignore` 把本目录排除掉，两边互不干扰

