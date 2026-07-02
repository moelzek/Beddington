from __future__ import annotations

import json
import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from beddington.cli import (
    _AutoSootheWatcher,
    _DashboardSoothe,
    _SensorSampler,
    _build_soothe_presets,
    _duck_dashboard_soothe,
    _format_sensor_line,
    _is_degenerate,
    _maybe_play_wake_chime,
    _record_run_soothe_outcomes,
    _record_soothe_outcomes,
    _resume_dashboard_soothe,
    _resolve_live_view_token,
    _soothe_command_replaces_playback,
    _soothe_via_dashboard,
    main,
)
from beddington.config import (
    AppConfig,
    AssistantConfig,
    SootheConfig,
    SootheLearnConfig,
    SootheStepConfig,
)
from beddington.logging import OutputPaths
from beddington.models import Event, NightReport
from beddington.sensor_store import SensorStore
from beddington.soothe_memory import best_preset
from beddington.video import ImageInfo, VisualChangeReport


def test_format_sensor_line_combines_all_sensors() -> None:
    line = _format_sensor_line(
        {
            "room_temperature_c": 25.2,
            "room_humidity_pct": 50.0,
            "room_pressure_hpa": 1013.0,
            "room_gas_resistance_ohms": 123456,
            "person_present": True,
            "motion_detected": False,
            "room_illuminance_lx": 31.9,
            "target_distance_cm": 57.4,
            "target_count": 2,
            "radar_respiratory_rate": 18.0,
            "radar_heart_rate_bpm": 87.0,
        }
    )
    assert "25.2 C" in line
    assert "50% RH" in line
    assert "1013 hPa" in line
    assert "123 kohm gas" in line
    assert "present" in line
    assert "still" in line
    assert "31.9 lux" in line
    assert "87 bpm heart" in line
    assert "scene: settled near the cot" in line


def test_format_sensor_line_empty() -> None:
    assert _format_sensor_line({}) == "no readings yet"


@pytest.mark.parametrize("kind", ("soothe_quiet_confirmed", "soothe_settled"))
def test_record_run_soothe_outcomes_writes_success(
    tmp_path: Path,
    kind: str,
) -> None:
    attempted = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)
    resolved = datetime(2026, 6, 29, 20, 1, tzinfo=UTC)
    db_path = tmp_path / "s.db"

    _record_run_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=attempted,
                offset_seconds=10.0,
                details={"name": "rain"},
            ),
            Event(kind=kind, occurred_at=resolved, offset_seconds=70.0),
        ),
        str(db_path),
    )

    store = SensorStore(str(db_path))
    assert store.outcomes_since(0.0) == [(resolved.timestamp(), "rain", True)]
    store.close()


def test_record_run_soothe_outcomes_writes_failure(tmp_path: Path) -> None:
    attempted = datetime(2026, 6, 29, 21, 0, tzinfo=UTC)
    resolved = datetime(2026, 6, 29, 21, 2, tzinfo=UTC)
    db_path = tmp_path / "s.db"

    _record_run_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=attempted,
                offset_seconds=10.0,
                details={"name": "pink-noise"},
            ),
            Event(kind="soothe_unresolved", occurred_at=resolved, offset_seconds=130.0),
        ),
        str(db_path),
    )

    store = SensorStore(str(db_path))
    assert store.outcomes_since(0.0) == [(resolved.timestamp(), "pink-noise", False)]
    store.close()


def test_record_soothe_outcomes_maps_display_name_to_preset_key_for_selection(
    tmp_path: Path,
) -> None:
    started = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)
    presets = {"white_noise": SootheStepConfig(name="white noise")}
    store = SensorStore(str(tmp_path / "s.db"))

    _record_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=started,
                offset_seconds=0.0,
                details={"name": "white noise"},
            ),
            Event(
                kind="soothe_quiet_confirmed",
                occurred_at=started + timedelta(seconds=60),
                offset_seconds=60.0,
            ),
            Event(
                kind="soothe_attempted",
                occurred_at=started + timedelta(seconds=120),
                offset_seconds=120.0,
                details={"name": "white noise"},
            ),
            Event(
                kind="soothe_settled",
                occurred_at=started + timedelta(seconds=180),
                offset_seconds=180.0,
            ),
        ),
        store,
        presets,
    )

    outcomes = store.outcomes_since(0.0)
    assert outcomes == [
        ((started + timedelta(seconds=60)).timestamp(), "white_noise", True),
        ((started + timedelta(seconds=180)).timestamp(), "white_noise", True),
    ]
    assert best_preset(outcomes, presets, min_samples=2, default="rain") == "white_noise"
    store.close()


