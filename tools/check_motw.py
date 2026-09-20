"""体检：检查便携版文件有没有「来自 Internet」标记（Zone.Identifier）。

为什么重要：从网上下载的 zip 用资源管理器解压时，每个文件都会被打上这个标记，
.NET Framework 会因此拒绝加载 `pythonnet\\runtime\\Python.Runtime.dll`，
内嵌 WebView2 浏览器直接初始化失败 —— 表现就是「地址栏粘贴链接没反应、不跳转视频」。

用法：
    python check_motw.py                 # 默认检查 ..\\app
    python check_motw.py --app <目录>
退出码：0 = 干净；1 = 发现标记（浏览器会起不来）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CRITICAL = (
    "pythonnet/runtime/Python.Runtime.dll",
    "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
)


def zone_id(path: Path) -> str | None:
    try:
        return Path(f"{path}:Zone.Identifier").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default=str(Path(__file__).resolve().parents[1] / "app"))
    args = parser.parse_args(argv)
    app = Path(args.app)
    if not app.is_dir():
        print(f"[!] 目录不存在：{app}")
        return 2

    flagged: list[str] = []
    total = 0
    for path in app.rglob("*"):
        if not path.is_file():
            continue
        total += 1
        if zone_id(path) is not None:
            flagged.append(str(path.relative_to(app)).replace("\\", "/"))

    print(f"检查目录 : {app}")
    print(f"文件总数 : {total}")
    print(f"带 MOTW  : {len(flagged)}")
    hostile = False
    for rel in flagged[:20]:
        print(f"   - {rel}")
        if rel in CRITICAL:
            hostile = True
    if len(flagged) > 20:
        print(f"   ...另有 {len(flagged) - 20} 个")

    if not flagged:
        print("结论：干净 —— WebView2 / pythonnet 可以正常加载。")
        return 0
    print("结论：这个副本的浏览器起不来。请用 tools\\extract_portable.py 重新解压，")
    print("      或对目录执行 PowerShell 的 Get-ChildItem -Recurse | Unblock-File 后再试。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
