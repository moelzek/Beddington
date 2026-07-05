from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from beddington import vision_bench
from beddington.config import load_config
from beddington.worker import (
    Annotation,
    PiClient,
    StateChangeAnalyzer,
    VisionProbeAnalyzer,
    WorkerHTTPError,
    WorkerLoop,
    load_analyzer,
)
from beddington.vision_bench import Detection, FrameResult


class _StubServer(ThreadingHTTPServer):
    daemon_threads = True


def _start_stub_server():
    state: dict[str, object] = {
        "tokens": [],
        "annotations": [],
        "fail_snapshot": False,
    }

    class Handler(BaseHTTPRequestHandler):
        def _token(self) -> str:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = (query.get("token") or [""])[0]
            state["tokens"].append(token)
            return token

        def _json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            self._token()
            if path == "/snapshot.json":
                if state["fail_snapshot"]:
                    self._json({"ok": False}, status=500)
                    return
                self._json({"label": "Still for 1 min", "confidence": {"band": "low"}})
                return
            if path == "/events.json":
                self._json({"events": [{"kind": "worker_observation"}]})
                return
            if path == "/frame.jpg":
                body = b"frame-bytes"
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json({"ok": False}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            self._token()
            if path != "/annotate":
                self._json({"ok": False}, status=404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            annotations = state["annotations"]
            assert isinstance(annotations, list)
            annotations.append(payload)
            self._json({"ok": True, "id": len(annotations)})

        def log_message(self, *_args: object) -> None:
            return

    httpd = _StubServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    return httpd, base, state


def test_pi_client_accepts_self_signed_tls_for_https_base_url() -> None:
    import ssl

    https_client = PiClient("https://192.168.1.72:8088", "worker-token", timeout=2)
    context = https_client._ssl_context
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE

    http_client = PiClient("http://192.168.1.72:8088", "worker-token", timeout=2)
    assert http_client._ssl_context is None


def test_pi_client_round_trips_and_raises_on_500() -> None:
    httpd, base, state = _start_stub_server()
    client = PiClient(base, "worker-token", timeout=2)
    try:
        assert client.get_snapshot()["label"] == "Still for 1 min"
        assert client.get_events()["events"][0]["kind"] == "worker_observation"
        assert client.get_frame() == b"frame-bytes"
        assert client.post_annotation(
            Annotation("worker_observation", "state changed", ts=123.0)
        )
        assert state["annotations"] == [
            {
                "kind": "worker_observation",
                "detail": "state changed",
                "ts": 123.0,
            }
        ]
        assert state["tokens"] == ["worker-token"] * 4

        state["fail_snapshot"] = True
        with pytest.raises(WorkerHTTPError) as failed:
            client.get_snapshot()
        assert failed.value.status == 500
    finally:
        httpd.shutdown()
        httpd.server_close()


class _FakeClient:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.events_calls = 0
        self.frame_calls = 0
        self.annotations: list[Annotation] = []

    def get_snapshot(self) -> dict:
        self.snapshot_calls += 1
        return {"label": "Still for 1 min", "confidence": {"band": "low"}}

    def get_events(self) -> dict:
        self.events_calls += 1
        return {"events": [{"kind": "manual_note"}]}

    def get_frame(self) -> bytes | None:
        self.frame_calls += 1
        return b"frame"

    def post_annotation(self, annotation: Annotation) -> bool:
        self.annotations.append(annotation)
        return True


class _StaticAnalyzer:
    name = "static"

    def __init__(self, wants_frame: bool, detail: str = "same") -> None:
        self._wants_frame = wants_frame
        self.detail = detail

    def wants_frame(self, _snapshot: dict) -> bool:
        return self._wants_frame

    def analyze(
        self,
        _snapshot: dict,
        _events: list[dict],
        _frame: bytes | None,
    ) -> list[Annotation]:
        return [Annotation("worker_observation", self.detail)]


class _CrashingAnalyzer:
    name = "crashing"

    def wants_frame(self, _snapshot: dict) -> bool:
        return False

    def analyze(
        self,
        _snapshot: dict,
        _events: list[dict],
        _frame: bytes | None,
    ) -> list[Annotation]:
        raise RuntimeError("analyzer failed")


class _SequenceAnalyzer:
    name = "sequence"

    def __init__(self) -> None:
        self._index = 0

    def wants_frame(self, _snapshot: dict) -> bool:
        return False

    def analyze(
        self,
        _snapshot: dict,
        _events: list[dict],
        _frame: bytes | None,
    ) -> list[Annotation]:
        self._index += 1
        return [Annotation("worker_observation", f"detail-{self._index}")]


def test_worker_loop_run_once_frame_dedup_exceptions_and_event_cadence() -> None:
    client = _FakeClient()
    clock = {"t": 0.0}
    loop = WorkerLoop(
        client,
        [_StaticAnalyzer(wants_frame=True), _CrashingAnalyzer()],
        snapshot_interval=3.0,
        events_interval=10.0,
        dedup_window_s=5.0,
        sleep=lambda _seconds: None,
        clock=lambda: clock["t"],
    )

    assert loop.run_once() == 1
    assert client.events_calls == 1
    assert client.frame_calls == 1

    clock["t"] = 1.0
    assert loop.run_once() == 0
    assert client.events_calls == 1
    assert client.frame_calls == 2

    clock["t"] = 6.0
    assert loop.run_once() == 1
    assert client.events_calls == 1

    clock["t"] = 10.5
    assert loop.run_once() == 0
    assert client.events_calls == 2
    assert client.frame_calls == 4


def test_worker_loop_prunes_expired_dedup_entries() -> None:
    client = _FakeClient()
    clock = {"t": 0.0}
    loop = WorkerLoop(
        client,
        [_SequenceAnalyzer()],
        snapshot_interval=3.0,
        events_interval=100.0,
        dedup_window_s=5.0,
        sleep=lambda _seconds: None,
        clock=lambda: clock["t"],
    )

    assert loop.run_once() == 1
    assert len(loop._posted) == 1
    clock["t"] = 1.0
    assert loop.run_once() == 1
    assert len(loop._posted) == 2
    clock["t"] = 6.0
    assert loop.run_once() == 1
    assert len(loop._posted) == 1
    assert [annotation.detail for annotation in client.annotations] == [
        "detail-1",
        "detail-2",
        "detail-3",
    ]


def test_worker_loop_skips_frame_when_no_analyzer_wants_it() -> None:
    client = _FakeClient()
    loop = WorkerLoop(
        client,
        [_StaticAnalyzer(wants_frame=False)],
        snapshot_interval=3.0,
        events_interval=10.0,
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
    )

    assert loop.run_once() == 1
    assert client.frame_calls == 0


def test_state_change_analyzer_emits_only_on_label_change() -> None:
    analyzer = StateChangeAnalyzer()

    first = {"label": "Still for 1 min", "confidence": {"band": "low"}}
    changed = {"label": "Movement changed", "confidence": {"band": "medium"}}

    assert analyzer.analyze(first, [], None) == []
    annotations = analyzer.analyze(changed, [], None)
    assert annotations == [
        Annotation(
            kind="worker_observation",
            detail="state Still for 1 min -> Movement changed (confidence medium)",
        )
    ]
    assert analyzer.analyze({}, [], None) == []


def test_load_analyzer_builtin_and_bad_spec() -> None:
    assert isinstance(load_analyzer("state_change"), StateChangeAnalyzer)
    assert isinstance(load_analyzer("vision_probe"), VisionProbeAnalyzer)
    with pytest.raises(ValueError, match="unknown analyzer"):
        load_analyzer("does_not_exist")


class _VisionBackend:
    def __init__(self, results: list[FrameResult]) -> None:
        self.results = results
        self.calls = 0

    def analyze_jpeg(self, data: bytes) -> FrameResult:
        del data
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result

    def save_annotated(self, data: bytes, out_path: object) -> None:
        del data, out_path


def _frame_result(
    detections: list[Detection],
    image_h: int = 100,
) -> FrameResult:
    return FrameResult(
        detections=detections,
        poses=[],
        image_w=100,
        image_h=image_h,
        inference_ms=5.0,
    )


def test_vision_probe_throttles_frame_requests() -> None:
    clock = {"t": 10.0}
    analyzer = VisionProbeAnalyzer(
        backend=_VisionBackend([_frame_result([])]),
        min_interval_s=30.0,
        clock=lambda: clock["t"],
    )

    assert analyzer.wants_frame({}) is True
    assert analyzer.analyze({}, [], b"jpeg") == [
        Annotation(kind="worker_person_seen", detail="no person detected")
    ]
    clock["t"] = 39.0
    assert analyzer.wants_frame({}) is False
    assert analyzer.analyze({}, [], None) == []
    clock["t"] = 40.0
    assert analyzer.wants_frame({}) is True


def test_vision_probe_emits_only_when_person_observation_changes() -> None:
    backend = _VisionBackend(
        [
            _frame_result([]),
            _frame_result([]),
            _frame_result([Detection("person", 0.87, (0, 10, 50, 70))]),
            _frame_result([Detection("person", 0.40, (0, 0, 40, 40))]),
            _frame_result(
                [
                    Detection("person", 0.87, (0, 10, 50, 70)),
                    Detection("person", 0.75, (0, 20, 40, 80)),
                ]
            ),
        ]
    )
    analyzer = VisionProbeAnalyzer(
        backend=backend,
        min_interval_s=0.0,
        clock=lambda: 0.0,
    )

    annotations: list[Annotation] = []
    for _ in range(5):
        assert analyzer.wants_frame({})
        annotations.extend(analyzer.analyze({}, [], b"jpeg"))

    assert annotations == [
        Annotation(kind="worker_person_seen", detail="no person detected"),
        Annotation(
            kind="worker_person_seen",
            detail="person x1 (max conf 0.87, max box height 0.60)",
        ),
        Annotation(
            kind="worker_person_seen",
            detail="person x2 (max conf 0.87, max box height 0.60)",
        ),
    ]


def test_vision_probe_frame_none_is_not_an_observation() -> None:
    backend = _VisionBackend([_frame_result([])])
    analyzer = VisionProbeAnalyzer(
        backend=backend,
        min_interval_s=0.0,
        clock=lambda: 0.0,
    )

    assert analyzer.wants_frame({})
    assert analyzer.analyze({}, [], None) == []
    assert backend.calls == 0


def test_vision_probe_builds_default_backend_only_on_first_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = {"count": 0}

    class FakeDefaultBackend(_VisionBackend):
        def __init__(self) -> None:
            built["count"] += 1
            super().__init__([_frame_result([])])

    monkeypatch.setattr(vision_bench, "UltralyticsBackend", FakeDefaultBackend)
    analyzer = VisionProbeAnalyzer(min_interval_s=0.0, clock=lambda: 0.0)

    assert built["count"] == 0
    assert analyzer.wants_frame({})
    assert analyzer.analyze({}, [], None) == []
    assert built["count"] == 0
    assert analyzer.wants_frame({})
    assert analyzer.analyze({}, [], b"jpeg") == [
        Annotation(kind="worker_person_seen", detail="no person detected")
    ]
    assert built["count"] == 1


def test_worker_config_toml_round_trip_and_validation(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[worker]
base_url = "http://pi.local:8088"
snapshot_interval_s = 2.5
events_interval_s = 12.0
request_timeout_s = 4.0
analyzers = ["state_change"]
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.worker.base_url == "http://pi.local:8088"
    assert config.worker.snapshot_interval_s == 2.5
    assert config.worker.events_interval_s == 12.0
    assert config.worker.request_timeout_s == 4.0
    assert config.worker.analyzers == ("state_change",)

    bad_cases = [
        ("base_url = \"ftp://pi\"\n", "worker.base_url"),
        ("snapshot_interval_s = 0\n", "worker.snapshot_interval_s"),
        ("events_interval_s = 0\n", "worker.events_interval_s"),
        ("request_timeout_s = 0\n", "worker.request_timeout_s"),
    ]
    for body, message in bad_cases:
        path.write_text(f"[worker]\n{body}", encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_config(path)


def test_worker_help_exits_zero() -> None:
    from beddington.cli import main

    with pytest.raises(SystemExit) as exited:
        main(["worker", "--help"])
    assert exited.value.code == 0
