from pathlib import Path

import pytest

from lullaby.config import load_config


def test_load_config_reads_detection_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[detection]
threshold = 0.4
sustained_seconds = 2.0
release_seconds = 0.5
notification_cooldown_seconds = 20

[notifications]
desktop = false
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.detection.threshold == 0.4
    assert config.detection.sustained_seconds == 2.0
    assert config.notifications.desktop is False


def test_invalid_threshold_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[detection]\nthreshold = 1.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="between 0 and 1"):
        load_config(path)
