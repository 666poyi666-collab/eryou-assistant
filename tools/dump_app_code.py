"""反汇编便携版 app 包里的指定函数，用来摸清界面结构（属性名/动作名）。

用法：
    python dump_app_code.py title_bar.pyc                 # 列出所有函数名
    python dump_app_code.py title_bar.pyc __init__ _build_ui
    python dump_app_code.py main_window.pyc _init_ui --consts
"""

from __future__ import annotations

import dis
import marshal
import sys
import types
from pathlib import Path

if sys.version_info[:2] != (3, 12):
    raise SystemExit("需要 CPython 3.12")

APP = Path(r"C:\Users\16408\Desktop\二游自动\03_二游辅助\app\_internal\app")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(relative: str) -> types.CodeType:
    return marshal.loads((APP / relative).read_bytes()[16:])


def walk(code: types.CodeType, prefix: str = ""):
    if isinstance(code, types.CodeType):
        yield prefix + code.co_name, code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from walk(const, prefix + code.co_name + ".")


def main(argv: list[str]) -> int:
    target = argv[0]
    code = load(target)
    names = list(walk(code))
    if len(argv) == 1:
        for name, _ in names:
            print(name)
        return 0
    filters = [a for a in argv[1:] if not a.startswith("--")]
    want_globals = "--globals" in argv
    for name, obj in names:
        if filters and not any(f in name for f in filters):
            continue
        print("=" * 90)
        print(f"### {name}  (line {obj.co_firstlineno})")
        print("co_names:", ", ".join(obj.co_names))
        strings = [c for c in obj.co_consts if isinstance(c, str)]
        if strings:
            print("consts(str):", " | ".join(repr(c) for c in strings[:60]))
        if want_globals:
            dis.dis(obj, depth=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
