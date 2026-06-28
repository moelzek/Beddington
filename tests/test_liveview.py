from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

from lullaby.liveview import (
    FrameBroker,
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


def test_build_viewer_html_dashboard_overlay() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t", readings_path="/readings.json?token=t"
    )
    assert "/readings.json?token=t" in html
    assert 'class="panel"' in html
    assert "poll()" in html  # polling script present


def test_build_viewer_html_tabbed_dashboard() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
    )
    assert "/history.json?token=t" in html
    assert "canvas" in html  # graph tabs
    assert "room_temperature_c" in html  # sensor spec embedded
    assert "Camera" in html


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


def test_build_viewer_html_has_night_tab_when_digest() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
    )
    assert "/digest.json?token=t" in html
    assert "Night" in html
    assert "loadDigest" in html


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
    from lullaby.liveview import day_night_mode

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
    cmd = rpicam_vid_command(night=True)
    assert "--shutter" in cmd  # longer exposure
    assert "--gain" in cmd  # higher gain


def test_frame_broker_delivers_and_closes() -> None:
    broker = FrameBroker()
    broker.publish(JPEG_A)
    seq, frame = broker.wait_for_frame(0, timeout=1.0)
    assert frame == JPEG_A and seq == 1
    broker.close()
    assert broker.closed
    _, frame = broker.wait_for_frame(seq, timeout=1.0)
    assert frame is None  # closed -> no frame


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

    def presets(self) -> list[dict[str, str]]:
        return [
            {"key": "white_noise", "label": "White noise"},
            {"key": "heartbeat", "label": "Heartbeat"},
        ]

    def default(self) -> str:
        return "white_noise"

    def playing(self) -> str | None:
        return self._playing

    def play(self, name: str) -> dict[str, object]:
        self._playing = name
        return {"ok": True, "playing": name}

    def stop(self) -> dict[str, object]:
        self._playing = None
        return {"ok": True, "playing": None}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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
        page = urllib.request.urlopen(f"{base}/?token={token}", timeout=2).read()
        assert b"readings.json" in page
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


def test_build_viewer_html_has_soothe_tab() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        soothe_path="/soothe?token=t",
    )
    assert "Soothe" in html
    assert "soothePost" in html
    assert "/soothe?token=t" in html


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
        assert json.loads(urllib.request.urlopen(play, timeout=2).read())["playing"] == "white_noise"

        stop = urllib.request.Request(
            f"{base}/soothe?token={token}&action=stop", method="POST"
        )
        assert json.loads(urllib.request.urlopen(stop, timeout=2).read())["playing"] is None
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
