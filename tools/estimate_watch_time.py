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


def region_of(part: str) -> str:
    return part.split("（")[0].split("(")[0].strip()[:16]


def build_batches(pages: list[dict], start: int, target_minutes: float) -> list[list[dict]]:
    """把剩余分P按「每批 target_minutes 左右」切批，尽量切在区域交界处。"""
    target = target_minutes * 60
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_seconds = 0.0
    for page in pages:
        if page["page"] < start:
            continue
        new_region_break = (
            current
            and region_of(page["part"]) != region_of(current[-1]["part"])
            and current_seconds >= target * 0.6
        )
        if new_region_break or (current and current_seconds + page["duration"] > target * 1.15):
            batches.append(current)
            current = []
            current_seconds = 0.0
        current.append(page)
        current_seconds += page["duration"]
    if current:
        batches.append(current)
    return batches


def print_plan(pages: list[dict], start: int, target_minutes: float, per_day: int, factor: float) -> None:
    batches = build_batches(pages, start, target_minutes)
    print()
    print(f"=== 建议排期（每批约 {target_minutes:.0f} 分钟视频，每天 {per_day} 批，折算系数 ×{factor}）===")
    for index, batch in enumerate(batches, 1):
        first, last = batch[0], batch[-1]
        seconds = sum(p["duration"] for p in batch)
        span = (
            f"p{first['page']}"
            if first["page"] == last["page"]
            else f"p{first['page']}~p{last['page']}"
        )
        region = region_of(last["part"])
        print(
            f"  第{index:>2}批  {span:<12} {len(batch):>2} 个分P  "
            f"视频 {hms(seconds):<10} 实际约 {hms(seconds * factor):<10} {region}"
        )
    print()
    days = (len(batches) + per_day - 1) // per_day
    for day in range(days):
        group = batches[day * per_day : (day + 1) * per_day]
        seconds = sum(p["duration"] for batch in group for p in batch)
        span_first = group[0][0]["page"]
        span_last = group[-1][-1]["page"]
        print(
            f"  第 {day + 1} 天：{len(group)} 批（p{span_first}~p{span_last}）"
            f"｜视频 {hms(seconds)}｜实际约 {hms(seconds * factor)}"
        )
    print(f"  → 共 {len(batches)} 批，按每天 {per_day} 批约 {days} 天跑完")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvid", default="BV1hjgG6jEa6")
    parser.add_argument("--page", type=int, default=13, help="当前/下一个分P")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--plan", action="store_true", help="输出分批排期建议")
    parser.add_argument("--batch-minutes", type=float, default=75.0, help="每批视频时长目标（分钟）")
    parser.add_argument("--per-day", type=int, default=2, help="每天跑几批")
    parser.add_argument("--factor", type=float, default=1.35, help="视频→实际的折算系数")
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
    print("=== 已完成段（用于校准你自己的系数）===")
    done = [p for p in pages if p["page"] < current]
    if done:
        done_seconds = sum(p["duration"] for p in done)
        print(f"    p1~p{current - 1}：{len(done)} 个分P，视频时长合计 {hms(done_seconds)}")
        print(
            f"    如果你记得这段实际花了 T 小时，你的系数 = T ÷ {done_seconds / 3600:.2f}"
            "（对话/过场/拾取越多，系数越大）"
        )
    else:
        print("    （还没有已完成的分P）")

    print()
    print("=== 剩余里最长的 8 个分P ===")
    for page in sorted(
        (p for p in pages if p["page"] >= current), key=lambda p: -p["duration"]
    )[:8]:
        print(f"    p{page['page']:<3} {hms(page['duration']):>10}  {page['part']}")

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

    if args.plan:
        print_plan(pages, current, args.batch_minutes, args.per_day, args.factor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
