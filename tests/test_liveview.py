from __future__ import annotations

import io
import http.client
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from beddington.liveaudio import (
    TALK_MAX_BYTES,
    AudioClientTooSlow,
    TalkBusy,
    TalkPlaybackError,
    TalkResult,
)
from beddington.liveview import (
    _SOI,
    _AlertState,
    _HEADER_READ_TIMEOUT,
    FrameBroker,
    _DaemonThreadingHTTPServer,
    _ModeBroker,
    _STREAM_WRITE_TIMEOUT,
    _make_handler,
    build_viewer_html,
    history_series,
    is_authorised,
    iter_jpeg_frames,
    multipart_frame,
    rpicam_vid_command,
    serve_live_view,
)

JPEG_A = b"\xff\xd8" + b"AAAA" + b"\xff\xd9"
JPEG_B = b"\xff\xd8" + b"BBBBBB" + b"\xff\xd9"


def test_iter_jpeg_frames_splits_back_to_back() -> None:
    frames = list(iter_jpeg_frames([JPEG_A + JPEG_B]))
    assert frames == [JPEG_A, JPEG_B]


def test_iter_jpeg_frames_reassembles_across_chunks() -> None:
    # A frame split mid-way across two chunks must still emerge whole.
    chunks = [JPEG_A[:3], JPEG_A[3:] + JPEG_B[:2], JPEG_B[2:]]
    assert list(iter_jpeg_frames(chunks)) == [JPEG_A, JPEG_B]


def test_iter_jpeg_frames_drops_leading_junk() -> None:
    assert list(iter_jpeg_frames([b"garbage" + JPEG_A])) == [JPEG_A]


def test_iter_jpeg_frames_bounds_buffer_on_wedged_stream() -> None:
    # BUG B: a camera wedges mid-frame — one SOI then many MB with no EOI. The
    # partial must be dropped (buffer bounded, no OOM) and a later well-formed
    # frame must still come through once a real EOI arrives.
    import beddington.liveview as lv

    cap = lv._MAX_JPEG_BYTES

    def wedged_then_recovers():
        # One SOI, then a long run of non-EOI bytes streamed across many chunks,
        # well past the cap. Use 0x00 so no accidental FF D9 appears mid-run.
        yield _SOI
        chunk = b"\x00" * (256 * 1024)
        emitted = 0
        while emitted <= cap + 4 * len(chunk):
            yield chunk
            emitted += len(chunk)
        # Now the camera un-wedges: a fresh, well-formed frame.
        yield JPEG_B

    gen = iter_jpeg_frames(wedged_then_recovers())
    frames = list(gen)

    # The multi-MB partial was discarded; only the recovered frame is yielded.
    assert frames == [JPEG_B]


def test_iter_jpeg_frames_buffer_stays_bounded_across_chunks() -> None:
    # Assert the *peak* memory held by the splitter stays bounded while a wedged
    # stream pours in far more than the cap. We tap the buffer by measuring the
    # process's own generator: feed one chunk at a time and check that the total
    # bytes fed minus bytes the generator could plausibly hold never forces an
    # unbounded buffer — done here by tracking peak via ``tracemalloc``.
    import tracemalloc

    import beddington.liveview as lv

    cap = lv._MAX_JPEG_BYTES
    chunk = b"\x00" * (512 * 1024)

    def wedged():
        yield _SOI
        total = 0
        while total < cap * 4:
            yield chunk
            total += len(chunk)
        yield JPEG_A

    tracemalloc.start()
    frames = list(iter_jpeg_frames(wedged()))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert frames == [JPEG_A]
    # Peak allocation must stay near the cap, not near cap*4 (the wedged total).
    # Generous headroom (cap + a few chunks) still proves the buffer is bounded.
    assert peak < cap + 8 * len(chunk)


def test_iter_jpeg_frames_back_to_back_after_wedge_no_regression() -> None:
    # Well-formed back-to-back frames still split correctly (no regression from
    # the cap logic) — including immediately after a dropped wedge.
    assert list(iter_jpeg_frames([JPEG_A + JPEG_B])) == [JPEG_A, JPEG_B]

    def wedge_then_two():
        yield _SOI
        big = b"\x00" * (1024 * 1024)
        import beddington.liveview as lv

        sent = 0
        while sent <= lv._MAX_JPEG_BYTES + 2 * len(big):
            yield big
            sent += len(big)
        yield JPEG_A + JPEG_B

    assert list(iter_jpeg_frames(wedge_then_two())) == [JPEG_A, JPEG_B]


def test_multipart_frame_has_jpeg_headers() -> None:
    chunk = multipart_frame(JPEG_A)
    assert b"Content-Type: image/jpeg" in chunk
    assert b"Content-Length: " + str(len(JPEG_A)).encode() in chunk
    assert chunk.endswith(JPEG_A + b"\r\n")


def test_is_authorised() -> None:
    assert is_authorised("s3cret", "s3cret")
    assert not is_authorised("wrong", "s3cret")
    assert not is_authorised("", "s3cret")
    assert not is_authorised("anything", "")  # no token configured -> deny


def test_build_viewer_html_embeds_stream() -> None:
    html = build_viewer_html("/stream.mjpg?token=abc", "Cot cam")
    assert "/stream.mjpg?token=abc" in html
    assert "<img" in html
    assert "Cot cam" in html
    assert "readings.json" not in html  # no dashboard unless asked


def test_build_viewer_html_escapes_title_and_paths() -> None:
    html = build_viewer_html(
        '/stream.mjpg?token=abc" onerror="alert(1)',
        'Cot <script>alert("x")</script>',
        readings_path='/readings.json?token=abc"bad',
    )

    assert 'Cot &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;' in html
    assert 'token=abc&quot; onerror=&quot;alert(1)' in html
    assert 'const RP="/readings.json?token=abc\\"bad";' in html


def test_build_viewer_html_dashboard_overlay() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t", readings_path="/readings.json?token=t"
    )
    assert "/readings.json?token=t" in html
    assert 'class="panel"' in html
    assert "poll()" in html  # polling script present


def test_build_viewer_html_state_first_dashboard() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    assert "/history.json?token=t" in html
    assert "/snapshot.json?token=t" in html
    assert 'id="state-hero"' in html
    assert 'id="t2-alerts"' in html
    assert "renderT2Alerts" in html
    assert "BabyStateHero" in html
    assert 'id="action-panel"' in html
    assert 'id="sensor-cards"' in html
    assert 'id="motion-timeline"' not in html
    assert "Motion timeline" not in html
    assert 'id="engineering" class="engineering"' in html
    assert "fmtTime" in html  # engineering charts label the x axis
    assert "room_temperature_c" in html  # sensor spec embedded
    assert 'id="tabs"' in html  # video-first layout: telemetry behind tabs
    assert 'data-view="eng"' in html


def test_build_viewer_html_has_monitor_unreachable_copy() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )

    assert "Monitor unreachable — it may be offline. Live camera may still work." in html


