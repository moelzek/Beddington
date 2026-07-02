from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from beddington.liveview import (
    _SOI,
    FrameBroker,
    _DaemonThreadingHTTPServer,
    _ModeBroker,
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
    # Night drops the frame rate so the long exposure fits (more light per frame).
    assert int(cmd[cmd.index("--framerate") + 1]) < 12


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


def test_build_viewer_html_has_soothe_tab() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        soothe_path="/soothe?token=t",
    )
    assert "Soothe" in html
    assert "soothePost" in html
    assert "soothe-status" in html
    assert "setSootheStatus" in html
    assert "addCurrentSootheControl" in html
    assert "Cry trigger sound" in html
    assert "addPresetGroups" in html
    assert "card.onclick" in html
    assert "Sounds" in html
    assert "Music" in html
    assert "/soothe?token=t" in html


def test_build_viewer_html_keeps_soothe_without_history() -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        soothe_path="/soothe?token=t",
    )

    assert "Soothe" in html
    assert "soothe-status" in html
    assert "async function load(){if(!HISTORY)" in html
    assert "/soothe?token=t" in html


def test_dashboard_script_is_valid_javascript(tmp_path) -> None:
    html = build_viewer_html(
        "/stream.mjpg?token=t",
        readings_path="/readings.json?token=t",
        history_path="/history.json?token=t",
        digest_path="/digest.json?token=t",
        soothe_path="/soothe?token=t",
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