def test_record_soothe_outcomes_uses_switched_preset_key(tmp_path: Path) -> None:
    started = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)
    presets = {
        "rain": SootheStepConfig(name="rain"),
        "waves": SootheStepConfig(name="waves"),
    }
    store = SensorStore(str(tmp_path / "s.db"))

    _record_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=started,
                offset_seconds=0.0,
                details={"name": "rain"},
            ),
            Event(
                kind="soothe_switched",
                occurred_at=started + timedelta(seconds=300),
                offset_seconds=300.0,
                details={"from": "rain", "to": "waves"},
            ),
            Event(
                kind="soothe_settled",
                occurred_at=started + timedelta(seconds=360),
                offset_seconds=360.0,
            ),
        ),
        store,
        presets,
    )

    assert store.outcomes_since(0.0) == [
        ((started + timedelta(seconds=360)).timestamp(), "waves", True)
    ]
    store.close()


def _auto_soothe_config(learn_enabled: bool, min_samples: int) -> SimpleNamespace:
    return SimpleNamespace(
        detection=SimpleNamespace(threshold=0.25),
        soothe=SimpleNamespace(
            preset="rain",
            presets={
                "rain": SootheStepConfig(name="rain"),
                "waves": SootheStepConfig(name="waves"),
            },
            learn=SimpleNamespace(enabled=learn_enabled, min_samples=min_samples),
        )
    )


def _trigger_auto_soothe(watcher: _AutoSootheWatcher) -> str | None:
    watcher._state = {"enabled": True, "preset": "rain"}
    watcher._last_state = 10.0
    watcher._watcher = SimpleNamespace(observe=lambda _elapsed, _audio: True)
    return watcher.feed(np.zeros(15_600, dtype=np.float32), 10.0)


def _patch_auto_soothe_memory(
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    monkeypatch.setattr("beddington.cli._DEFAULT_HISTORY_DB", str(db_path))
    monkeypatch.setattr(
        "beddington.cli._build_soothe_presets",
        lambda config: config.soothe.presets,
    )


def test_wake_chime_plays_when_wake_question_detected() -> None:
    played: list[Path] = []

    result = _maybe_play_wake_chime(
        "what is the temperature",
        AppConfig(assistant=AssistantConfig(chime_enabled=True)),
        player=lambda path: played.append(path) or {"played": True},
    )

    assert result == {"played": True}
    assert [path.name for path in played] == ["chime.wav"]


def test_wake_chime_honours_disabled_config() -> None:
    played: list[Path] = []

    result = _maybe_play_wake_chime(
        "what is the temperature",
        AppConfig(assistant=AssistantConfig(chime_enabled=False)),
        player=lambda path: played.append(path) or {"played": True},
    )

    assert result == {"played": False, "reason": "disabled"}
    assert played == []


def test_wake_chime_suppressed_for_followup_after_bare_wake() -> None:
    played: list[Path] = []

    result = _maybe_play_wake_chime(
        "stop",
        AppConfig(assistant=AssistantConfig(chime_enabled=True)),
        player=lambda path: played.append(path) or {"played": True},
        already_acknowledged=True,
    )

    assert result == {"played": False, "reason": "already_acknowledged"}
    assert played == []


def test_bundled_chime_is_not_a_soothe_preset() -> None:
    presets = _build_soothe_presets(AppConfig())

    assert "chime" not in presets
    assert "white_noise" in presets
    assert "drums" in presets


def test_dashboard_soothe_presets_include_catalog_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "beddington.soothe.SubprocessSoothePlayer",
        _FakeDashboardPlayer,
    )
    dashboard = _DashboardSoothe(_build_soothe_presets(AppConfig()), "white_noise")
    presets = {preset["key"]: preset for preset in dashboard.presets()}

    assert presets["white_noise"]["label"] == "White"
    assert presets["white_noise"]["category"] == "sounds"
    assert presets["drums"]["label"] == "Drums"
    assert presets["drums"]["category"] == "music"
    assert presets["uterine_whoosh"]["avoid"] == "safety or medical framing"


