"""保证含非 ASCII 的 .ps1 带 UTF-8 BOM（PowerShell 5.1 才认）。

踩坑记录：`edit`/`write` 这类工具写文件不带 BOM，改一次脚本就可能把 BOM 弄丢，
于是 5.1 按 ANSI 解析中文，把 `}`/`{` 当 GBK 尾字节吞掉 → 假语法错误。
构建脚本第一步就跑这个，防止再犯。

用法：
    python ensure_bom.py           # 检查并修正（默认 src/ 与 tools/）
    python ensure_bom.py --check   # 只检查，返回非 0 表示需要修
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"
DEFAULT_DIRS = ("src", "tools")
SKIP_PARTS = {".git", "build", "venv", "__pycache__", "app", "app.previous", "发布存档"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def collect(dirs: list[str]) -> list[Path]:
    files: list[Path] = []
    for name in dirs:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.ps1"):
            if set(path.relative_to(ROOT).parts) & SKIP_PARTS:
                continue
            files.append(path)
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dirs", nargs="*", default=list(DEFAULT_DIRS))
    args = parser.parse_args(argv)

    fixed: list[Path] = []
    for path in collect(args.dirs):
        data = path.read_bytes()
        if data.startswith(BOM) or not any(byte > 127 for byte in data):
            continue
        fixed.append(path)
        if not args.check:
            path.write_bytes(BOM + data)

    if fixed:
        print(f"需要补 BOM 的 .ps1：{len(fixed)}")
        for path in fixed:
            print("   ", path.relative_to(ROOT))
    else:
        print("所有含中文的 .ps1 都有 BOM ✓")
    if args.check:
        return 1 if fixed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
