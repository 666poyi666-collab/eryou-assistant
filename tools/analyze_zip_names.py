"""分析 zip 条目名编码：UTF-8 / GBK / 其他。"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ZIP = Path(
    r"C:\Users\16408\Downloads\eryou-assistant-v0.2.0-win64-portable.zip"
)

with zipfile.ZipFile(ZIP) as zf:
    infos = zf.infolist()

utf8_ok = 0
utf8_bad: list[tuple[str, str, str]] = []
ascii_only = 0
flagged = 0
for info in infos:
    if info.flag_bits & 0x800:
        flagged += 1
    raw = info.filename.encode("cp437", errors="replace")
    if all(b < 0x80 for b in raw):
        ascii_only += 1
        continue
    try:
        raw.decode("utf-8")
        utf8_ok += 1
    except UnicodeDecodeError:
        gbk = ""
        try:
            gbk = raw.decode("cp936")
        except UnicodeDecodeError:
            gbk = "<cp936 也失败>"
        utf8_bad.append((info.filename, repr(raw), gbk))

print(f"总条目        : {len(infos)}")
print(f"UTF-8 标志位  : {flagged}")
print(f"纯 ASCII 名   : {ascii_only}")
print(f"非 ASCII UTF-8: {utf8_ok}")
print(f"非 ASCII 非法 : {len(utf8_bad)}")
print("--- 非法 UTF-8 的名字（最多 20 条）---")
for name, raw, gbk in utf8_bad[:20]:
    print(f"  cp437={name!r}\n    raw={raw}\n    cp936={gbk!r}")