class _FakeDashboardPlayer:
    instances: list["_FakeDashboardPlayer"] = []

    def __init__(self) -> None:
        self.played_steps: list[SootheStepConfig] = []
        self.stop_calls = 0
        self.instances.append(self)

    def play(self, step: SootheStepConfig) -> dict[str, object]:
        self.played_steps.append(step)
        return {"played": True}

    def stop_all(self) -> None:
        self.stop_calls += 1


def test_resolve_live_view_token_rejects_weak_explicit_token() -> None:
    assert _resolve_live_view_token("abc_DEF-12345") == "abc_DEF-12345"
    with pytest.raises(SystemExit, match="12 URL-safe"):
        _resolve_live_view_token("x")
    with pytest.raises(SystemExit, match="12 URL-safe"):
        _resolve_live_view_token("not safe enough")


def test_sensor_sampler_stop_closes_store() -> None:
    class Store:
        closed = False

        def close(self) -> None:
            self.closed = True

    store = Store()
    sampler = _SensorSampler([], 1.0, store=store)

    sampler.stop()

    assert store.closed is True


def test_voice_stop_command_stops_dashboard_soothe_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from beddington.assistant import match_soothe_command

    _FakeDashboardPlayer.instances = []
    monkeypatch.setattr(
        "beddington.soothe.SubprocessSoothePlayer",
        _FakeDashboardPlayer,
    )
    dashboard = _DashboardSoothe(
        {"white_noise": SootheStepConfig(name="white noise")},
        "white_noise",
    )
    dashboard.play("white_noise")

    command = match_soothe_command("stop")
    assert command == {"action": "stop"}
    assert dashboard.playing() == "white_noise"
    stopped = dashboard.stop() if command["action"] == "stop" else {}
    safe_stop = dashboard.stop()

    assert stopped == {"ok": True, "playing": None, "context": ""}
    assert safe_stop == {"ok": True, "playing": None, "context": ""}
    assert dashboard.playing() is None
    assert _FakeDashboardPlayer.instances[0].stop_calls == 2


def test_voice_stop_music_wake_phrase_is_fast_stop_command() -> None:
    from beddington.assistant import match_soothe_command
    from beddington.ears import extract_wake_question

    question = extract_wake_question("Hi Beddington, stop music")

    assert question == "stop music"
    assert match_soothe_command(question) == {"action": "stop"}
    assert _soothe_command_replaces_playback({"action": "stop"})


def test_repeated_wake_word_transcript_is_degenerate() -> None:
    text = " ".join(["Hi Paddington"] * 20)

    assert _is_degenerate(text)


def test_duck_and_resume_dashboard_soothe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object] | None, str]] = []

    def fake_live_view_json(
        path: str,
        token: str,
        port: int,
        params: dict[str, object] | None = None,
        method: str = "GET",
    ) -> dict[str, object]:
        del token, port
        calls.append((path, params, method))
        if path == "/soothe.json":
            return {"playing": "piano", "context": "sleep"}
        if params and params.get("action") == "stop":
            return {"ok": True, "playing": None, "context": ""}
        if params and params.get("action") == "play":
            return {"ok": True, "playing": params["preset"], "context": params.get("context", "")}
        return {"ok": False}

    monkeypatch.setattr("beddington.cli._read_live_view_token", lambda: "token")
    monkeypatch.setattr("beddington.cli._live_view_json", fake_live_view_json)

    paused = _duck_dashboard_soothe()
    resumed = _resume_dashboard_soothe(paused)

    assert paused == {"preset": "piano", "context": "sleep"}
    assert resumed == {"ok": True, "playing": "piano", "context": "sleep"}
    assert calls == [
        ("/soothe.json", None, "GET"),
        ("/soothe", {"action": "stop"}, "POST"),
        ("/soothe", {"action": "play", "preset": "piano", "context": "sleep"}, "POST"),
    ]


