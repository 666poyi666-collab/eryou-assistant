import cv2
import numpy as np
import pytest

from eryou_assistant.core.auto_dialog import (
    AutoDialogEngine,
    DialogDecision,
    scale_region,
    template_resource_path,
)


def test_bundled_games_and_scaled_regions() -> None:
    engine = AutoDialogEngine()
    assert engine.profiles.keys() == {"genshin", "starrail"}
    assert scale_region((100, 200, 300, 400), (1000, 1000), (500, 2000)) == (
        50,
        400,
        150,
        800,
    )


def test_exact_template_match_stays_dry_run() -> None:
    engine = AutoDialogEngine(threshold=0.7)
    profile = engine.profiles["genshin"]
    template = profile.templates[0]
    raw = np.fromfile(template_resource_path(template.template_path), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    score, _ = engine.matcher.match(image, template_resource_path(template.template_path))
    assert score > 0.99

    decision = DialogDecision(
        profile.key,
        template.id,
        template.trigger_action,
        score,
        True,
        True,
        "test",
    )
    result = engine.trigger(decision, allow_real_input=True)
    assert result.dry_run is True
    assert "dry-run" in result.message


def test_dialog_detection_scales_across_common_resolutions() -> None:
    engine = AutoDialogEngine(threshold=0.7)
    profile = engine.profiles["genshin"]
    template = profile.templates[0]
    raw = np.fromfile(template_resource_path(template.template_path), dtype=np.uint8)
    original = cv2.imdecode(raw, cv2.IMREAD_COLOR)

    for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
        scale = width / profile.base_resolution[0]
        resized = cv2.resize(original, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x1, y1, _, _ = scale_region(
            template.base_region,
            profile.base_resolution,
            (width, height),
        )
        frame[y1 : y1 + resized.shape[0], x1 : x1 + resized.shape[1]] = resized
        decision = engine.evaluate_frame(profile, frame)
        assert decision is not None
        assert decision.template_id == template.id
        assert decision.score > 0.95


def test_runtime_template_self_check_unlocks_explicit_input() -> None:
    engine = AutoDialogEngine()
    verified, failures = engine.verify_bundled_templates()

    assert verified
    assert failures == []
    assert engine.regression_verified


def test_learned_scale_is_saved_per_resolution(tmp_path) -> None:
    engine = AutoDialogEngine(config_dir=tmp_path)
    profile = engine.profiles["genshin"]
    engine.learning_store.save(
        profile.key,
        (1920, 1080),
        {"dialog_triangle": {"scale": 0.75, "score": 0.91}},
    )

    restored = AutoDialogEngine(config_dir=tmp_path)
    assert restored.learning_store.get_scale(
        profile.key, (1920, 1080), "dialog_triangle"
    ) == pytest.approx(0.75)


def test_calibration_recovers_and_uses_template_scale(tmp_path) -> None:
    engine = AutoDialogEngine(config_dir=tmp_path)
    profile = engine.profiles["genshin"]
    template = profile.templates[0]
    raw = np.fromfile(template_resource_path(template.template_path), dtype=np.uint8)
    original = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    expected_scale = 0.75
    resized = cv2.resize(original, None, fx=expected_scale, fy=expected_scale)
    x1, y1, _, _ = scale_region(template.base_region, profile.base_resolution, (1920, 1080))
    frame[y1 : y1 + resized.shape[0], x1 : x1 + resized.shape[1]] = resized

    learned = engine.learn_from_frame(profile, frame)

    assert learned[template.id]["scale"] == pytest.approx(expected_scale, abs=0.03)
    assert engine.evaluate_frame(profile, frame).template_id == template.id
