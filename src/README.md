# 二游辅助

二游辅助是一个纯免费、开源的 Windows 桌面工具，用于承载攻略浏览、方向提醒、
自动对话和本地图像定位能力。

这是从“懒人妈宝 6.0”迁移出来的新仓库。新版本不包含卡密、计费、登录心跳、
付费公告或强制更新逻辑，也不会要求用户关闭杀毒软件或降低 UAC。
程序启动时只加载本地首页，不加载推广开屏；嵌入浏览器保留用于攻略和视频，应用不注入
广告，并拦截常见广告请求。旧版黑色粒子动画已完全删除。

## 当前状态

- 已完成：WebView2 浏览、收藏历史管理、视频与网页全屏控制、事件式字幕桥、
  方向/转弯/增强浮窗、原神与星铁自动对话校准和后台识别、CPU ONNX 方向识别、
  XFeat 地图定位、持续选区识别、热键、预设、主题和沉浸窗口控制。
- 安全限制：自动对话默认 dry-run；内置多分辨率模板自检通过后，仍需用户明确确认才会
  开启真实按键。可用“校准截图”为当前游戏分辨率保存模板缩放比例。
- 不迁移：旧卡密授权、计费服务、明文 HTTP 授权、旧覆盖式更新器。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m eryou_assistant
```

完整 AI 功能通过可选依赖安装，使用 CPU `onnxruntime`，不需要 CUDA：

```powershell
uv pip install --python .\.venv\Scripts\python.exe "numpy>=1.26,<3" `
  "onnxruntime>=1.18,<2" "opencv-python-headless>=4.10,<5"
```

## 构建并安装本地版

本地版安装在当前用户的 `%LOCALAPPDATA%\Programs\二游辅助`，不请求管理员权限，
不会读取、覆盖或删除旧版 `Program Files` 目录。重复安装会把上一份本地版保留为
`二游辅助.previous`，便于手动回滚。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\build-local.ps1 -WithAI -Install
```

已经验收过 `dist\二游辅助` 时，可用 `-SkipBuild -Install` 仅执行原子安装。

卸载仅作用于上述当前用户目录和当前用户开始菜单快捷方式：

```powershell
.\scripts\uninstall-local.ps1
```

## 质量门禁

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
```

迁移范围见 [docs/MIGRATION.md](docs/MIGRATION.md)，旧版恢复证据见
[docs/LEGACY_RECOVERY.md](docs/LEGACY_RECOVERY.md)。

## 许可证

[MIT](LICENSE)