def test_soothe_via_dashboard_next_uses_best_preset_excluding_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object] | None, str]] = []

    def fake_live_view_json(
        path: str,
        token: str,
        port: int,
        params: dict[str, object] | None = None,
        method: str = "GET",
    ) -> dict[str, object]:
        del token, port
        calls.append((path, params, method))
        if path == "/soothe.json":
            return {
                "presets": [
                    {"key": "white_noise", "label": "white noise"},
                    {"key": "rain", "label": "rain"},
                    {"key": "ocean_waves", "label": "ocean waves"},
                ],
                "playing": "rain",
                "default": "rain",
            }
        return {"ok": True, "playing": params["preset"] if params else None}

    monkeypatch.setattr("beddington.cli._read_live_view_token", lambda: "token")
    monkeypatch.setattr("beddington.cli._live_view_json", fake_live_view_json)
    monkeypatch.setattr(
        "beddington.cli._load_soothe_outcomes",
        lambda _db: [
            (1.0, "white_noise", False),
            (2.0, "ocean_waves", True),
            (3.0, "ocean_waves", True),
            (4.0, "rain", True),
        ],
    )
    config = AppConfig(
        soothe=SootheConfig(
            preset="white_noise",
            learn=SootheLearnConfig(enabled=True, min_samples=1),
        )
    )

    assert _soothe_via_dashboard({"action": "next"}, config=config) == (
        "Playing ocean waves."
    )
    assert calls[-1] == (
        "/soothe",
        {"action": "play", "preset": "ocean_waves"},
        "POST",
    )


def test_soothe_via_dashboard_play_best_uses_context_specific_music(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object] | None, str]] = []

    def fake_live_view_json(
        path: str,
        token: str,
        port: int,
        params: dict[str, object] | None = None,
        method: str = "GET",
    ) -> dict[str, object]:
        del token, port
        calls.append((path, params, method))
        if path == "/soothe.json":
            return {
                "presets": [
                    {"key": "dreams", "label": "Dreams", "category": "music"},
                    {"key": "piano", "label": "Piano", "category": "music"},
                    {"key": "white_noise", "label": "White", "category": "sounds"},
                ],
                "playing": None,
                "default": "dreams",
            }
        return {"ok": True, "playing": params["preset"] if params else None}

    def fake_outcomes(_db: str, context: str | None = None) -> list[tuple[float, str, bool]]:
        assert context == "sleep"
        return [
            (1.0, "dreams", False),
            (2.0, "piano", True),
            (3.0, "piano", True),
        ]

    monkeypatch.setattr("beddington.cli._read_live_view_token", lambda: "token")
    monkeypatch.setattr("beddington.cli._live_view_json", fake_live_view_json)
    monkeypatch.setattr("beddington.cli._load_soothe_outcomes", fake_outcomes)
    config = AppConfig(
        soothe=SootheConfig(
            preset="dreams",
            learn=SootheLearnConfig(enabled=True, min_samples=1),
        )
    )

    assert _soothe_via_dashboard(
        {"action": "play_best", "category": "music", "context": "sleep"},
        config=config,
    ) == "Playing piano for sleep."
    assert calls[-1] == (
        "/soothe",
        {"action": "play", "preset": "piano", "context": "sleep"},
        "POST",
    )


def test_soothe_via_dashboard_feedback_records_current_context(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"

    def fake_live_view_json(
        path: str,
        token: str,
        port: int,
        params: dict[str, object] | None = None,
        method: str = "GET",
    ) -> dict[str, object]:
        del token, port, params, method
        assert path == "/soothe.json"
        return {"playing": "piano", "context": "feeding"}

    monkeypatch.setattr("beddington.cli._DEFAULT_HISTORY_DB", str(db_path))
    monkeypatch.setattr("beddington.cli._read_live_view_token", lambda: "token")
    monkeypatch.setattr("beddington.cli._live_view_json", fake_live_view_json)
    monkeypatch.setattr("beddington.cli.time.time", lambda: 123.0)

    assert _soothe_via_dashboard({"action": "feedback", "success": True}) == (
        "Noted, I'll remember that piano helped for feeding."
    )

    store = SensorStore(str(db_path))
    assert store.outcomes_since_context(0.0, "feeding") == [(123.0, "piano", True)]
    store.close()


def test_soothe_via_dashboard_volume_uses_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directions: list[str] = []

    def fake_adjust(direction: str) -> dict[str, object]:
        directions.append(direction)
        return {"ok": True}

    monkeypatch.setattr("beddington.cli._adjust_playback_volume", fake_adjust)

    assert _soothe_via_dashboard({"action": "volume", "dir": "up"}) == (
        "Okay, a little louder."
    )
    assert directions == ["up"]


def test_soothe_via_dashboard_autosoothe_writes_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[bool, str]] = []
    monkeypatch.setattr(
        "beddington.autosoothe.read_state",
        lambda: {"enabled": False, "preset": "rain"},
    )
    monkeypatch.setattr(
        "beddington.autosoothe.write_state",
        lambda enabled, preset: writes.append((enabled, preset))
        or {"enabled": enabled, "preset": preset},
    )
    config = AppConfig(
        soothe=SootheConfig(
            preset="rain",
            presets={"rain": SootheStepConfig(name="rain")},
        )
    )

    assert _soothe_via_dashboard(
        {"action": "autosoothe", "enabled": True}, config=config
    ) == "Okay, I'll start watching for crying."
    assert _soothe_via_dashboard(
        {"action": "autosoothe", "enabled": False}, config=config
    ) == "Okay, I'll stop watching for crying."
    assert writes == [(True, "rain"), (False, "rain")]


