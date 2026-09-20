from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureState(StrEnum):
    READY = "ready"
    MIGRATING = "migrating"


@dataclass(frozen=True, slots=True)
class Feature:
    key: str
    title: str
    summary: str
    state: FeatureState


FEATURES: tuple[Feature, ...] = (
    Feature("guide", "攻略浏览", "嵌入浏览、收藏、历史和视频控制", FeatureState.READY),
    Feature("direction", "方向提醒", "字幕方向、转向和增强浮窗", FeatureState.READY),
    Feature("dialog", "自动对话", "原神与星铁模板识别，默认 dry-run", FeatureState.READY),
    Feature("vision", "AI 定位", "CPU 方向识别与地图特征定位", FeatureState.READY),
    Feature("settings", "设置", "预设、热键和窗口行为", FeatureState.READY),
)


def feature_by_key(key: str) -> Feature:
    for feature in FEATURES:
        if feature.key == key:
            return feature
    raise KeyError(key)
