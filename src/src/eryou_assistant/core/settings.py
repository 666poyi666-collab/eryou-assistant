from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

DEFAULT_HOTKEYS = {
    "toggle_play": "~",
    "fast_forward": "6",
    "fast_backward": "5",
    "next_episode": "8",
    "prev_episode": "7",
    "toggle_visible": "F9",
    "toggle_mouse_passthrough": "F10",
    "toggle_auto_dialog": "F8",
    "toggle_always_on_top": "ctrl+shift+t",
}

DEFAULTS: dict[str, Any] = {
    "schema_version": 2,
    "active_preset": "默认",
    "presets": {
        "默认": {
            "hotkeys": DEFAULT_HOTKEYS,
            "video_skip_seconds": 5,
            "window": {
                "always_on_top": False,
                "transparency": 100,
                "mouse_passthrough": False,
                "theme": "light",
                "width": 1180,
                "height": 760,
                "x": None,
                "y": None,
            },
            "immersive": {
                "hole_enabled": True,
                "hole_radius": 250,
                "smart_dodge": False,
                "anti_occlude": True,
            },
            "direction": {
                "enabled": True,
                "subtitle_sprite": True,
                "turn_enabled": True,
                "enhanced_enabled": True,
            },
            "dialog": {"enabled": False, "allow_real_input": False},
            "vision": {"live": False, "edge_enhance": False, "region": None},
        }
    },
}


def default_config_dir() -> Path:
    override = os.environ.get("ERYOU_ASSISTANT_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(location or (Path.home() / ".eryou_assistant"))


def _merge(default: Any, current: Any) -> Any:
    if not isinstance(default, dict) or not isinstance(current, dict):
        return copy.deepcopy(current)
    merged = copy.deepcopy(default)
    for key, value in current.items():
        merged[key] = _merge(merged[key], value) if key in merged else copy.deepcopy(value)
    return merged


class SettingsStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or default_config_dir()
        self.path = self.config_dir / "settings.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return copy.deepcopy(DEFAULTS)
        if not isinstance(loaded, dict):
            return copy.deepcopy(DEFAULTS)
        if int(loaded.get("schema_version", 1)) < 2:
            replacements = {
                "toggle_visible": ("9", "F9"),
                "toggle_mouse_passthrough": ("0", "F10"),
                "toggle_auto_dialog": ("-", "F8"),
            }
            for preset in loaded.get("presets", {}).values():
                hotkeys = preset.get("hotkeys", {})
                for action, (old, new) in replacements.items():
                    if hotkeys.get(action) == old:
                        hotkeys[action] = new
            loaded["schema_version"] = 2
        return _merge(DEFAULTS, loaded)

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @property
    def active_preset_name(self) -> str:
        name = str(self.data.get("active_preset", "默认"))
        return name if name in self.data["presets"] else "默认"

    @property
    def active_preset(self) -> dict[str, Any]:
        return self.data["presets"][self.active_preset_name]

    def create_preset(self, name: str, source: str | None = None) -> None:
        clean_name = name.strip()
        if not clean_name or clean_name in self.data["presets"]:
            raise ValueError("预设名称为空或已存在")
        template = self.data["presets"].get(
            source or self.active_preset_name, DEFAULTS["presets"]["默认"]
        )
        self.data["presets"][clean_name] = copy.deepcopy(template)
        self.save()

    def rename_preset(self, old: str, new: str) -> None:
        clean_name = new.strip()
        if old == "默认" or not clean_name or clean_name in self.data["presets"]:
            raise ValueError("无法重命名该预设")
        self.data["presets"][clean_name] = self.data["presets"].pop(old)
        if self.active_preset_name == old:
            self.data["active_preset"] = clean_name
        self.save()

    def delete_preset(self, name: str) -> None:
        if name == "默认":
            raise ValueError("默认预设不能删除")
        self.data["presets"].pop(name)
        if self.active_preset_name == name:
            self.data["active_preset"] = "默认"
        self.save()

    def activate_preset(self, name: str) -> None:
        if name not in self.data["presets"]:
            raise KeyError(name)
        self.data["active_preset"] = name
        self.save()