def test_auto_soothe_watcher_uses_best_preset_when_learning_has_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "rain", True)
    store.append_soothe_outcome(2.0, "rain", False)
    store.append_soothe_outcome(3.0, "waves", True)
    store.append_soothe_outcome(4.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(True, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "waves"


def test_auto_soothe_watcher_keeps_configured_preset_when_learning_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "rain", False)
    store.append_soothe_outcome(2.0, "rain", False)
    store.append_soothe_outcome(3.0, "waves", True)
    store.append_soothe_outcome(4.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(False, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "rain"


def test_auto_soothe_watcher_keeps_configured_preset_with_sparse_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(True, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "rain"


def test_auto_soothe_watcher_debug_prints_yamnet_score(
    capsys: pytest.CaptureFixture[str],
) -> None:
    watcher = _AutoSootheWatcher(
        _auto_soothe_config(False, 2),
        16_000,
        frame_ms=1000,
        debug=True,
    )
    watcher._state = {"enabled": True, "preset": "rain"}
    watcher._last_state = 10.0
    watcher._watcher = SimpleNamespace(
        last_score=0.72,
        observe=lambda _elapsed, _audio: True,
    )

    assert watcher.feed(np.zeros(15_600, dtype=np.float32), 10.0) == "rain"

    output = capsys.readouterr().out
    assert "YAMNet cry score=0.720" in output
    assert "threshold=0.250" in output
    assert "trigger=True" in output


def test_auto_soothe_watcher_backs_off_after_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watcher = _AutoSootheWatcher(
        _auto_soothe_config(False, 2),
        16_000,
        frame_ms=1000,
    )
    now = [10.0]

    def fail_build() -> object:
        raise RuntimeError("model missing")

    class FakeThread:
        def __init__(self, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            started.append(self.target)

    started: list[object] = []
    monkeypatch.setattr("beddington.cli.time.monotonic", lambda: now[0])
    monkeypatch.setattr(watcher, "_build", fail_build)

    watcher._do_build()

    assert watcher._build_failures == 1
    assert watcher._build_retry_until == 40.0

    monkeypatch.setattr("beddington.cli.threading.Thread", FakeThread)
    watcher._ensure_building(20.0)
    assert started == []

    watcher._ensure_building(40.1)
    assert len(started) == 1


def test_preview_soothe_dry_run_uses_selected_preset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--config",
            "config/default.toml",
            "preview-soothe",
            "--dry-run",
            "--seconds",
            "0.1",
        ]
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "Preset: white_noise (White)" in output
    assert "Dry run: dry_run" in output


def test_preview_soothe_rejects_non_positive_seconds() -> None:
    with pytest.raises(SystemExit, match="--seconds must be positive"):
        main(
            [
                "--config",
                "config/default.toml",
                "preview-soothe",
                "--dry-run",
                "--seconds",
                "0",
            ]
        )


def test_preview_soothe_rejects_unknown_preset() -> None:
    with pytest.raises(SystemExit, match="Unknown soothe preset"):
        main(
            [
                "--config",
                "config/default.toml",
                "preview-soothe",
                "--dry-run",
                "--preset",
                "thunderstorm",
            ]
        )


def test_analyze_passes_configured_sensor_readers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[sensors]
sample_interval_seconds = 2.0

[sensors.motion]
enabled = true
gpio_pin = 4
""",
        encoding="utf-8",
    )
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"RIFF")
    readers = [object()]
    captured = {}

    def fake_build_sensor_readers(sensors_config):
        assert sensors_config.motion.enabled is True
        assert sensors_config.motion.gpio_pin == 4
        return readers

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        started = datetime(2026, 6, 28, tzinfo=UTC)
        report = NightReport(
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            source="fake.wav",
            detector="fake",
            threshold=0.4,
            sustained_seconds=1.5,
            windows_processed=0,
            peak_score=0.0,
            events=(),
        )
        return SimpleNamespace(
            report=report,
            digest="digest",
            paths=OutputPaths(
                events_json=tmp_path / "events.json",
                readable_log=tmp_path / "night-log.txt",
                digest=tmp_path / "morning-digest.txt",
            ),
        )

    monkeypatch.setattr("beddington.cli.YamNetTFLiteDetector", lambda model: object())
    monkeypatch.setattr("beddington.cli.WavFileAudioSource", lambda path: object())
    monkeypatch.setattr("beddington.cli.build_sensor_readers", fake_build_sensor_readers)
    monkeypatch.setattr("beddington.cli.run_pipeline", fake_run_pipeline)

    result = main(
        [
            "--config",
            str(config_path),
            "analyze",
            str(wav_path),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    assert result == 0
    assert captured["sensor_readers"] is readers
    assert captured["config"].sensors.sample_interval_seconds == 2.0
    assert "digest" in capsys.readouterr().out


def test_analyze_records_soothe_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"RIFF")
    history_db = tmp_path / "history.db"

    def fake_run_pipeline(**kwargs):
        started = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)
        resolved = started + timedelta(seconds=90)
        report = NightReport(
            started_at=started,
            finished_at=resolved,
            source="fake.wav",
            detector="fake",
            threshold=0.4,
            sustained_seconds=1.5,
            windows_processed=0,
            peak_score=0.0,
            events=(
                Event(
                    kind="soothe_attempted",
                    occurred_at=started,
                    offset_seconds=0.0,
                    details={"name": "rain"},
                ),
                Event(
                    kind="soothe_unresolved",
                    occurred_at=resolved,
                    offset_seconds=90.0,
                ),
            ),
        )
        return SimpleNamespace(
            report=report,
            digest="digest",
            paths=OutputPaths(
                events_json=tmp_path / "events.json",
                readable_log=tmp_path / "night-log.txt",
                digest=tmp_path / "morning-digest.txt",
            ),
        )

    monkeypatch.setattr("beddington.cli.YamNetTFLiteDetector", lambda model: object())
    monkeypatch.setattr("beddington.cli.WavFileAudioSource", lambda path: object())
    monkeypatch.setattr("beddington.cli.build_sensor_readers", lambda config: ())
    monkeypatch.setattr("beddington.cli.run_pipeline", fake_run_pipeline)

    result = main(
        [
            "--config",
            str(config_path),
            "analyze",
            str(wav_path),
            "--history-db",
            str(history_db),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    store = SensorStore(str(history_db))
    assert result == 0
    assert store.outcomes_since(0.0) == [
        (datetime(2026, 6, 29, 22, 1, 30, tzinfo=UTC).timestamp(), "rain", False)
    ]
    store.close()


def test_camera_smoke_image_mode_writes_derived_report(tmp_path, capsys) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 123, 45)
    )
    output_dir = tmp_path / "camera-output"

    result = main(
        [
            "--config",
            "config/default.toml",
            "camera-smoke",
            "--image",
            str(image),
            "--output",
            str(output_dir),
        ]
    )

    output = capsys.readouterr().out
    report = json.loads((output_dir / "camera-smoke.json").read_text(encoding="utf-8"))

    assert result == 0
    assert "Camera smoke source: image-file" in output
    assert "Image metadata: PNG 123x45" in output
    assert report["image"]["width"] == 123
    assert report["image"]["height"] == 45
    assert "Raw camera frames stay local" in report["privacy_note"]


def test_camera_smoke_rejects_invalid_dimensions() -> None:
    with pytest.raises(SystemExit, match="--width and --height must be positive"):
        main(
            [
                "--config",
                "config/default.toml",
                "camera-smoke",
                "--width",
                "0",
            ]
        )


def test_visual_change_writes_derived_report(tmp_path, capsys) -> None:
    before = tmp_path / "before.pgm"
    after = tmp_path / "after.pgm"
    before.write_bytes(b"P5\n2 2\n255\n" + bytes([0, 0, 0, 0]))
    after.write_bytes(b"P5\n2 2\n255\n" + bytes([255, 0, 255, 0]))
    output_dir = tmp_path / "visual-output"

    result = main(
        [
            "--config",
            "config/default.toml",
            "visual-change",
            "--before",
            str(before),
            "--after",
            str(after),
            "--output",
            str(output_dir),
            "--pixel-threshold",
            "0.5",
            "--changed-ratio-threshold",
            "0.25",
        ]
    )

    output = capsys.readouterr().out
    report = json.loads((output_dir / "visual-change.json").read_text(encoding="utf-8"))

    assert result == 0
    assert "Observation: visual_change_detected" in output
    assert report["changed_pixel_ratio"] == 0.5
    assert report["observation"] == "visual_change_detected"
    assert "not a safety" in report["wording_note"]


def test_camera_change_writes_derived_report(tmp_path, capsys, monkeypatch) -> None:
    def fake_capture(output_dir, **kwargs):
        assert output_dir == tmp_path / "camera-change-output"
        assert kwargs["keep_frames"] is False
        return VisualChangeReport(
            analysed_at=datetime(2026, 6, 23, tzinfo=UTC),
            before=ImageInfo("deleted temporary before frame", "BMP", 2, 1, 62),
            after=ImageInfo("deleted temporary after frame", "BMP", 2, 1, 62),
            mean_absolute_difference=0.5,
            changed_pixel_ratio=0.5,
            pixel_threshold=0.5,
            changed_ratio_threshold=0.25,
            observation="visual_change_detected",
            source="rpicam-still-pair",
            raw_frames_retained=False,
            camera_summary="0 : imx708 [4608x2592 10-bit RGGB]",
        )

    monkeypatch.setattr("beddington.cli.capture_rpicam_visual_change", fake_capture)

    result = main(
        [
            "--config",
            "config/default.toml",
            "camera-change",
            "--output",
            str(tmp_path / "camera-change-output"),
            "--pixel-threshold",
            "0.5",
            "--changed-ratio-threshold",
            "0.25",
        ]
    )

    output = capsys.readouterr().out
    report = json.loads(
        (tmp_path / "camera-change-output" / "visual-change.json").read_text(
            encoding="utf-8"
        )
    )

    assert result == 0
    assert "Observation: visual_change_detected" in output
    assert "Raw camera frames deleted" in output
    assert report["source"] == "rpicam-still-pair"
    assert report["raw_frames_retained"] is False
    assert report["before"]["path"] == "deleted temporary before frame"


def test_speech_bar_ignores_own_soothe_but_hears_louder_voice() -> None:
    """Part 3: while Beddington plays a sound, the leaked music must not read
    as speech, but a clearer/louder voice over it still opens an utterance."""
    from beddington.cli import _speech_bar, _update_self_audio_floor

    base = 0.024  # quiet-room threshold
    music_level = 0.09  # our own soothe leaking into the mic

    # With nothing playing, the bar is just the room threshold.
    assert _speech_bar(base, 0.0, soothe_playing=False) == base

    # Let the self-audio floor track up to the music over a second of frames.
    floor = 0.0
    for _ in range(40):
        floor = _update_self_audio_floor(
            floor, music_level, soothe_playing=True, in_utterance=False
        )
    bar = _speech_bar(base, floor, soothe_playing=True)

    # The music alone stays *below* the bar (no false wake) ...
    assert music_level < bar
    # ... but a distinctly louder voice over the music clears it.
    assert music_level * 2.0 > bar

    # Once the sound stops (or we start capturing), the floor decays back down
    # so the bar returns toward the room threshold.
    for _ in range(40):
        floor = _update_self_audio_floor(
            floor, music_level, soothe_playing=False, in_utterance=False
        )
    assert _speech_bar(base, floor, soothe_playing=True) < bar
    assert _speech_bar(base, floor, soothe_playing=False) == base


def test_auto_soothe_watcher_alerts_even_when_disabled() -> None:
    # Detection/alerting must run regardless of the auto-soothe toggle: with the
    # toggle OFF the watcher still fires on_cry (the parent alert) but plays no
    # soothe sound; with it ON it also returns a preset to play.
    from types import SimpleNamespace

    fired: list[float] = []
    watcher = _AutoSootheWatcher(
        _auto_soothe_config(False, 2), 16_000, frame_ms=1000,
        on_cry=lambda score: fired.append(score),
    )
    watcher._state = {"enabled": False, "preset": "rain"}
    watcher._last_state = 10.0
    watcher._watcher = SimpleNamespace(
        observe=lambda _elapsed, _audio: True, last_score=0.87
    )

    preset = watcher.feed(np.zeros(15_600, dtype=np.float32), 10.0)

    assert preset is None  # toggle off -> no auto-play
    assert fired == [0.87]  # but it DID alert the parent
