from __future__ import annotations

import argparse
import dis
import json
import types
from pathlib import Path
from typing import Any

from PyInstaller.archive.readers import CArchiveReader


def _code_metadata(code: types.CodeType) -> dict[str, Any]:
    return {
        "name": code.co_name,
        "qualname": code.co_qualname,
        "filename": code.co_filename,
        "first_line": code.co_firstlineno,
        "arg_count": code.co_argcount,
        "positional_only": code.co_posonlyargcount,
        "keyword_only": code.co_kwonlyargcount,
        "names": list(code.co_names),
        "variables": list(code.co_varnames),
        "strings": [value for value in code.co_consts if isinstance(value, str)],
        "children": [
            _code_metadata(value) for value in code.co_consts if isinstance(value, types.CodeType)
        ],
    }


def _recursive_disassembly(code: types.CodeType, depth: int = 0) -> str:
    heading = f"{'=' * 20} {'  ' * depth}{code.co_qualname} {'=' * 20}\n"
    output = [heading, dis.Bytecode(code).dis(), "\n"]
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            output.append(_recursive_disassembly(value, depth + 1))
    return "".join(output)


def inspect_archive(archive_path: Path, output_root: Path) -> int:
    archive = CArchiveReader(str(archive_path))
    pyz = archive.open_embedded_archive("PYZ-00.pyz")
    modules = sorted(name for name in pyz.toc if name == "app" or name.startswith("app."))
    output_root.mkdir(parents=True, exist_ok=True)

    index: dict[str, Any] = {
        "archive": str(archive_path),
        "modules": modules,
        "entrypoint": _code_metadata(__import__("marshal").loads(archive.extract("main"))),
    }
    (output_root / "main.dis.txt").write_text(
        _recursive_disassembly(__import__("marshal").loads(archive.extract("main"))),
        encoding="utf-8",
    )

    for module_name in modules:
        code = pyz.extract(module_name)
        if not isinstance(code, types.CodeType):
            continue
        filename = module_name.replace(".", "_")
        metadata = _code_metadata(code)
        index[module_name] = metadata
        (output_root / f"{filename}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_root / f"{filename}.dis.txt").write_text(
            _recursive_disassembly(code),
            encoding="utf-8",
        )

    (output_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(modules)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect app modules in a PyInstaller archive.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = inspect_archive(args.archive.resolve(), args.output.resolve())
    print(f"exported {count} app modules to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