def test_live_view_command_passes_liveview_state_thresholds_to_snapshot_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import beddington.cli as cli
    from beddington.config import AppConfig, LiveviewConfig
    from beddington.live_snapshot import SnapshotThresholds

    captured: dict[str, object] = {}
    thresholds = SnapshotThresholds(caregiver_dwell_s=1.25)

    class FakeEngine:
        def __init__(self, received_thresholds, process_start_ts=None):
            captured["thresholds"] = received_thresholds
            captured["process_start_ts"] = process_start_ts

        def build(self, **_kwargs):
            return {"schema_version": 1, "caregiver_dwell_s": captured["thresholds"].caregiver_dwell_s}

    class FakeSampler:
        def __init__(self, _readers, _interval, store=None):
            self.store = store

        def start(self) -> None:
            captured["sampler_started"] = True

        def stop(self) -> None:
            captured["sampler_stopped"] = True

        def latest(self) -> dict[str, object]:
            return {}

        def history(self) -> list[tuple[float, dict[str, object]]]:
            return []

        def mode(self) -> str:
            return "night"

        def override(self) -> None:
            return None

        def set_override(self, _mode: str | None) -> None:
            pass

        def set_frame_age(self, _age: float | None) -> None:
            pass

    def fake_serve_live_view(**kwargs):
        captured["snapshot"] = kwargs["snapshot_provider"]({"alerts": {"active": False}})

    monkeypatch.setattr("beddington.cli.build_sensor_readers", lambda _config: [object()])
    monkeypatch.setattr("beddington.cli._SensorSampler", FakeSampler)
    monkeypatch.setattr("beddington.cli._resolve_live_view_token", lambda _token: "token")
    monkeypatch.setattr("beddington.cli._lan_ip", lambda _bind: "127.0.0.1")
    monkeypatch.setattr("beddington.cli._build_soothe_presets", lambda _config: {})
    monkeypatch.setattr("beddington.cli.time.time", lambda: 1234.0)
    monkeypatch.setattr("beddington.live_snapshot.LiveSnapshotEngine", FakeEngine)
    monkeypatch.setattr("beddington.liveview.RpicamFrameSource", lambda _cmd: object())
    monkeypatch.setattr("beddington.liveview.serve_live_view", fake_serve_live_view)

    args = SimpleNamespace(
        port=8080,
        width=640,
        height=480,
        fps=15,
        token=None,
        no_sensors=False,
        no_history=True,
        sensor_interval=3.0,
        history_db=":memory:",
        history_hours=1.0,
        night_camera_num=None,
        camera_num=0,
        night=False,
        bind="127.0.0.1",
        rotate=0,
    )

    result = cli._live_view_command(
        args,
        AppConfig(liveview=LiveviewConfig(state=thresholds)),
    )

    assert result == 0
    assert captured["thresholds"] is thresholds
    assert captured["process_start_ts"] == 1234.0
    assert captured["snapshot"] == {"schema_version": 1, "caregiver_dwell_s": 1.25}
    assert captured["sampler_started"] is True
    assert captured["sampler_stopped"] is True


def test_build_viewer_html_rotate() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        rotate=90,
    )
    assert "ROTATE=90" in html
    assert 'img.rot90' in html  # rotation CSS present
    assert build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
    ).count("ROTATE=0")  # default no rotation


def test_build_viewer_html_has_tonight_card_when_digest() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
    )
    assert "/digest.json?token=t" in html
    assert 'id="tonight"' in html
    assert "I don't have enough history yet for a night summary." in html
    assert "loadDigest" in html


def test_build_viewer_html_has_exact_privacy_badge() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        alerts_path="/alerts.json?token=t",
    )

    assert "LAN only · no cloud · no recording · no audio streaming" in html
    assert "LAN only · no recording · no audio" not in html


def test_build_viewer_html_embeds_snapshot_path() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )

    assert "/snapshot.json?token=t" in html
    assert 'SNAPSHOT="/snapshot.json?token=t"' in html
    assert 'id="state-hero"' in html


def test_build_viewer_html_without_snapshot_omits_state_sections() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        alerts_path="/alerts.json?token=t",
    )

    assert 'id="state-hero"' not in html
    assert "BabyStateHero" not in html
    assert 'id="state-chip"' not in html
    assert 'id="health-dots"' not in html
    assert 'alt="Live camera view"' in html
    assert "/alerts.json?token=t" in html


def test_build_viewer_html_activity_slider_gated_by_snapshot() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    assert 'id="activity-slider"' in html
    assert '<span>Still</span><span>Moving</span>' in html
    assert "arousal_score" in html

    without_snapshot = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
    )
    assert 'id="activity-slider"' not in without_snapshot


def test_build_viewer_html_camera_chips_are_path_gated() -> None:
    snapshot_html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    assert 'id="camera-chip-room"' in snapshot_html
    assert 'id="camera-chip-caregiver"' not in snapshot_html

    events_html = build_viewer_html(
        "/stream.mjpg?token=t",
        events_path="/events.json?token=t",
    )
    assert "/events.json?token=t" in events_html
    assert 'id="camera-chip-caregiver"' in events_html
    assert "Caregiver seen " in events_html
    assert 'id="camera-chip-room"' not in events_html

    plain_html = build_viewer_html(
        "/stream.mjpg?token=t",
        history_path="/history.json?token=t",
    )
    assert 'id="camera-chips"' not in plain_html


def test_build_viewer_html_motion_donut_gated_by_history() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        history_path="/history.json?token=t",
    )
    assert 'id="motion-donut-card"' in html
    assert 'id="motion-donut"' in html
    assert "Motion · last" in html
    assert "Collecting readings..." in html
    assert 'id="motion-timeline"' not in html

    without_history = build_viewer_html(
        "/stream.mjpg?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    assert 'id="motion-donut-card"' not in without_history


def test_build_viewer_html_crying_card_gated_by_events() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        events_path="/events.json?token=t",
    )
    assert 'id="crying-card"' in html
    assert 'id="crying-count"' in html
    assert 'id="crying-list"' in html
    assert "Crying heard" in html
    assert "No crying heard in this window." in html

    without_events = build_viewer_html(
        "/stream.mjpg?token=t",
        history_path="/history.json?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    assert 'id="crying-card"' not in without_events


def test_build_viewer_html_new_dashboard_copy_avoids_banned_state_words() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
        snapshot_path="/snapshot.json?token=t",
        events_path="/events.json?token=t",
    )
    lower = html.lower()
    assert "peaceful" not in lower
    assert "asleep" not in lower
    assert "calm" not in lower


def test_build_viewer_html_debug_section_collapsed_with_sensor_charts() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
    )

    assert '<details id="engineering" class="engineering">' in html
    assert "<summary>Charts</summary>" in html
    assert '<canvas id="cv-room_temperature_c"></canvas>' in html
    assert '<button type="button" class="sensor-chip active"' in html
    assert '<details id="engineering" class="engineering" open>' not in html


def test_build_viewer_html_video_first_tab_bar() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
        soothe_path="/soothe?token=t",
        snapshot_path="/snapshot.json?token=t",
    )

    assert 'id="view-monitor"' in html
    assert 'id="view-tonight"' in html
    assert 'id="view-eng"' in html
    assert 'data-view="monitor">Monitor</button>' in html
    assert 'data-view="tonight">Tonight</button>' in html
    assert 'data-view="eng">More data</button>' in html
    assert 'id="sound-btn"' in html  # soothe lives behind the Sound sheet
    assert 'id="sound-sheet"' in html
    assert 'data-sensor="room_temperature_c"' in html

    # camera-only config keeps a bare monitor: no tab bar at all
    bare = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        alerts_path="/alerts.json?token=t",
    )
    assert 'id="tabs"' not in bare
    assert 'class="notabs"' in bare


