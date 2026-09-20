import pytest

from eryou_assistant.core.features import FEATURES, FeatureState, feature_by_key


def test_feature_keys_are_unique() -> None:
    keys = [feature.key for feature in FEATURES]
    assert len(keys) == len(set(keys))


def test_all_recovered_features_are_ready() -> None:
    assert {feature.key for feature in FEATURES} == {
        "guide",
        "direction",
        "dialog",
        "vision",
        "settings",
    }
    assert all(feature.state is FeatureState.READY for feature in FEATURES)


def test_unknown_feature_raises_key_error() -> None:
    with pytest.raises(KeyError):
        feature_by_key("missing")
