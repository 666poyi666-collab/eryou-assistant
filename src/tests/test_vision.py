import cv2
import numpy as np
import pytest

from eryou_assistant.core.vision import ConeAngleDetector, FeatureLocator


def test_bundled_angle_model_runs_on_cpu() -> None:
    detector = ConeAngleDetector()
    result = detector.predict(np.zeros((200, 200, 3), dtype=np.uint8))
    assert 0 <= result.angle < 360
    assert result.confidence >= 0


def test_feature_locator_finds_exact_crop() -> None:
    rng = np.random.default_rng(42)
    large = rng.integers(0, 256, size=(600, 800, 3), dtype=np.uint8)
    cv2.circle(large, (400, 300), 60, (255, 255, 255), 4)
    small = large[200:400, 300:500].copy()
    locator = FeatureLocator()
    result = locator.locate(large, small)
    assert result is not None
    assert result.x == pytest.approx(0.5, abs=0.03)
    assert result.y == pytest.approx(0.5, abs=0.03)
    assert result.confidence > 0.5
    assert locator._session is not None
    assert locator.last_backend in {"xfeat", "orb-fallback"}
