from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WindowSnapshot:
    hwnd: int
    title: str
    class_name: str
    process_name: str
    client_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class TemplateProfile:
    id: str
    display_name: str
    template_path: str
    base_region: tuple[int, int, int, int]
    trigger_action: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class GameProfile:
    key: str
    display_name: str
    title_patterns: tuple[str, ...]
    class_patterns: tuple[str, ...]
    process_patterns: tuple[str, ...]
    base_resolution: tuple[int, int]
    templates: tuple[TemplateProfile, ...]


@dataclass(frozen=True, slots=True)
class DialogDecision:
    game: str
    template_id: str
    action: str
    score: float
    passed: bool
    dry_run: bool
    message: str


class DialogLearningStore:
    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / "auto_dialog_learned.json"
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "games": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "games": {}}
        return payload if isinstance(payload, dict) else {"version": 1, "games": {}}

    @staticmethod
    def resolution_key(size: tuple[int, int]) -> str:
        return f"{size[0]}x{size[1]}"

    def get_scale(self, game: str, size: tuple[int, int], template_id: str) -> float | None:
        entry = (
            self.data.get("games", {})
            .get(game, {})
            .get(self.resolution_key(size), {})
            .get(template_id)
        )
        return float(entry["scale"]) if isinstance(entry, dict) and "scale" in entry else None

    def save(self, game: str, size: tuple[int, int], values: dict[str, dict]) -> None:
        games = self.data.setdefault("games", {})
        resolution = games.setdefault(game, {}).setdefault(self.resolution_key(size), {})
        resolution.update(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


def load_game_profiles() -> dict[str, GameProfile]:
    config_path = files("eryou_assistant.resources").joinpath("auto_dialog_games.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    profiles: dict[str, GameProfile] = {}
    for key, raw in payload.items():
        if key.startswith("_") or not isinstance(raw, dict) or not raw.get("enabled", True):
            continue
        templates = tuple(
            TemplateProfile(
                id=item["id"],
                display_name=item["display_name"],
                template_path=Path(item["template_path"]).name,
                base_region=tuple(item["base_region"]),
                trigger_action=item["trigger_action"],
                enabled=bool(item.get("enabled", True)),
            )
            for item in raw.get("templates", [])
        )
        profiles[key] = GameProfile(
            key=key,
            display_name=raw["display_name"],
            title_patterns=tuple(raw.get("window_title_match", {}).get("patterns", [])),
            class_patterns=tuple(raw.get("window_class_match", {}).get("patterns", [])),
            process_patterns=tuple(raw.get("process_name_match", {}).get("patterns", [])),
            base_resolution=tuple(raw.get("base_resolution", (2560, 1440))),
            templates=templates,
        )
    return profiles


def template_resource_path(name: str) -> Path:
    return Path(str(files("eryou_assistant.resources").joinpath("templates", name)))


def match_game(snapshot: WindowSnapshot, profiles: dict[str, GameProfile]) -> GameProfile | None:
    title = snapshot.title.casefold()
    class_name = snapshot.class_name.casefold()
    process_name = snapshot.process_name.casefold()
    for profile in profiles.values():
        title_match = any(pattern.casefold() in title for pattern in profile.title_patterns)
        class_match = any(pattern.casefold() == class_name for pattern in profile.class_patterns)
        process_match = any(
            pattern.casefold() in process_name for pattern in profile.process_patterns
        )
        if title_match and (class_match or process_match):
            return profile
    return None


def scale_region(
    region: tuple[int, int, int, int],
    base_resolution: tuple[int, int],
    current_resolution: tuple[int, int],
) -> tuple[int, int, int, int]:
    base_width, base_height = base_resolution
    width, height = current_resolution
    x_scale, y_scale = width / base_width, height / base_height
    x1, y1, x2, y2 = region
    return (
        round(x1 * x_scale),
        round(y1 * y_scale),
        round(x2 * x_scale),
        round(y2 * y_scale),
    )


class TemplateMatcher:
    def match(
        self,
        image,
        template_path: Path,
        *,
        scale: float = 1.0,
    ) -> tuple[float, tuple[int, int] | None]:
        import cv2
        import numpy as np

        if image is None or not template_path.exists():
            return 0.0, None
        template_bytes = np.fromfile(str(template_path), dtype=np.uint8)
        template = cv2.imdecode(template_bytes, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return 0.0, None
        source = self._gray(image)
        best_score = 0.0
        best_location = None
        for candidate in (scale, scale - 0.03, scale + 0.03):
            candidate = max(0.2, candidate)
            resized = cv2.resize(
                template,
                None,
                fx=candidate,
                fy=candidate,
                interpolation=cv2.INTER_CUBIC if candidate >= 1 else cv2.INTER_AREA,
            )
            if source.shape[0] < resized.shape[0] or source.shape[1] < resized.shape[1]:
                continue
            scores = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
            _, maximum, _, location = cv2.minMaxLoc(scores)
            if maximum > best_score:
                best_score = float(maximum)
                best_location = location
        return best_score, best_location

    @staticmethod
    def _gray(image):
        import cv2

        if image.ndim == 2:
            return image
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


class AutoDialogEngine:
    def __init__(
        self,
        threshold: float = 0.70,
        cooldown_seconds: float = 0.45,
        config_dir: Path | None = None,
    ) -> None:
        self.profiles = load_game_profiles()
        self.matcher = TemplateMatcher()
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.regression_verified = False
        self._last_action_at = 0.0
        self.learning_store = DialogLearningStore(config_dir or (Path.home() / ".eryou_assistant"))

    def verify_bundled_templates(
        self, resolutions: tuple[tuple[int, int], ...] = ((1280, 720), (1920, 1080))
    ) -> tuple[bool, list[str]]:
        import cv2
        import numpy as np

        failures: list[str] = []
        for profile in self.profiles.values():
            for template in profile.templates:
                source = cv2.imdecode(
                    np.fromfile(template_resource_path(template.template_path), dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if source is None:
                    failures.append(f"{profile.key}/{template.id}: missing")
                    continue
                for width, height in resolutions:
                    frame = np.zeros((height, width, 3), dtype=np.uint8)
                    scale = (
                        width / profile.base_resolution[0] + height / profile.base_resolution[1]
                    ) / 2
                    resized = cv2.resize(
                        source,
                        None,
                        fx=scale,
                        fy=scale,
                        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
                    )
                    x1, y1, x2, y2 = scale_region(
                        template.base_region,
                        profile.base_resolution,
                        (width, height),
                    )
                    copy_height = min(resized.shape[0], y2 - y1)
                    copy_width = min(resized.shape[1], x2 - x1)
                    frame[y1 : y1 + copy_height, x1 : x1 + copy_width] = resized[
                        :copy_height, :copy_width
                    ]
                    result = self.evaluate_frame(profile, frame)
                    if result is None or result.template_id != template.id:
                        failures.append(f"{profile.key}/{template.id}@{width}x{height}")
        self.regression_verified = not failures
        return self.regression_verified, failures

    def evaluate_frame(self, profile: GameProfile, frame) -> DialogDecision | None:
        height, width = frame.shape[:2]
        scale = (width / profile.base_resolution[0] + height / profile.base_resolution[1]) / 2
        for template in profile.templates:
            if not template.enabled:
                continue
            x1, y1, x2, y2 = scale_region(
                template.base_region,
                profile.base_resolution,
                (width, height),
            )
            region = frame[max(0, y1) : min(height, y2), max(0, x1) : min(width, x2)]
            learned_scale = self.learning_store.get_scale(profile.key, (width, height), template.id)
            score, _ = self.matcher.match(
                region,
                template_resource_path(template.template_path),
                scale=learned_scale or scale,
            )
            if score >= self.threshold:
                return DialogDecision(
                    profile.key,
                    template.id,
                    template.trigger_action,
                    score,
                    True,
                    True,
                    f"识别到{template.display_name}",
                )
        return None

    def learn_from_frame(self, profile: GameProfile, frame) -> dict[str, dict]:
        import numpy as np

        height, width = frame.shape[:2]
        learned: dict[str, dict] = {}
        candidates = np.linspace(0.3, 2.5, 89)
        for template in profile.templates:
            x1, y1, x2, y2 = scale_region(
                template.base_region,
                profile.base_resolution,
                (width, height),
            )
            region = frame[max(0, y1) : min(height, y2), max(0, x1) : min(width, x2)]
            best_score = 0.0
            best_scale = 1.0
            for candidate in candidates:
                score, _ = self.matcher.match(
                    region,
                    template_resource_path(template.template_path),
                    scale=float(candidate),
                )
                if score > best_score:
                    best_score = score
                    best_scale = float(candidate)
            if best_score >= 0.40:
                learned[template.id] = {
                    "scale": round(best_scale, 4),
                    "score": round(best_score, 6),
                    "client_size": [width, height],
                }
        self.learning_store.save(profile.key, (width, height), learned)
        return learned

    def trigger(self, decision: DialogDecision, *, allow_real_input: bool) -> DialogDecision:
        now = time.monotonic()
        if now - self._last_action_at < self.cooldown_seconds:
            return DialogDecision(
                decision.game,
                decision.template_id,
                decision.action,
                decision.score,
                decision.passed,
                True,
                "冷却中，未发送按键",
            )
        self._last_action_at = now
        if not allow_real_input or not self.regression_verified:
            return DialogDecision(
                decision.game,
                decision.template_id,
                decision.action,
                decision.score,
                decision.passed,
                True,
                f"dry-run：将执行 {decision.action}",
            )
        _press_action(decision.action)
        return DialogDecision(
            decision.game,
            decision.template_id,
            decision.action,
            decision.score,
            decision.passed,
            False,
            f"已执行 {decision.action}",
        )


def foreground_window_snapshot() -> WindowSnapshot | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = int(user32.GetForegroundWindow())
    if not hwnd:
        return None
    title_buffer = ctypes.create_unicode_buffer(512)
    class_buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
    rect = ctypes.wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    process_id = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process_name = _process_name(process_id.value)
    return WindowSnapshot(
        hwnd,
        title_buffer.value,
        class_buffer.value,
        process_name,
        (rect.right - rect.left, rect.bottom - rect.top),
    )


def _process_name(process_id: int) -> str:
    if not process_id:
        return ""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not handle:
        return ""
    try:
        size = ctypes.wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _press_action(action: str) -> None:
    if sys.platform != "win32":
        return
    key_name = action.removeprefix("press_").removesuffix("_key").upper()
    virtual_keys = {
        "F": 0x46,
        "SPACE": 0x20,
        "ENTER": 0x0D,
        "ESC": 0x1B,
        "TAB": 0x09,
        "BACK": 0x08,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
        **{str(number): 0x30 + number for number in range(10)},
    }
    virtual_key = virtual_keys.get(key_name)
    if not virtual_key:
        raise ValueError(f"不支持的动作: {action}")
    ctypes.windll.user32.keybd_event(virtual_key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(virtual_key, 0, 0x0002, 0)
