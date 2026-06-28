from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from lullaby.liveview import (
    FrameBroker,
    build_viewer_html,
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