def test_history_series_converts_bool_and_scale() -> None:
    hist = [
        (100.0, {"room_temperature_c": 21.0, "room_gas_resistance_ohms": 50000, "person_present": True}),
        (103.0, {"room_temperature_c": 22.0, "room_gas_resistance_ohms": 60000, "person_present": False}),
    ]
    series = history_series(hist)
    assert series["room_temperature_c"]["points"] == [[100.0, 21.0], [103.0, 22.0]]
    assert series["room_gas_resistance_ohms"]["points"] == [[100.0, 50.0], [103.0, 60.0]]
    assert series["person_present"]["points"] == [[100.0, 1.0], [103.0, 0.0]]
    assert series["person_present"]["bool"] is True


def test_history_series_skips_missing_values() -> None:
    series = history_series([(1.0, {}), (2.0, {"room_temperature_c": 20.0})])
    assert series["room_temperature_c"]["points"] == [[2.0, 20.0]]


def test_day_night_mode_hysteresis() -> None:
    from beddington.liveview import day_night_mode

    assert day_night_mode(2.0, "day") == "night"  # clearly dark
    assert day_night_mode(200.0, "night") == "day"  # clearly lit
    # in the dusk band the mode holds (no flapping)
    assert day_night_mode(20.0, "day") == "day"
    assert day_night_mode(20.0, "night") == "night"


def test_rpicam_vid_command_basic() -> None:
    cmd = rpicam_vid_command(camera=1, width=320, height=240, fps=10)
    assert cmd[0] == "rpicam-vid"
    assert "--camera" in cmd and cmd[cmd.index("--camera") + 1] == "1"
    assert "--codec" in cmd and cmd[cmd.index("--codec") + 1] == "mjpeg"
    assert cmd[cmd.index("--width") + 1] == "320"
    assert "--shutter" not in cmd  # day mode


def test_rpicam_vid_command_night_adds_low_light() -> None:
    cmd = rpicam_vid_command(night=True, fps=12)
    assert "--shutter" in cmd  # longer exposure
    assert "--gain" in cmd  # higher gain
    # Night runs at full frame rate; the shutter must fit the frame period.
    fps = int(cmd[cmd.index("--framerate") + 1])
    shutter_us = int(cmd[cmd.index("--shutter") + 1])
    assert fps == 12
    assert shutter_us <= 1_000_000 // fps


def test_frame_broker_delivers_and_closes() -> None:
    broker = FrameBroker()
    broker.publish(JPEG_A)
    seq, frame = broker.wait_for_frame(0, timeout=1.0)
    assert frame == JPEG_A and seq == 1
    broker.close()
    assert broker.closed
    _, frame = broker.wait_for_frame(seq, timeout=1.0)
    assert frame is None  # closed -> no frame


def test_frame_broker_timeout_returns_no_frame() -> None:
    broker = FrameBroker()

    seq, frame = broker.wait_for_frame(0, timeout=0.01)

    assert seq == 0
    assert frame is None


def test_mode_broker_switch_returns_new_broker_frame_promptly() -> None:
    # K5: day runs fast (high seq) and night runs slow (low seq). After a
    # day->night switch a viewer must NOT block until the night broker's seq
    # climbs past the stale day seq — it should get night's current frame at once.
    day = FrameBroker()
    night = FrameBroker()
    mode = {"value": "day"}
    broker = _ModeBroker({"day": day, "night": night}, lambda: mode["value"])

    # Day has streamed a lot (seq high); night has only a couple of frames.
    for _ in range(900):
        day.publish(JPEG_A)
    night.publish(JPEG_B)
    night.publish(JPEG_B)  # night seq == 2, far below day seq == 900

    cursor = broker.new_cursor()
    # Viewer reads day and reaches its high seq.
    seq, frame = broker.wait_for_frame(0, timeout=1.0, cursor=cursor)
    assert frame == JPEG_A
    day_seq = seq
    assert day_seq == 900

    # Switch to night. With the stale cross-broker seq (900) this would block
    # for minutes; the fix must return night's current frame immediately.
    mode["value"] = "night"
    seq, frame = broker.wait_for_frame(day_seq, timeout=0.2, cursor=cursor)
    assert frame == JPEG_B  # got the new broker's frame, not None/timeout
    assert seq == 2  # night's own seq, not the stale day seq

    # Subsequent reads follow night normally (block until a newer night frame).
    seq2, frame2 = broker.wait_for_frame(seq, timeout=0.05, cursor=cursor)
    assert frame2 is None  # no new night frame yet -> normal timeout
    assert seq2 == 2
    night.publish(JPEG_B)
    seq3, frame3 = broker.wait_for_frame(seq2, timeout=1.0, cursor=cursor)
    assert frame3 == JPEG_B and seq3 == 3


def test_mode_broker_single_mode_behaves_like_frame_broker() -> None:
    # No switch: _ModeBroker must behave exactly like the underlying broker.
    only = FrameBroker()
    broker = _ModeBroker({"day": only}, lambda: "day")
    cursor = broker.new_cursor()

    only.publish(JPEG_A)
    seq, frame = broker.wait_for_frame(0, timeout=1.0, cursor=cursor)
    assert frame == JPEG_A and seq == 1

    seq2, frame2 = broker.wait_for_frame(seq, timeout=0.02, cursor=cursor)
    assert frame2 is None and seq2 == 1  # nothing new -> timeout, seq unchanged


class _FakeFrameSource:
    def __init__(self, frames: list[bytes]) -> None:
        self._frames = frames
        self._stop = threading.Event()

    def frames(self):
        i = 0
        while not self._stop.is_set():
            yield self._frames[i % len(self._frames)]
            i += 1
            time.sleep(0.005)

    def close(self) -> None:
        self._stop.set()


class _FakeSoothe:
    def __init__(self) -> None:
        self._playing: str | None = None
        self._context = ""

    def presets(self) -> list[dict[str, str]]:
        return [
            {
                "key": "white_noise",
                "label": "White",
                "category": "sounds",
                "feel": "steady",
                "use": "masking",
                "avoid": "loud play",
            },
            {
                "key": "piano",
                "label": "Piano",
                "category": "music",
                "feel": "gentle",
                "use": "background",
                "avoid": "masking",
            },
        ]

    def default(self) -> str:
        return "white_noise"

    def autosoothe(self) -> dict[str, object]:
        return {"enabled": False, "preset": ""}

    def set_autosoothe(self, enabled: bool, preset: str) -> dict[str, object]:
        return {"enabled": enabled, "preset": preset}

    def playing(self) -> str | None:
        return self._playing

    def context(self) -> str:
        return self._context

    def play(self, name: str, context: str = "") -> dict[str, object]:
        self._playing = name
        self._context = context
        return {"ok": True, "playing": name, "context": context}

    def stop(self) -> dict[str, object]:
        self._playing = None
        self._context = ""
        return {"ok": True, "playing": None, "context": ""}


