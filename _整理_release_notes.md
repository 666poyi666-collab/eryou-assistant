## 下载后必读

这个便携包是 zip，**不要用资源管理器「全部解压缩」**：

1. 条目名没有 UTF-8 标志位，中文名会变成乱码（`二游辅助.exe` → `浜屾父杈呭姪.exe`）；
2. 更关键的是，解压出的文件会被打上「来自 Internet」标记，.NET Framework 会拒绝加载
   `pythonnet\runtime\Python.Runtime.dll`，**内嵌浏览器（WebView2）直接启动失败**，
   表现就是「地址栏粘贴链接没反应、不跳转视频」。

正确解压（自动还原中文名 + 清除标记）：

```powershell
python tools\extract_portable.py `
  --src eryou-assistant-v0.2.0-win64-portable.zip `
  --dest .\app --strip-top
```

已经用资源管理器解压过也没关系，对解压目录执行一次
`Get-ChildItem -Recurse | Unblock-File` 即可恢复播放能力；`tools\check_motw.py` 可以体检。

## 校验

```
sha256  a9262758eed31d6793c68544cee4cc1179382f3ca03d42ce8bd85ab7bb08db44
size    224379683 bytes
```

## 说明

源码见本仓库 `src/`（快照自 er-you-auto-workspace 的 tag v0.2.0）。
本包为 PyInstaller one-dir 便携版，运行体不随源码树分发。
