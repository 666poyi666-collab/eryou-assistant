import pytest

from eryou_assistant.core.hotkeys import GlobalHotkeyManager, parse_hotkey
from eryou_assistant.core.settings import DEFAULT_HOTKEYS, SettingsStore


def test_settings_presets_are_isolated_and_persisted(tmp_path) -> None:
    store = SettingsStore(tmp_path)
    store.create_preset("游戏", "默认")
    store.activate_preset("游戏")
    store.active_preset["hotkeys"]["toggle_visible"] = "F9"
    store.save()

    restored = SettingsStore(tmp_path)
    assert restored.active_preset_name == "游戏"
    assert restored.active_preset["hotkeys"]["toggle_visible"] == "F9"
    assert restored.data["presets"]["默认"]["hotkeys"] == DEFAULT_HOTKEYS


def test_hotkey_parser_matches_legacy_keys() -> None:
    assert parse_hotkey("ctrl+alt+h") == (0x0003, ord("H"))
    assert parse_hotkey("F9") == (0, 0x78)
    assert parse_hotkey("~") == (0, 0xC0)
    with pytest.raises(KeyError):
        parse_hotkey("ctrl+unknown")


def test_unsafe_global_defaults_are_migrated(tmp_path) -> None:
    store = SettingsStore(tmp_path)
    store.active_preset["hotkeys"].update(
        {
            "toggle_visible": "9",
            "toggle_mouse_passthrough": "0",
            "toggle_auto_dialog": "-",
        }
    )
    store.data["schema_version"] = 1
    store.save()

    migrated = SettingsStore(tmp_path)
    assert migrated.active_preset["hotkeys"]["toggle_visible"] == "F9"
    assert migrated.active_preset["hotkeys"]["toggle_mouse_passthrough"] == "F10"
    assert migrated.active_preset["hotkeys"]["toggle_auto_dialog"] == "F8"


def test_invalid_hotkey_does_not_crash_registration(qapp) -> None:
    manager = GlobalHotkeyManager(qapp)
    assert manager.register("ctrl+unknown", lambda: None) is False