class _FakeAudioBroker:
    max_listeners = 2

    def __init__(self) -> None:
        self.listeners = 0

    def add_listener(self) -> None:
        self.listeners += 1

    def remove_listener(self) -> None:
        self.listeners -= 1

    def wait_for_block(self, seq: int, timeout: float = 2.0):
        del timeout
        if seq == 0:
            return 1, b"\x01\x00\x02\x00"
        raise AudioClientTooSlow("done")

    def close(self) -> None:
        return


class _FakeTalkPlayer:
    def __init__(self, *, playing: bool = False, exc: Exception | None = None) -> None:
        self._playing = playing
        self.exc = exc
        self.calls: list[tuple[bytes, str]] = []

    def playing(self) -> bool:
        return self._playing

    def play(self, data: bytes, content_type: str) -> TalkResult:
        self.calls.append((data, content_type))
        if self.exc is not None:
            raise self.exc
        return TalkResult(seconds=1.25)


class _FakeSocket:
    def __init__(self, request: bytes | object) -> None:
        self._request = request
        self.output = io.BytesIO()
        self.timeouts: list[float] = []

    def makefile(self, mode: str, _buffering: int | None = None):
        if "r" in mode:
            return self._request
        return self.output

    def sendall(self, data: bytes) -> None:
        self.output.write(data)

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class _TimeoutReader:
    def readline(self, _limit: int = -1) -> bytes:
        raise TimeoutError("timed out")

    def close(self) -> None:
        return


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_handler_server(
    handler: type,
) -> tuple[_DaemonThreadingHTTPServer, str]:
    httpd = _DaemonThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}"


def _handler_response(handler: type, request: bytes) -> bytes:
    sock = _FakeSocket(io.BytesIO(request))
    handler(sock, ("127.0.0.1", 12345), object())
    return sock.output.getvalue()


def _response_json(raw: bytes) -> object:
    return json.loads(raw.split(b"\r\n\r\n", 1)[1])


