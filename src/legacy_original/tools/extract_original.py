from __future__ import annotations

import argparse
import importlib.util
import marshal
import shutil
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

EXCLUDED_MODULES = {
    "app.auth",
    "app.dialogs.auth_dialogs",
    "app.particle_splash",
    "tiandun",
}


def module_path(root: Path, name: str, is_package: bool) -> Path:
    parts = name.split(".")
    if is_package:
        return root.joinpath(*parts, "__init__.pyc")
    return root.joinpath(*parts[:-1], f"{parts[-1]}.pyc")


def write_pyc(path: Path, code) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = importlib.util.MAGIC_NUMBER + b"\0" * 12
    path.write_bytes(header + marshal.dumps(code))


def extract(executable: Path, output: Path) -> list[str]:
    archive = CArchiveReader(str(executable))
    pyz_name = next(name for name in archive.toc if name.startswith("PYZ"))
    pyz_blob = output.parent / "original.pyz"
    pyz_blob.parent.mkdir(parents=True, exist_ok=True)
    pyz_blob.write_bytes(archive.extract(pyz_name))
    pyz = ZlibArchiveReader(str(pyz_blob))
    extracted: list[str] = []
    try:
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        for name, entry in pyz.toc.items():
            if name in EXCLUDED_MODULES:
                continue
            code = pyz.extract(name)
            if code is None:
                output.joinpath(*name.split(".")).mkdir(parents=True, exist_ok=True)
                extracted.append(name)
                continue
            is_package = bool(entry[0])
            write_pyc(module_path(output, name, is_package), code)
            extracted.append(name)
    finally:
        pyz_blob.unlink(missing_ok=True)
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    modules = extract(args.executable.resolve(), args.output.resolve())
    print(f"extracted {len(modules)} original modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
