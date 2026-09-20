# 二游辅助原版功能本地化工程

本目录不重写妈宝功能。构建时从用户提供的原版 `mabao.exe` 中提取原始 Python
模块，使用本地入口直接启动原版 `MainWindow`，仅移除以下启动链路：

- 卡密登录、授权心跳和会员限制；
- 更新检查与“发现新版本”；
- 公告/推广开屏；
- 黑色粒子开屏；
- 网页中的常见广告请求和广告卡片。

原安装目录 `C:\Program Files (x86)\LanRenMaBao` 始终只读。默认输出和安装位置分别为
`dist\二游辅助` 与 `%LOCALAPPDATA%\Programs\MabaoLocal`。程序和快捷方式统一显示为
“二游辅助”；安装目录固定使用纯英文路径，避免 ONNX Runtime 在 Windows 中文路径下无法加载模型。

```powershell
.\legacy_original\build-local.ps1 -Install
```

构建结果保留原版的浏览器、字幕方向提醒、增强提醒、自动对话学习、AI 导航、
热键、收藏历史、主题和沉浸功能。CUDA DLL 不随本地版复制，ONNX 使用 CPU provider。
构建会校验原版 EXE 的 SHA256，并要求完整提取 3659 个字节码模块和 4 个
namespace package，其中 53 个为原版 `app` 功能模块；任一功能模块缺失都会直接终止打包。

本地入口会恢复原版日志、强制 ONNX Runtime 使用 CPU、在没有显式关闭时默认启用
AI 方向与定位，并补充 `=` 全局倍速循环（1x/1.25x/1.5x/2x）及跨页面记忆。

原神或星铁处于前台时，`~` 通过 Win32 全局热键控制播放/暂停，鼠标 X1/X2
通过 Raw Input 执行后退/前进；启动时只对首次显示使用“不激活”属性，之后恢复正常
任务栏激活行为。游戏前台时不会再反复改写本程序窗口的 Win32 扩展样式，避免切换时
出现最小化/弹回或任务栏状态异常。点击设置对话框时，游戏前台状态下默认不激活对话框；
按住 Ctrl 才进入明确的设置交互模式。

默认运行不会申请管理员权限，也不会安装全局低级输入钩子。旧版 elevated helper
仅在显式设置 `MABAO_ENABLE_ELEVATED_INPUT_HELPER=1` 时启动；普通情况下使用进程内
Raw Input，降低被游戏反作弊误判并结束游戏进程的风险。

B 站游客播放在 WebView2 `document-start` 阶段使用官方 `try_look=1` 试看能力，
自动选择实际返回的最高画质，上限为 1080P。1080P+/60、4K、HDR 和杜比仍需
登录或大会员，本地版不伪造 Cookie 或登录状态。登录遮罩只做页面样式隐藏。
游客画质实现参考了 MIT 许可的
[`ChrAlpha/bili-overdrive-hd`](https://github.com/ChrAlpha/bili-overdrive-hd)。