def _post_json(url: str, payload: object, token: str = "tk"):
    request = urllib.request.Request(
        f"{url}?token={token}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=2)


def _post_talk(
    base: str,
    token: str,
    data: bytes = b"clip",
    content_type: str = "audio/webm",
):
    request = urllib.request.Request(
        f"{base}/talk?token={token}",
        data=data,
        headers={"Content-Type": content_type},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=2)


def test_serve_live_view_requires_token_and_streams() -> None:
    source = _FakeFrameSource([JPEG_A, JPEG_B])
    token = "secret-token"
    port = _free_port()
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={"host": "127.0.0.1", "port": port, "token": token, "source": source},
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)  # let the server bind
    base = f"http://127.0.0.1:{port}"
    try:
        # No token -> 401
        try:
            urllib.request.urlopen(f"{base}/", timeout=2)
            raise AssertionError("expected 401 without token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        # Valid token -> the viewer page references the stream
        page = urllib.request.urlopen(f"{base}/?token={token}", timeout=2).read()
        assert b"stream.mjpg" in page

        # The stream serves multipart JPEG frames
        stream = urllib.request.urlopen(f"{base}/stream.mjpg?token={token}", timeout=2)
        data = stream.read(160)
        assert b"image/jpeg" in data
        stream.close()
    finally:
        source.close()


def test_handler_rejects_non_ascii_token_with_401() -> None:
    handler = _make_handler(FrameBroker(), "secret-token", "Cot cam")
    request = io.BytesIO(b"GET /?token=%C3%A9 HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)

    handler(sock, ("127.0.0.1", 12345), object())

    assert b" 401 " in sock.output.getvalue()


def test_handler_bounds_partial_header_read_with_timeout() -> None:
    handler = _make_handler(FrameBroker(), "secret-token", "Cot cam")
    sock = _FakeSocket(_TimeoutReader())

    handler(sock, ("127.0.0.1", 12345), object())

    assert sock.timeouts == [_HEADER_READ_TIMEOUT]


def test_closed_active_mode_broker_stream_ends_without_spinning() -> None:
    day = FrameBroker()
    night = FrameBroker()
    day.close()
    night.publish(JPEG_B)
    mode = {"value": "day"}
    broker = _ModeBroker({"day": day, "night": night}, lambda: mode["value"])
    handler = _make_handler(broker, "tk", "Cot cam")
    request = io.BytesIO(b"GET /stream.mjpg?token=tk HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)
    finished = threading.Event()

    def run_handler() -> None:
        handler(sock, ("127.0.0.1", 12345), object())
        finished.set()

    thread = threading.Thread(target=run_handler, daemon=True)
    thread.start()

    assert finished.wait(0.5)
    assert not thread.is_alive()
    assert sock.timeouts == [_HEADER_READ_TIMEOUT, _STREAM_WRITE_TIMEOUT]
    assert b"multipart/x-mixed-replace" in sock.output.getvalue()


def test_serve_live_view_serves_readings_when_provider_given() -> None:
    source = _FakeFrameSource([JPEG_A])
    token = "tok"
    port = _free_port()
    readings = {"temperature": "21°C · comfortable", "presence": "someone present"}
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "source": source,
            "readings_provider": lambda: readings,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        # readings require the token too
        try:
            urllib.request.urlopen(f"{base}/readings.json", timeout=2)
            raise AssertionError("expected 401 without token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        body = urllib.request.urlopen(f"{base}/readings.json?token={token}", timeout=2).read()
        assert json.loads(body)["temperature"] == "21°C · comfortable"

        # the viewer page now references the readings endpoint (dashboard mode)
        response = urllib.request.urlopen(f"{base}/?token={token}", timeout=2)
        page = response.read()
        assert b"readings.json" in page
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        source.close()


def test_serve_live_view_dual_camera_switches_on_mode() -> None:
    day = _FakeFrameSource([JPEG_A])
    night = _FakeFrameSource([JPEG_B])
    token = "tk"
    port = _free_port()
    mode = {"v": "day"}
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "sources": {"day": day, "night": night},
            "mode_getter": lambda: mode["v"],
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        stream = urllib.request.urlopen(f"{base}/stream.mjpg?token={token}", timeout=2)
        assert b"AAAA" in stream.read(120)  # day eye
        stream.close()
        mode["v"] = "night"
        time.sleep(0.2)
        stream2 = urllib.request.urlopen(f"{base}/stream.mjpg?token={token}", timeout=2)
        assert b"BBBBBB" in stream2.read(120)  # night eye
        stream2.close()
    finally:
        day.close()
        night.close()


def test_build_viewer_html_has_soothe_section() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        soothe_path="/soothe?token=t",
    )
    assert "Soothe" in html
    assert 'id="soothe" class="soothe-section"' in html
    assert "soothePost" in html
    assert "soothe-status" in html
    assert "setSootheStatus" in html
    assert "addCurrentSootheControl" in html
    assert "Cry trigger sound" in html
    assert "playing your voice" in html
    assert "Manual sounds" not in html  # manual preset grid removed from dashboard
    assert "addPresetGroups" not in html
    assert "/soothe?token=t" in html


def test_build_viewer_html_keeps_soothe_without_history() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        soothe_path="/soothe?token=t",
    )

    assert "Soothe" in html
    assert "soothe-status" in html
    assert 'id="engineering"' not in html
    assert "historyTick" in html
    assert "/soothe?token=t" in html


def test_dashboard_script_is_valid_javascript(tmp_path) -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
        soothe_path="/soothe?token=t",
        snapshot_path="/snapshot.json?token=t",
    )
    match = re.search(r"<script>(.*)</script>", html, re.S)
    assert match is not None
    script = tmp_path / "dashboard.js"
    script.write_text(match.group(1), encoding="utf-8")
    if shutil.which("node") is None:
        return

    subprocess.run(["node", "--check", str(script)], check=True)


def test_serve_live_view_soothe_play_and_stop() -> None:
    source = _FakeFrameSource([JPEG_A])
    token = "tk"
    port = _free_port()
    soothe = _FakeSoothe()
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "source": source,
            "soothe": soothe,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        state = json.loads(
            urllib.request.urlopen(f"{base}/soothe.json?token={token}", timeout=2).read()
        )
        assert any(p["key"] == "white_noise" for p in state["presets"])
        assert state["playing"] is None

        play = urllib.request.Request(
            f"{base}/soothe?token={token}&action=play&preset=white_noise", method="POST"
        )
        played = json.loads(urllib.request.urlopen(play, timeout=2).read())
        assert played["playing"] == "white_noise"
        assert played["autosoothe"] == {"enabled": False, "preset": ""}

        stop = urllib.request.Request(
            f"{base}/soothe?token={token}&action=stop", method="POST"
        )
        stopped = json.loads(urllib.request.urlopen(stop, timeout=2).read())
        assert stopped["playing"] is None
        assert stopped["autosoothe"] == {"enabled": False, "preset": ""}
    finally:
        source.close()


def test_serve_live_view_mode_override() -> None:
    source = _FakeFrameSource([JPEG_A])
    token = "tk"
    port = _free_port()
    forced = {"v": None}

    def setter(value: str | None) -> str:
        forced["v"] = value
        return value or "night"

    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "source": source,
            "mode_setter": setter,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        day = urllib.request.Request(f"{base}/mode?token={token}&set=day", method="POST")
        d = json.loads(urllib.request.urlopen(day, timeout=2).read())
        assert d["mode"] == "day" and d["mode_auto"] is False

        auto = urllib.request.Request(f"{base}/mode?token={token}&set=", method="POST")
        d2 = json.loads(urllib.request.urlopen(auto, timeout=2).read())
        assert d2["mode_auto"] is True
    finally:
        source.close()


def test_serve_live_view_serves_history_json() -> None:
    source = _FakeFrameSource([JPEG_A])
    token = "tk"
    port = _free_port()
    series = {
        "room_temperature_c": {
            "label": "Temp", "unit": "°C", "bool": False, "points": [[1.0, 21.0]]
        }
    }
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "source": source,
            "history_provider": lambda: series,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        body = urllib.request.urlopen(f"{base}/history.json?token={token}", timeout=2).read()
        assert json.loads(body)["room_temperature_c"]["points"] == [[1.0, 21.0]]
    finally:
        source.close()


def test_alert_state_raise_snapshot_and_clear() -> None:
    from beddington.liveview import _AlertState

    a = _AlertState()
    assert a.snapshot()["active"] is False
    first = a.raise_alert("Cry detected", "score 0.90", 0.9)
    assert first["ok"] is True and first["seq"] == 1
    snap = a.snapshot()
    assert snap["active"] is True
    assert snap["title"] == "Cry detected" and snap["seq"] == 1
    assert a.raise_alert("Cry detected", "again")["seq"] == 2  # seq increments
    a.clear()
    assert a.snapshot()["active"] is False


def test_alert_state_expires_after_ttl(monkeypatch) -> None:
    import beddington.liveview as lv

    clock = {"t": 100.0}
    monkeypatch.setattr(lv.time, "monotonic", lambda: clock["t"])
    a = lv._AlertState(ttl_seconds=30.0)
    a.raise_alert("Cry detected", "x")
    assert a.snapshot()["active"] is True
    clock["t"] = 100.0 + 31.0  # past the TTL — self-heals even without a clear
    assert a.snapshot()["active"] is False


def test_snapshot_json_requires_token() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        snapshot_provider=lambda _ctx: {"schema_version": 1},
    )
    request = io.BytesIO(b"GET /snapshot.json HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)

    handler(sock, ("127.0.0.1", 12345), object())

    assert b" 401 " in sock.output.getvalue()


def test_snapshot_json_serves_provider_with_alerts_and_frame_age() -> None:
    from beddington.liveview import _AlertState

    broker = FrameBroker()
    broker.publish(JPEG_A)
    alerts = _AlertState()
    alerts.raise_alert("Cry detected", "cry score 0.9", 0.9)
    seen: dict[str, object] = {}

    def provider(ctx: dict[str, object]) -> dict[str, object]:
        seen.update(ctx)
        return {
            "schema_version": 1,
            "alert_active": ctx["alerts"]["active"],
            "has_frame_age": isinstance(ctx["camera_frame_age_s"], float),
        }

    handler = _make_handler(
        broker,
        "tk",
        "Cot cam",
        alert_state=alerts,
        snapshot_provider=provider,
    )
    request = io.BytesIO(b"GET /snapshot.json?token=tk HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)

    handler(sock, ("127.0.0.1", 12345), object())

    raw = sock.output.getvalue()
    body = raw.split(b"\r\n\r\n", 1)[1]
    payload = json.loads(body)
    assert b" 200 " in raw
    assert payload == {"schema_version": 1, "alert_active": True, "has_frame_age": True}
    assert seen["alerts"]["active"] is True
    assert isinstance(seen["camera_frame_age_s"], float)


def test_snapshot_json_404_without_provider() -> None:
    handler = _make_handler(FrameBroker(), "tk", "Cot cam")
    request = io.BytesIO(b"GET /snapshot.json?token=tk HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)

    handler(sock, ("127.0.0.1", 12345), object())

    assert b" 404 " in sock.output.getvalue()


def test_handler_root_wires_snapshot_path_when_provider_configured() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        snapshot_provider=lambda _ctx: {"schema_version": 1},
    )
    request = io.BytesIO(b"GET /?token=tk HTTP/1.1\r\nHost: test\r\n\r\n")
    sock = _FakeSocket(request)

    handler(sock, ("127.0.0.1", 12345), object())

    raw = sock.output.getvalue()
    assert b" 200 " in raw
    assert b"/snapshot.json?token=tk" in raw


def test_dashboard_wires_alert_banner_and_poll_path() -> None:
    from beddington.liveview import build_viewer_html

    html = build_viewer_html(
        "/stream.mjpg?token=t",
        "Cot cam",
        readings_path="/readings.json?token=t",
        alerts_path="/alerts.json?token=t",
    )
    assert "/alerts.json?token=t" in html  # dashboard polls it
    assert "alertbanner" in html  # the banner element exists
    assert 'aria-live="assertive"' in html


def test_stream_server_uses_daemon_threads() -> None:
    # BUG A: daemon per-connection threads so a stuck stream handler can never
    # block interpreter shutdown / server_close.
    assert _DaemonThreadingHTTPServer.daemon_threads is True


def test_stream_viewer_cap_returns_503_when_full() -> None:
    # BUG A: with the viewer semaphore fully held, a new /stream.mjpg request
    # gets 503 instead of opening yet another unbounded stream.
    import beddington.liveview as lv

    source = _FakeFrameSource([JPEG_A, JPEG_B])
    token = "cap-token"
    port = _free_port()
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={"host": "127.0.0.1", "port": port, "token": token, "source": source},
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"

    # Drain every free viewer slot so the next request is over the cap. Restore
    # in finally so we never leak permits into other tests. (Acquire with a
    # short timeout in case a previous test's stream handler is mid-teardown and
    # about to release its slot.)
    held = 0
    try:
        deadline = time.monotonic() + 1.0
        while held < lv._MAX_STREAM_VIEWERS and time.monotonic() < deadline:
            if lv._STREAM_VIEWERS.acquire(timeout=0.05):
                held += 1
        assert held == lv._MAX_STREAM_VIEWERS  # all slots now drained

        try:
            urllib.request.urlopen(f"{base}/stream.mjpg?token={token}", timeout=2)
            raise AssertionError("expected 503 when viewer cap is exhausted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 503

        # Free one slot -> a viewer can connect again and gets JPEG frames.
        lv._STREAM_VIEWERS.release()
        held -= 1
        stream = urllib.request.urlopen(f"{base}/stream.mjpg?token={token}", timeout=2)
        assert b"image/jpeg" in stream.read(160)
        stream.close()
    finally:
        for _ in range(held):
            lv._STREAM_VIEWERS.release()
        source.close()


def test_iter_jpeg_frames_resyncs_on_cap_crossed_chunk_with_recovered_frame() -> None:
    # Codex #B: a chunk that crosses the cap AND already contains a complete
    # recovered JPEG must NOT be yielded as one giant corrupt frame (from a junk
    # SOI to the recovered frame's EOI) — the splitter must resync to the real
    # frame. (The no-EOI cap branch never fires here because an EOI IS present.)
    import beddington.liveview as lv

    cap = lv._MAX_JPEG_BYTES
    chunks = [
        _SOI,                        # a junk "frame" starts
        b"\x00" * (cap - 1024),      # stays just under the cap, still no EOI
        b"\x00" * 4096 + JPEG_A,     # this chunk crosses the cap AND holds a real frame
    ]
    assert list(iter_jpeg_frames(chunks)) == [JPEG_A]


def test_serve_live_view_serves_events_json_and_broker_sink() -> None:
    source = _FakeFrameSource([JPEG_A])
    token = "tk"
    port = _free_port()
    timeline = [
        {"kind": "crying", "started_ts": 1.0, "ended_ts": 61.0, "detail": ""}
    ]
    sunk: list[object] = []
    alert_states: list[object] = []
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "source": source,
            "events_provider": lambda: {"window_hours": 12, "events": timeline},
            "broker_sink": sunk.append,
            "alert_state_sink": alert_states.append,
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        body = urllib.request.urlopen(
            f"{base}/events.json?token={token}", timeout=2
        ).read()
        payload = json.loads(body)
        assert payload["events"] == timeline
        # The broker was handed to the sink before serving started, and it
        # exposes frame_age for the episode tracker.
        assert len(sunk) == 1 and hasattr(sunk[0], "frame_age")
        assert (
            len(alert_states) == 1
            and alert_states[0].snapshot()["active"] is False
        )
        try:
            urllib.request.urlopen(f"{base}/events.json?token=wrong", timeout=2)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as denied:
            assert denied.code == 401
    finally:
        source.close()


def test_annotate_requires_token_and_validates_payload() -> None:
    rows: list[tuple[str, float, str]] = []

    def sink(kind: str, ts: float, detail: str) -> int:
        rows.append((kind, ts, detail))
        return 7

    handler = _make_handler(FrameBroker(), "tk", "Cot cam", annotation_sink=sink)
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            _post_json(f"{base}/annotate", {"kind": "worker_note", "detail": "x"}, token="")
        assert denied.value.code == 401

        bad_cases = [
            ({"kind": "manual_note", "detail": "x"}, "bad kind"),
            ({"kind": "worker_note", "detail": "   "}, "detail required"),
            ({"kind": "worker_note", "detail": "x" * 2001}, "detail too long"),
            ({"kind": "worker_note", "detail": "x", "ts": time.time() + 120}, "bad ts"),
        ]
        for payload, error in bad_cases:
            with pytest.raises(urllib.error.HTTPError) as rejected:
                _post_json(f"{base}/annotate", payload)
            assert rejected.value.code == 400
            body = json.loads(rejected.value.read())
            assert body["error"] == error

        with pytest.raises(urllib.error.HTTPError) as too_large:
            _post_json(
                f"{base}/annotate",
                {"kind": "worker_note", "detail": "x" * (9 * 1024)},
            )
        assert too_large.value.code == 413
        assert rows == []
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_rejects_negative_content_length_without_reading() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        annotation_sink=lambda _kind, _ts, _detail: 1,
    )
    httpd, _base = _start_handler_server(handler)
    conn = http.client.HTTPConnection(
        "127.0.0.1",
        httpd.server_address[1],
        timeout=2,
    )
    try:
        conn.putrequest("POST", "/annotate?token=tk")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        response = conn.getresponse()
        body = json.loads(response.read())
        assert response.status == 411
        assert body == {"ok": False, "error": "content length required"}
    finally:
        conn.close()
        httpd.shutdown()
        httpd.server_close()


def test_annotate_invalid_utf8_returns_invalid_json() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        annotation_sink=lambda _kind, _ts, _detail: 1,
    )
    httpd, base = _start_handler_server(handler)
    request = urllib.request.Request(
        f"{base}/annotate?token=tk",
        data=b"\xff\xfe{",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=2)
        assert rejected.value.code == 400
        assert json.loads(rejected.value.read()) == {
            "ok": False,
            "error": "invalid json",
        }
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_rate_limit_counts_invalid_attempts() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        annotation_sink=lambda _kind, _ts, _detail: 1,
    )
    httpd, base = _start_handler_server(handler)
    try:
        for _ in range(30):
            with pytest.raises(urllib.error.HTTPError) as rejected:
                _post_json(f"{base}/annotate", {"kind": "manual_note", "detail": "x"})
            assert rejected.value.code == 400

        with pytest.raises(urllib.error.HTTPError) as limited:
            _post_json(f"{base}/annotate", {"kind": "worker_note", "detail": "x"})
        assert limited.value.code == 429
        assert json.loads(limited.value.read())["error"] == "rate limited"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_404_without_sink() -> None:
    handler = _make_handler(FrameBroker(), "tk", "Cot cam")
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as missing:
            _post_json(f"{base}/annotate", {"kind": "worker_note", "detail": "x"})
        assert missing.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_sink_exception_returns_500_and_server_continues() -> None:
    def sink(_kind: str, _ts: float, _detail: str) -> int:
        raise RuntimeError("boom")

    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        events_provider=lambda: {"events": []},
        annotation_sink=sink,
    )
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as failed:
            _post_json(f"{base}/annotate", {"kind": "worker_note", "detail": "x"})
        assert failed.value.code == 500
        assert json.loads(failed.value.read()) == {"ok": False}

        body = urllib.request.urlopen(f"{base}/events.json?token=tk", timeout=2).read()
        assert json.loads(body) == {"events": []}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_success_writes_fake_sink_and_does_not_raise_alert() -> None:
    alert_state = _AlertState()
    before = alert_state.snapshot()
    rows: list[tuple[str, float, str]] = []

    def sink(kind: str, ts: float, detail: str) -> int:
        rows.append((kind, ts, detail))
        return 123

    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        alert_state=alert_state,
        annotation_sink=sink,
    )
    httpd, base = _start_handler_server(handler)
    try:
        response = _post_json(
            f"{base}/annotate",
            {"kind": "worker_observation", "detail": "  movement changed  "},
        )
        assert json.loads(response.read()) == {"ok": True, "id": 123}
        assert rows and rows[0][0] == "worker_observation"
        assert rows[0][2] == "movement changed"
        assert alert_state.snapshot() == before
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_annotate_real_sensor_store_surfaces_in_timeline(tmp_path) -> None:
    from beddington.sensor_store import SensorStore

    store = SensorStore(str(tmp_path / "events.db"))

    def sink(kind: str, ts: float, detail: str) -> int | None:
        return store.append_event(kind, ts, ended_ts=ts, detail=detail)

    handler = _make_handler(FrameBroker(), "tk", "Cot cam", annotation_sink=sink)
    httpd, base = _start_handler_server(handler)
    try:
        ts = time.time()
        response = _post_json(
            f"{base}/annotate",
            {"kind": "worker_observation", "detail": "state changed", "ts": ts},
        )
        assert json.loads(response.read())["ok"] is True
        timeline = store.timeline_since(ts - 1)
        assert timeline == [
            {
                "kind": "worker_observation",
                "started_ts": ts,
                "ended_ts": ts,
                "detail": "state changed",
            }
        ]
    finally:
        httpd.shutdown()
        httpd.server_close()
        store.close()


