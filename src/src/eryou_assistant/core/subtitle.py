from __future__ import annotations

from collections import deque
from dataclasses import dataclass

DIRECTION_ALIASES = {
    "north": ("北", "正北", "北面", "北方", "北侧", "北端", "北向", "图上", "上"),
    "east": ("东", "正东", "东面", "东方", "东侧", "东端", "东向", "图右", "右"),
    "south": ("南", "正南", "南面", "南方", "南侧", "南端", "南向", "图下", "下"),
    "west": ("西", "正西", "西面", "西方", "西侧", "西端", "西向", "图左", "左"),
    "northeast": (
        "东北",
        "右上",
        "右偏上",
        "东偏北",
        "北偏东",
        "北边偏东",
        "东边偏北",
        "右边偏上",
        "上边偏右",
        "图右上",
        "右上方",
        "东北角",
    ),
    "southeast": (
        "东南",
        "右下",
        "右偏下",
        "东偏南",
        "南偏东",
        "南边偏东",
        "东边偏南",
        "右边偏下",
        "下边偏右",
        "图右下",
        "右下方",
        "东南角",
    ),
    "southwest": (
        "西南",
        "左下",
        "左偏下",
        "西偏南",
        "南偏西",
        "南边偏西",
        "西边偏南",
        "左边偏下",
        "下边偏左",
        "图左下",
        "左下方",
        "西南角",
    ),
    "northwest": (
        "西北",
        "左上",
        "左偏上",
        "西偏北",
        "北偏西",
        "北边偏西",
        "西边偏北",
        "左边偏上",
        "上边偏左",
        "图左上",
        "左上方",
        "西北角",
    ),
}

DIRECTION_DISPLAY = {
    "north": ("↑", "上"),
    "northeast": ("↗", "右上"),
    "east": ("→", "右"),
    "southeast": ("↘", "右下"),
    "south": ("↓", "下"),
    "southwest": ("↙", "左下"),
    "west": ("←", "左"),
    "northwest": ("↖", "左上"),
    "left_turn": ("↺", "左转"),
    "right_turn": ("↻", "右转"),
}
DIRECTION_ANGLE = {
    "north": 0,
    "northeast": 45,
    "east": 90,
    "southeast": 135,
    "south": 180,
    "southwest": 225,
    "west": 270,
    "northwest": 315,
}
TURN_ALIASES = {
    "left_turn": ("向左转", "往左转", "左拐", "向左拐", "打左方向", "左转"),
    "right_turn": ("向右转", "往右转", "右拐", "向右拐", "打右方向", "右转"),
}
TRIGGERS = (
    "往",
    "向",
    "朝",
    "沿",
    "顺着",
    "走",
    "去",
    "冲",
    "开",
    "看",
    "飞",
    "游",
    "行驶",
    "前进",
    "拐",
    "转",
    "跑",
    "移动",
    "地图",
    "雷达",
    "罗盘",
    "屏幕",
    "画面",
    "视角",
    "图",
    "方向",
    "边",
    "侧",
    "角",
    "端",
    "区域",
    "位置",
)
EXCLUDED = {"东西", "南北"}
KEYWORD_CHARS = frozenset("东西南北偏上下左右图边前正面方侧端向角区域位置")


@dataclass(frozen=True, slots=True)
class DirectionMatch:
    key: str
    arrow: str
    name: str
    angle: int | None
    source: str


class SubtitleParser:
    def __init__(self) -> None:
        self.previous_direction: str | None = None
        self._last_cardinal: str | None = None
        self._prev_tail = ""
        self.history: deque[DirectionMatch] = deque(maxlen=10)

    def parse(self, text: str) -> DirectionMatch | None:
        turn = self.parse_turn_hint(text)
        if turn:
            return self._record(turn, text)
        direction = self.parse_direction(text)
        if direction:
            return self._record(direction, text)
        return None

    def parse_direction(self, text: str) -> str | None:
        original = text or ""
        filtered = "".join(char for char in original if char in KEYWORD_CHARS)
        combined = f"{self._prev_tail}{filtered}"
        self._prev_tail = filtered[-1:] if filtered[-1:] in {"偏", "图"} else ""
        if not combined or any(word == combined for word in EXCLUDED):
            return None

        aliases = sorted(
            ((alias, key) for key, values in DIRECTION_ALIASES.items() for alias in values),
            key=lambda item: (
                len(item[0]),
                item[1] in {"northeast", "southeast", "southwest", "northwest"},
            ),
            reverse=True,
        )
        for alias, key in aliases:
            if alias not in combined or alias in EXCLUDED:
                continue
            if len(alias) == 1 and not any(trigger in original for trigger in TRIGGERS):
                continue
            self.previous_direction = key
            if key in {"north", "east", "south", "west"}:
                self._last_cardinal = key
            return key

        bias_axis = {
            "偏东": "east",
            "偏右": "east",
            "偏西": "west",
            "偏左": "west",
            "偏北": "north",
            "偏上": "north",
            "偏南": "south",
            "偏下": "south",
        }
        diagonal = {
            ("north", "east"): "northeast",
            ("north", "west"): "northwest",
            ("south", "east"): "southeast",
            ("south", "west"): "southwest",
            ("east", "north"): "northeast",
            ("east", "south"): "southeast",
            ("west", "north"): "northwest",
            ("west", "south"): "southwest",
        }
        if self._last_cardinal:
            for word, axis in bias_axis.items():
                if word in combined and (self._last_cardinal, axis) in diagonal:
                    return diagonal[(self._last_cardinal, axis)]
        return None

    def parse_turn_hint(self, text: str) -> str | None:
        for key, aliases in TURN_ALIASES.items():
            if any(alias in text for alias in aliases):
                return key
        return None

    def _record(self, key: str, source: str) -> DirectionMatch:
        arrow, name = DIRECTION_DISPLAY[key]
        match = DirectionMatch(key, arrow, name, DIRECTION_ANGLE.get(key), source)
        self.history.append(match)
        return match


def subtitle_display_ms(text: str) -> int:
    return min(2000 + 300 * len(text), 10000)
