from __future__ import annotations

from beddington.soothe_memory import best_preset


def test_best_preset_returns_default_without_data() -> None:
    presets = {"rain": object(), "waves": object()}
    assert best_preset([], presets, min_samples=2, default="rain") == "rain"
    assert (
        best_preset([(1.0, "unknown", True)], presets, min_samples=1, default="rain")
        == "rain"
    )


def test_best_preset_explores_least_tried_preset() -> None:
    presets = {"rain": object(), "pink-noise": object(), "waves": object()}
    outcomes = [
        (1.0, "rain", True),
        (2.0, "rain", True),
        (3.0, "rain", False),
        (4.0, "pink-noise", True),
        (5.0, "pink-noise", False),
    ]
    assert best_preset(outcomes, presets, min_samples=3, default="rain") == "waves"


def test_best_preset_exploration_ties_by_name() -> None:
    presets = {"rain": object(), "bells": object(), "waves": object()}
    outcomes = [
        (1.0, "rain", True),
        (2.0, "rain", True),
        (3.0, "rain", False),
    ]
    assert best_preset(outcomes, presets, min_samples=3, default="rain") == "bells"


def test_best_preset_chooses_highest_success_rate_then_name() -> None:
    presets = {"alpha": object(), "beta": object(), "gamma": object()}
    outcomes = [
        (1.0, "alpha", True),
        (2.0, "alpha", False),
        (3.0, "beta", True),
        (4.0, "beta", True),
        (5.0, "gamma", True),
        (6.0, "gamma", True),
        (7.0, "unknown", True),
    ]
    assert best_preset(outcomes, presets, min_samples=2, default="alpha") == "beta"


def test_best_preset_returns_default_without_presets() -> None:
    assert best_preset([(1.0, "rain", True)], {}, min_samples=1, default="rain") == "rain"