def test_frame_jpg_requires_token_and_serves_latest_frame() -> None:
    broker = FrameBroker()
    broker.publish(JPEG_A)
    handler = _make_handler(broker, "tk", "Cot cam")
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f"{base}/frame.jpg", timeout=2)
        assert denied.value.code == 401

        response = urllib.request.urlopen(f"{base}/frame.jpg?token=tk", timeout=2)
        assert response.read() == JPEG_A
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.headers["X-Frame-Seq"] == "1"
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_frame_jpg_503_when_no_frame_published() -> None:
    handler = _make_handler(FrameBroker(), "tk", "Cot cam")
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as unavailable:
            urllib.request.urlopen(f"{base}/frame.jpg?token=tk", timeout=3)
        assert unavailable.value.code == 503
        assert json.loads(unavailable.value.read()) == {
            "ok": False,
            "error": "no frame",
        }
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_frame_jpg_404_without_broker() -> None:
    handler = _make_handler(object(), "tk", "Cot cam")
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{base}/frame.jpg?token=tk", timeout=2)
        assert missing.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_frame_jpg_works_with_dual_camera_serve_live_view_wiring() -> None:
    day = _FakeFrameSource([JPEG_A])
    night = _FakeFrameSource([JPEG_B])
    token = "tk"
    port = _free_port()
    mode = {"v": "day"}
    thread = threading.Thread(
        target=serve_live_view,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "token": token,
            "sources": {"day": day, "night": night},
            "mode_getter": lambda: mode["v"],
        },
        daemon=True,
    )
    thread.start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    try:
        assert urllib.request.urlopen(f"{base}/frame.jpg?token={token}", timeout=2).read() == JPEG_A
        mode["v"] = "night"
        time.sleep(0.1)
        assert urllib.request.urlopen(f"{base}/frame.jpg?token={token}", timeout=2).read() == JPEG_B
    finally:
        day.close()
        night.close()


