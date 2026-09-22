"""根据 B 站分P列表，算「跟跑视频」还剩多久。

用法：
    python estimate_watch_time.py --bvid BV1hjgG6jEa6 --page 13
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}


def hms(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, sec = divmod(rest, 60)
    if hours:
        return f"{hours} 小时 {minutes:02d} 分"
    return f"{minutes} 分 {sec:02d} 秒"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvid", default="BV1hjgG6jEa6")
    parser.add_argument("--page", type=int, default=13, help="当前/下一个分P")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    request = urllib.request.Request(
        API.format(bvid=args.bvid), headers=HEADERS
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        print(f"接口失败: {payload}")
        return 1
    data = payload["data"]
    pages = data["pages"]
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    total = sum(p["duration"] for p in pages)
    print(f"视频：{data['title']}")
    print(f"UP：{data['owner']['name']}｜共 {len(pages)} 个分P｜总时长 {hms(total)}")
    print()

    current = args.page
    for start, label in (
        (current, f"p{current} 还没开始跑（含 p{current}）"),
        (current + 1, f"p{current} 已经跑完（从 p{current + 1} 起）"),
    ):
        rest = [p for p in pages if p["page"] >= start]
        seconds = sum(p["duration"] for p in rest)
        print(f"● {label}")
        print(f"    剩 {len(rest)} 个分P｜纯视频 {hms(seconds)}（{int(seconds)} 秒）")
        print(
            f"    折算实际：×1.2 ≈ {hms(seconds * 1.2)}｜×1.35 ≈ {hms(seconds * 1.35)}"
            f"｜×1.5 ≈ {hms(seconds * 1.5)}"
        )
        print()

    print("=== 剩余分P明细（当前分P起，前 20 条）===")
    count = 0
    for page in pages:
        if page["page"] < current:
            continue
        count += 1
        if count > 20:
            print(f"    …… 其余 {len([p for p in pages if p['page'] >= current]) - 20} 个分P省略")
            break
        mark = "  ← 当前" if page["page"] == current else ""
        print(
            f"    p{page['page']:<3} {str(datetime.timedelta(seconds=page['duration'])):>8}"
            f"  {page['part']}{mark}"
        )

    print()
    print("=== 按区域汇总（当前分P起）===")
    buckets: dict[str, int] = {}
    order: list[str] = []
    for page in pages:
        if page["page"] < current:
            continue
        key = page["part"].split("（")[0].split("(")[0].strip()[:16]
        if key not in buckets:
            buckets[key] = 0
            order.append(key)
        buckets[key] += page["duration"]
    for key in order:
        print(f"    {key:<18} {hms(buckets[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
