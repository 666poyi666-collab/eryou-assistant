import pytest

from eryou_assistant.core.subtitle import SubtitleParser, subtitle_display_ms


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("往东北方向走", "northeast"),
        ("小地图的北方向", "north"),
        ("去图右上", "northeast"),
        ("向右转", "right_turn"),
        ("向左转", "left_turn"),
        ("东西", None),
        ("普通字幕", None),
    ],
)
def test_direction_and_turn_parsing(text: str, expected: str | None) -> None:
    match = SubtitleParser().parse(text)
    assert (match.key if match else None) == expected


def test_direction_history_and_subtitle_duration() -> None:
    parser = SubtitleParser()
    assert parser.parse("往北走").angle == 0
    assert parser.parse("偏东").key == "northeast"
    assert len(parser.history) == 2
    assert subtitle_display_ms("测试") == 2600
    assert subtitle_display_ms("很长" * 100) == 10000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("北边偏东", "northeast"),
        ("东边偏南", "southeast"),
        ("南边偏西", "southwest"),
        ("西边偏北", "northwest"),
        ("右边偏上", "northeast"),
        ("下边偏左", "southwest"),
        ("往上看", "north"),
        ("走左边", "west"),
        ("雷达显示北面", "north"),
    ],
)
def test_legacy_direction_phrases(text: str, expected: str) -> None:
    assert SubtitleParser().parse_direction(text) == expected