def test_audio_endpoints_404_when_disabled() -> None:
    handler = _make_handler(FrameBroker(), "tk", "Cot cam")

    audio = _handler_response(
        handler,
        b"GET /audio.pcm?token=tk HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    talk = _handler_response(
        handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: audio/webm\r\nContent-Length: 4\r\n\r\nclip"
        ),
    )

    assert b" 404 " in audio
    assert b" 404 " in talk


def test_audio_endpoints_require_full_token() -> None:
    handler = _make_handler(
        FrameBroker(),
        "full-token",
        "Cot cam",
        worker_token="worker-token",
        audio_broker=_FakeAudioBroker(),
        talk_player=_FakeTalkPlayer(),
    )
    talk_bad = (
        b"POST /talk?token=bad HTTP/1.1\r\nHost: test\r\n"
        b"Content-Type: audio/webm\r\nContent-Length: 4\r\n\r\nclip"
    )
    talk_worker = (
        b"POST /talk?token=worker-token HTTP/1.1\r\nHost: test\r\n"
        b"Content-Type: audio/webm\r\nContent-Length: 4\r\n\r\nclip"
    )

    assert b" 401 " in _handler_response(
        handler,
        b"GET /audio.pcm?token=bad HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    assert b" 403 " in _handler_response(
        handler,
        b"GET /audio.pcm?token=worker-token HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    assert b" 401 " in _handler_response(handler, talk_bad)
    assert b" 403 " in _handler_response(handler, talk_worker)

    audio = _handler_response(
        handler,
        b"GET /audio.pcm?token=full-token HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    assert b" 200 " in audio
    assert audio.endswith(b"\x01\x00\x02\x00")


def test_talk_validates_size_type_busy_and_success() -> None:
    player = _FakeTalkPlayer()
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        audio_broker=_FakeAudioBroker(),
        talk_player=player,
    )
    wrong_type = _handler_response(
        handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: text/plain\r\nContent-Length: 4\r\n\r\nclip"
        ),
    )
    assert b" 415 " in wrong_type

    oversized = _handler_response(
        handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: audio/webm\r\nContent-Length: "
            + str(TALK_MAX_BYTES + 1).encode()
            + b"\r\n\r\n"
        ),
    )
    assert b" 413 " in oversized

    success = _handler_response(
        handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: audio/webm;codecs=opus\r\n"
            b"Content-Length: 4\r\n\r\nclip"
        ),
    )
    assert _response_json(success) == {"ok": True, "seconds": 1.25}
    assert player.calls == [(b"clip", "audio/webm;codecs=opus")]

    busy_handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        audio_broker=_FakeAudioBroker(),
        talk_player=_FakeTalkPlayer(exc=TalkBusy("busy")),
    )
    busy = _handler_response(
        busy_handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: audio/webm\r\nContent-Length: 4\r\n\r\nclip"
        ),
    )
    assert b" 409 " in busy


def test_talk_playback_error_returns_5xx() -> None:
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        audio_broker=_FakeAudioBroker(),
        talk_player=_FakeTalkPlayer(exc=TalkPlaybackError("ffmpeg")),
    )
    failed = _handler_response(
        handler,
        (
            b"POST /talk?token=tk HTTP/1.1\r\nHost: test\r\n"
            b"Content-Type: audio/webm\r\nContent-Length: 4\r\n\r\nclip"
        ),
    )
    assert b" 500 " in failed


