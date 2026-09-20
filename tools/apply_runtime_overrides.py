"""把 src/legacy_original/overrides 下的运行时覆盖文件铺到便携包 _internal 里。

原版构建脚本（build-local.ps1）本来就是这么做的：overrides\\app\\*.py 覆盖 _internal\\app\\*.py。
这里扩展成「任意子路径覆盖」，并支持 --check 只比对。

用法：
    python apply_runtime_overrides.py --bundle <便携包目录> [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\16408\Desktop\二游自动\03_二游辅助")
OVERRIDES = ROOT / "src" / "legacy_original" / "overrides"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="便携包目录（里面有 _internal）")
    parser.add_argument("--check", action="store_true", help="只比对，不写入")
    args = parser.parse_args(argv)

    bundle_internal = Path(args.bundle) / "_internal"
    if not bundle_internal.is_dir():
        print(f"[!] 找不到 {bundle_internal}")
        return 2
    if not OVERRIDES.is_dir():
        print(f"[!] 没有 overrides 目录：{OVERRIDES}")
        return 0

    pending: list[tuple[Path, Path]] = []
    for source in sorted(OVERRIDES.rglob("*")):
        if not source.is_file():
            continue
        pending.append((source, bundle_internal / source.relative_to(OVERRIDES)))

    changed = 0
    for source, target in pending:
        same = target.is_file() and digest(target) == digest(source)
        status = "ok  " if same else "更新"
        if not same:
            changed += 1
        print(f"  {status} {source.relative_to(OVERRIDES)}")
        if not same and not args.check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    print(f"覆盖文件 {len(pending)} 个，需要更新 {changed} 个" + ("（check 模式，未写入）" if args.check else ""))
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
