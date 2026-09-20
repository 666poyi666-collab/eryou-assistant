"""列出便携版 app 包（以及几个顶层模块）真正 import 的第三方依赖。

做法：用 Python 3.12 读 .pyc → marshal → 遍历所有 code object 收集 IMPORT_NAME/IMPORT_FROM，
再去掉标准库，剩下的就是打包时必须装的第三方包。
"""

from __future__ import annotations

import dis
import marshal
import pathlib
import sys
import types

if sys.version_info[:2] != (3, 12):
    raise SystemExit(f"需要 CPython 3.12 读这些 pyc，当前 {sys.version.split()[0]}")

ROOT = pathlib.Path(r"C:\Users\16408\Desktop\二游自动\03_二游辅助\app\_internal")
STDLIB = set(sys.stdlib_module_names)


def walk(code: types.CodeType, out: set[str], depth: int = 0) -> None:
    if depth > 12:
        return
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            walk(const, out, depth + 1)
    for name in code.co_names:
        out.add(name)


def imports_of(path: pathlib.Path) -> set[str]:
    """精确收集 IMPORT_NAME 的目标模块名。"""
    try:
        if path.suffix == ".pyc":
            code = marshal.loads(path.read_bytes()[16:])
        else:
            code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except Exception:  # noqa: BLE001
        return set()
    found: set[str] = set()
    stack: list[types.CodeType] = [code]
    while stack:
        current = stack.pop()
        for const in current.co_consts:
            if isinstance(const, types.CodeType):
                stack.append(const)
        for ins in dis.get_instructions(current):
            if ins.opname == "IMPORT_NAME" and isinstance(ins.argval, str):
                found.add(ins.argval.split(".")[0])
    return found


def main() -> int:
    targets = sorted((ROOT / "app").rglob("*.pyc"))
    targets += [ROOT / name for name in ("logger.pyc", "screenshot.pyc", "model_locate.pyc", "cone_angle_detector.pyc")]
    targets += sorted((ROOT / "qtwebview2").glob("*.py"))

    all_tokens: set[str] = set()
    per_file: dict[str, set[str]] = {}
    for path in targets:
        if not path.exists():
            continue
        names = imports_of(path)
        per_file[str(path.relative_to(ROOT))] = names
        all_tokens |= names

    third_party = {
        token
        for token in all_tokens
        if token.split(".")[0] not in STDLIB
        and token.isidentifier()
        and not token.startswith("_")
    }
    print("=== 可能是第三方/本地模块的顶层名 ===")
    for name in sorted(third_party):
        users = [f for f, names in per_file.items() if name in names]
        print(f"  {name:24} 出现在 {len(users)} 个文件   例: {users[0] if users else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