def test_soothe_json_reports_talk_playing() -> None:
    soothe = _FakeSoothe()
    handler = _make_handler(
        FrameBroker(),
        "tk",
        "Cot cam",
        soothe=soothe,
        audio_broker=_FakeAudioBroker(),
        talk_player=_FakeTalkPlayer(playing=True),
    )
    raw = _handler_response(
        handler,
        b"GET /soothe.json?token=tk HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    payload = _response_json(raw)
    assert payload["playing"] == "talk"
    assert payload["talk"] is True

    soothe.play("white_noise")
    raw = _handler_response(
        handler,
        b"GET /soothe.json?token=tk HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    payload = _response_json(raw)
    assert payload["playing"] == "white_noise"
    assert payload["talk"] is True


def test_build_viewer_html_audio_controls_only_when_enabled() -> None:
    disabled = build_viewer_html(
        "/stream.mjpg?token=t",
        alerts_path="/alerts.json?token=t",
    )
    assert 'id="audio"' not in disabled
    assert "LAN only · no cloud · no recording · no audio streaming" in disabled

    enabled = build_viewer_html(
        "/stream.mjpg?token=t",
        audio_path="/audio.pcm?token=t",
        talk_path="/talk?token=t",
    )
    assert 'id="audio" class="audio-section"' in enabled
    assert 'id="listen-btn"' in enabled
    assert 'id="talk-btn"' in enabled
    assert "/audio.pcm?token=t" in enabled
    assert "/talk?token=t" in enabled
    assert "live audio available" in enabled
    assert "Talk needs the https:// URL." in enabled


def test_worker_dashboard_omits_audio_controls() -> None:
    handler = _make_handler(
        FrameBroker(),
        "full-token",
        "Cot cam",
        worker_token="worker-token",
        audio_broker=_FakeAudioBroker(),
        talk_player=_FakeTalkPlayer(),
    )

    worker_page = _handler_response(
        handler,
        b"GET /?token=worker-token HTTP/1.1\r\nHost: test\r\n\r\n",
    )
    full_page = _handler_response(
        handler,
        b"GET /?token=full-token HTTP/1.1\r\nHost: test\r\n\r\n",
    )

    assert b" 200 " in worker_page
    assert b'id="audio"' not in worker_page
    assert b"/audio.pcm?token=worker-token" not in worker_page
    assert b" 200 " in full_page
    assert b'id="audio" class="audio-section"' in full_page


def test_live_view_tls_args_parse_and_wrap_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import beddington.cli as cli
    import beddington.liveview as lv

    args = cli.build_parser().parse_args(
        [
            "live-view",
            "--tls-cert",
            "cert.pem",
            "--tls-key",
            "key.pem",
        ]
    )
    assert args.tls_cert == Path("cert.pem")
    assert args.tls_key == Path("key.pem")

    captured: dict[str, object] = {}

    class FakeHTTPD:
        def __init__(self, address, handler):
            captured["address"] = address
            captured["handler"] = handler
            self.socket = object()

        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    class FakeContext:
        def __init__(self, protocol):
            captured["protocol"] = protocol

        def load_cert_chain(self, certfile, keyfile):
            captured["certfile"] = certfile
            captured["keyfile"] = keyfile

        def wrap_socket(self, socket, server_side=False):
            captured["wrapped_socket"] = socket
            captured["server_side"] = server_side
            return "wrapped"

    source = _FakeFrameSource([JPEG_A])
    monkeypatch.setattr(lv, "_DaemonThreadingHTTPServer", FakeHTTPD)
    monkeypatch.setattr(lv.ssl, "SSLContext", FakeContext)

    lv.serve_live_view(
        host="127.0.0.1",
        port=8088,
        token="tk",
        source=source,
        tls_cert="cert.pem",
        tls_key="key.pem",
    )

    assert captured["protocol"] == lv.ssl.PROTOCOL_TLS_SERVER
    assert captured["certfile"] == "cert.pem"
    assert captured["keyfile"] == "key.pem"
    assert captured["server_side"] is True
    assert captured["served"] is True
    assert captured["closed"] is True


def test_worker_token_gets_and_annotates_but_cannot_control() -> None:
    broker = FrameBroker()
    broker.publish(JPEG_A)
    alert_state = _AlertState()
    soothe = _FakeSoothe()
    annotations: list[tuple[str, str]] = []
    mode = {"value": "night"}

    def set_mode(value: str | None) -> str:
        mode["value"] = value or "night"
        return mode["value"]

    def annotation_sink(kind: str, _ts: float, detail: str) -> int:
        annotations.append((kind, detail))
        return len(annotations)

    handler = _make_handler(
        broker,
        "full-token",
        "Cot cam",
        soothe=soothe,
        mode_setter=set_mode,
        alert_state=alert_state,
        snapshot_provider=lambda _ctx: {
            "label": "Still for 1 min",
            "confidence": {"band": "low"},
        },
        events_provider=lambda: {"events": []},
        worker_token="worker-token",
        annotation_sink=annotation_sink,
    )
    httpd, base = _start_handler_server(handler)
    try:
        snapshot = json.loads(
            urllib.request.urlopen(
                f"{base}/snapshot.json?token=worker-token", timeout=2
            ).read()
        )
        assert snapshot["label"] == "Still for 1 min"
        events = json.loads(
            urllib.request.urlopen(
                f"{base}/events.json?token=worker-token", timeout=2
            ).read()
        )
        assert events == {"events": []}
        assert (
            urllib.request.urlopen(
                f"{base}/frame.jpg?token=worker-token", timeout=2
            ).read()
            == JPEG_A
        )
        assert json.loads(
            _post_json(
                f"{base}/annotate",
                {"kind": "worker_observation", "detail": "state changed"},
                token="worker-token",
            ).read()
        ) == {"ok": True, "id": 1}

        before = alert_state.snapshot()
        for path in (
            "/alert?token=worker-token",
            "/soothe?token=worker-token&action=play&preset=white_noise",
            "/mode?token=worker-token&set=day",
            "/autosoothe?token=worker-token&enabled=1&preset=white_noise",
        ):
            with pytest.raises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(
                    urllib.request.Request(f"{base}{path}", method="POST"),
                    timeout=2,
                )
            assert denied.value.code == 401
        assert alert_state.snapshot() == before

        alert = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{base}/alert?token=full-token&title=Cry&message=x",
                    method="POST",
                ),
                timeout=2,
            ).read()
        )
        assert alert["ok"] is True
        played = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{base}/soothe?token=full-token&action=play&preset=white_noise",
                    method="POST",
                ),
                timeout=2,
            ).read()
        )
        assert played["playing"] == "white_noise"
        forced = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{base}/mode?token=full-token&set=day",
                    method="POST",
                ),
                timeout=2,
            ).read()
        )
        assert forced == {"mode": "day", "mode_auto": False}
        autosoothe = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{base}/autosoothe?token=full-token&enabled=1&preset=white_noise",
                    method="POST",
                ),
                timeout=2,
            ).read()
        )
        assert autosoothe["enabled"] is True
        assert json.loads(
            _post_json(
                f"{base}/annotate",
                {"kind": "worker_observation", "detail": "full token note"},
                token="full-token",
            ).read()
        ) == {"ok": True, "id": 2}
        assert annotations == [
            ("worker_observation", "state changed"),
            ("worker_observation", "full token note"),
        ]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_worker_token_unset_does_not_authenticate_worker_tier() -> None:
    handler = _make_handler(
        FrameBroker(),
        "full-token",
        "Cot cam",
        snapshot_provider=lambda _ctx: {"label": "Still for 1 min"},
    )
    httpd, base = _start_handler_server(handler)
    try:
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(
                f"{base}/snapshot.json?token=worker-token",
                timeout=2,
            )
        assert denied.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
