"""对比新旧 EXE 内嵌 PYZ 的模块清单，产出「重建包需要补的 stdlib 模块」清单。

重建 EXE 时 PyInstaller 只分析 launcher.py/local_features.py 的导入，会把原版包里
那些 stdlib 模块（fileinput、asyncio、multiprocessing…）漏掉；app 里的 .pyc 一旦
懒加载这些模块就会 ImportError（实测表现为 XFeat 模型加载失败、退回 ORB）。
本脚本从原版 EXE 的 PYZ 取模块清单，算出缺失的 stdlib 部分，交给 spec 当 hiddenimports。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(r"C:\Users\16408\Desktop\二游自动\03_二游辅助")
OLD_EXE = ROOT / "app" / "二游辅助.exe"
NEW_EXE = ROOT / "build" / "dist" / "二游辅助" / "二游辅助.exe"
OUT_JSON = ROOT / "build" / "hiddenimports_stdlib.json"

STDLIB = set(sys.stdlib_module_names)
# 这些标准库在打包时容易引入无关的大依赖或平台不兼容代码，保持排除
EXCLUDE_PREFIXES = ("tkinter", "test", "idlelib", "lib2to3", "turtledemo", "ensurepip", "distutils", "antigravity", "this")


def pyz_modules(path: Path) -> list[str]:
    if not path.is_file():
        raise SystemExit(f"找不到 EXE: {path}")
    reader = CArchiveReader(str(path))
    archive_name = next((n for n in reader.toc if n.lower().endswith(".pyz")), None)
    if archive_name is None:
        raise SystemExit(f"{path.name} 里没有 PYZ")
    return sorted(reader.open_embedded_archive(archive_name).toc.keys())


def main() -> int:
    old = pyz_modules(OLD_EXE)
    print(f"原版 PYZ 模块数: {len(old)}")
    new: list[str] = []
    if NEW_EXE.is_file():
        new = pyz_modules(NEW_EXE)
        print(f"当前重建 PYZ 模块数: {len(new)}")
    else:
        print("当前重建包不存在，按「原版全量 stdlib」生成清单")

    missing = [
        name
        for name in old
        if name not in set(new)
        and name.split(".")[0] in STDLIB
        and not name.startswith(EXCLUDE_PREFIXES)
    ]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(missing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"需要补的 stdlib 模块: {len(missing)} -> {OUT_JSON}")
    for name in missing[:25]:
        print("   -", name)
    if len(missing) > 25:
        print(f"   …… 其余 {len(missing) - 25} 个见 JSON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
