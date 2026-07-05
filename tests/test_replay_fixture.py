from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "replay_fixture_night.py"


def _load_replay_module():
    spec = importlib.util.spec_from_file_location("replay_fixture_night", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_builtin_replay_fixture_is_deterministic(tmp_path: Path) -> None:
    replay = _load_replay_module()
    fixture = tmp_path / "fixture.json"
    out_one = tmp_path / "one"
    out_two = tmp_path / "two"

    replay.generate_fixture(fixture)

    assert replay.replay_fixture(
        fixture,
        ROOT / "config" / "default.toml",
        out_one,
        check=True,
    ) == 0
    assert replay.replay_fixture(
        fixture,
        ROOT / "config" / "default.toml",
        out_two,
        check=True,
    ) == 0

    first = json.loads((out_one / "replay-events.json").read_text(encoding="utf-8"))
    second = json.loads((out_two / "replay-events.json").read_text(encoding="utf-8"))

    assert first == second
    episode_kinds = {
        event["kind"] for event in first["episodes"] if event["action"] == "start"
    }
    assert {
        "stirring",
        "caregiver_present",
        "room_warm",
        "sensor_unavailable",
    } <= episode_kinds
    assert first["transitions"]
