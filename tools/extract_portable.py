"""正确解压「二游辅助」便携包。

这个 zip 的条目名是 UTF-8 字节，但没有设置 zip 的 UTF-8 标志位（通用位 11）。
Windows 资源管理器 / Expand-Archive 按系统 ANSI 代码页（本机 = CP936）解码，
于是 `二游辅助` 变成 `浜屾父杈呭姪`，部分名字还会因为落在 GBK 双字节边界上而
不可逆地损坏（出现替换字符）。

本脚本直接读 zip 中央目录的原始字节，按 UTF-8 还原真实文件名；同时对每个写出的
文件清除 Mark-of-the-Web（Zone.Identifier 备用数据流）——这是 .NET Framework
拒绝加载 `Python.Runtime.dll` 的原因，会导致内嵌 WebView2 浏览器初始化失败。

用法：
    python extract_portable.py --src <zip> --dest <目录> [--strip-top] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

UTF8_FLAG = 0x800

# 控制台可能是 GBK，报告里含有 cp437 解码出来的原始名字，直接 print 会抛
# UnicodeEncodeError，所以统一按 UTF-8 输出、无法编码的字符用替代符。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def recover_name(info: zipfile.ZipInfo) -> tuple[str, bool]:
    """返回 (真实条目名, 是否发生了修复)。"""
    raw = info.filename
    if info.flag_bits & UTF8_FLAG:
        return raw, False
    try:
        # zipfile 在无 UTF-8 标志时按 cp437 解码，这里逆回去拿原始字节
        data = raw.encode("cp437")
    except UnicodeEncodeError:
        return raw, False
    try:
        fixed = data.decode("utf-8")
    except UnicodeDecodeError:
        return raw, False
    return fixed, fixed != raw


def safe_target(dest: Path, name: str) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    parts = [p for p in pure.parts if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValueError(f"拒绝解压越界路径: {name}")
    if pure.is_absolute() or (parts and ":" in parts[0]):
        raise ValueError(f"拒绝解压绝对路径: {name}")
    return dest.joinpath(*parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, help="源 zip")
    parser.add_argument("--dest", required=True, help="目标目录")
    parser.add_argument(
        "--strip-top",
        action="store_true",
        help="去掉 zip 里的第一层目录，直接把内容铺到 --dest 下",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写出的路径")
    parser.add_argument(
        "--manifest",
        default="",
        help="把 sha256/大小/条目映射写成 JSON（可选）",
    )
    args = parser.parse_args(argv)

    src = Path(args.src)
    if not src.is_file():
        parser.error(f"找不到 zip: {src}")
    dest = Path(args.dest)

    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    fixed_count = 0
    written: list[dict] = []
    renames: list[list[str]] = []
    top_levels: set[str] = set()

    with zipfile.ZipFile(src) as zf:
        infos = zf.infolist()
        for info in infos:
            name, repaired = recover_name(info)
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if parts:
                top_levels.add(parts[0])
        if args.strip_top and len(top_levels) != 1:
            print(
                f"[!] --strip-top 生效但顶层有 {len(top_levels)} 项: {sorted(top_levels)}",
                file=sys.stderr,
            )
        for info in infos:
            name, repaired = recover_name(info)
            if repaired:
                fixed_count += 1
                if len(renames) < 15:
                    renames.append([info.filename, name])
            if args.strip_top:
                parts = PurePosixPath(name.replace("\\", "/")).parts
                if not parts:
                    continue
                name = str(PurePosixPath(*parts[1:])) if len(parts) > 1 else ""
                if not name:
                    continue
            if name.endswith("/"):
                continue
            target = safe_target(dest, name)
            if info.is_dir():
                if not args.dry_run:
                    target.mkdir(parents=True, exist_ok=True)
                continue
            if args.dry_run:
                print(f"{info.file_size:>10}  {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as handle, open(target, "wb") as out:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
            written.append(
                {
                    "path": str(target.relative_to(dest)).replace("\\", "/"),
                    "size": info.file_size,
                }
            )

    if args.dry_run:
        print(f"[dry-run] 条目 {len(infos)}，需要修复文件名 {fixed_count} 个")
        for old, new in renames:
            print(f"    {old!r} -> {new!r}")
        return 0

    # 统一清除解压目录内所有文件的 Zone.Identifier（Python 解压不会带上，
    # 但目标目录里可能残留旧文件）
    cleared = 0
    for path in dest.rglob("*"):
        if path.is_file():
            zone = Path(f"{path}:Zone.Identifier")
            if zone.exists():
                zone.unlink()
                cleared += 1

    print(f"源 zip        : {src}  (sha256 {source_hash})")
    print(f"解压目标      : {dest}")
    print(f"写出文件      : {len(written)}")
    print(f"修复文件名    : {fixed_count}")
    for old, new in renames:
        print(f"    {old!r} -> {new!r}")
    print(f"清除 MOTW     : {cleared}")

    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "source_zip": str(src),
                    "source_zip_sha256": source_hash,
                    "dest": str(dest),
                    "file_count": len(written),
                    "repaired_names": fixed_count,
                    "renames_sample": renames,
                    "files": written,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"清单          : {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
