from __future__ import annotations

import importlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .vision_bench import VisionBackend


@dataclass(frozen=True)
class Annotation:
    kind: str
    detail: str
    ts: float | None = None


class WorkerHTTPError(RuntimeError):
    def __init__(self, status: int, path: str) -> None:
        self.status = status
        self.path = path
        super().__init__(f"HTTP {status} from {path}")


class PiClient:
    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = float(timeout)
        # When the Pi serves TLS with the self-signed LAN cert, accept it: the
        # token gates access and this runs on a trusted local network.
        self._ssl_context = None
        if self.base_url.startswith("https://"):
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self._ssl_context = context

    def _url(self, path: str) -> str:
        query = urllib.parse.urlencode({"token": self.token})
        return f"{self.base_url}{path}?{query}"

    def _get_json(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(
                self._url(path), timeout=self.timeout, context=self._ssl_context
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise WorkerHTTPError(exc.code, path) from exc
        if not isinstance(payload, dict):
            raise WorkerHTTPError(200, path)
        return payload

    def get_snapshot(self) -> dict:
        return self._get_json("/snapshot.json")

    def get_events(self) -> dict:
        return self._get_json("/events.json")

    def get_frame(self) -> bytes | None:
        try:
            with urllib.request.urlopen(
                self._url("/frame.jpg"),
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 503):
                return None
            raise WorkerHTTPError(exc.code, "/frame.jpg") from exc

    def post_annotation(self, annotation: Annotation) -> bool:
        payload: dict[str, object] = {
            "kind": annotation.kind,
            "detail": annotation.detail,
        }
        if annotation.ts is not None:
            payload["ts"] = annotation.ts
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url("/annotate"),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self._ssl_context
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise WorkerHTTPError(exc.code, "/annotate") from exc
        return isinstance(result, dict) and bool(result.get("ok"))

    # Deliberately no /alert, /soothe, /mode, or /autosoothe methods: this client
    # enriches the Pi's timeline and does not expose control-channel capabilities.


class Analyzer(Protocol):
    name: str

    def wants_frame(self, snapshot: dict) -> bool:
        ...

    def analyze(
        self,
        snapshot: dict,
        events: list[dict],
        frame: bytes | None,
    ) -> list[Annotation]:
        ...


class StateChangeAnalyzer:
    name = "state_change"

    def __init__(self) -> None:
        self._last_label: str | None = None

    def wants_frame(self, snapshot: dict) -> bool:
        return False

    def analyze(
        self,
        snapshot: dict,
        events: list[dict],
        frame: bytes | None,
    ) -> list[Annotation]:
        label = snapshot.get("label")
        if not isinstance(label, str) or not label.strip():
            return []
        label = label.strip()
        if self._last_label is None:
            self._last_label = label
            return []
        if label == self._last_label:
            return []

        old = self._last_label
        self._last_label = label
        confidence = snapshot.get("confidence")
        band = (
            confidence.get("band")
            if isinstance(confidence, dict) and isinstance(confidence.get("band"), str)
            else "unknown"
        )
        return [
            Annotation(
                kind="worker_observation",
                detail=f"state {old} -> {label} (confidence {band})",
            )
        ]


class VisionProbeAnalyzer:
    name = "vision_probe"

    def __init__(
        self,
        backend: VisionBackend | None = None,
        min_interval_s: float = 30.0,
        clock=time.monotonic,
    ) -> None:
        self._backend = backend
        self._min_interval_s = float(min_interval_s)
        self._clock = clock
        self._last_frame_at = float("-inf")
        self._last_requested = False
        self._last_observation: int | None = None

    def wants_frame(self, snapshot: dict) -> bool:
        del snapshot
        self._last_requested = self._clock() - self._last_frame_at >= self._min_interval_s
        return self._last_requested

    def analyze(
        self,
        snapshot: dict,
        events: list[dict],
        frame: bytes | None,
    ) -> list[Annotation]:
        del snapshot, events
        if not self._last_requested:
            return []
        self._last_requested = False
        self._last_frame_at = self._clock()
        if frame is None:
            return []
        if self._backend is None:
            from .vision_bench import UltralyticsBackend

            self._backend = UltralyticsBackend()

        result = self._backend.analyze_jpeg(frame)
        people = [
            detection
            for detection in result.detections
            if detection.label.strip().lower() == "person"
        ]
        count = len(people)
        observation = min(count, 3)
        if observation == self._last_observation:
            return []
        self._last_observation = observation

        if count == 0:
            detail = "no person detected"
        else:
            max_conf = max(detection.confidence for detection in people)
            max_height = 0.0
            if result.image_h > 0:
                max_height = max(
                    max(0.0, detection.box[3] - detection.box[1]) / result.image_h
                    for detection in people
                )
            detail = (
                f"person x{count} "
                f"(max conf {max_conf:.2f}, max box height {max_height:.2f})"
            )
        return [Annotation(kind="worker_person_seen", detail=detail)]


BUILTIN_ANALYZERS: dict[str, type[Analyzer]] = {
    "state_change": StateChangeAnalyzer,
    "vision_probe": VisionProbeAnalyzer,
}


def load_analyzer(spec: str) -> Analyzer:
    if spec in BUILTIN_ANALYZERS:
        return BUILTIN_ANALYZERS[spec]()
    if ":" not in spec:
        raise ValueError(f"unknown analyzer '{spec}'")
    module_name, attr_name = spec.split(":", 1)
    if not module_name or not attr_name:
        raise ValueError(f"bad analyzer spec '{spec}'")
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, attr_name)
        analyzer = factory()
    except Exception as exc:
        raise ValueError(f"could not load analyzer '{spec}': {exc}") from exc
    return analyzer


class WorkerLoop:
    def __init__(
        self,
        client: PiClient,
        analyzers: list[Analyzer],
        snapshot_interval: float,
        events_interval: float,
        dedup_window_s: float = 300.0,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        if snapshot_interval <= 0:
            raise ValueError("snapshot_interval must be positive")
        if events_interval <= 0:
            raise ValueError("events_interval must be positive")
        if dedup_window_s < 0:
            raise ValueError("dedup_window_s must be non-negative")
        self.client = client
        self.analyzers = analyzers
        self.snapshot_interval = float(snapshot_interval)
        self.events_interval = float(events_interval)
        self.dedup_window_s = float(dedup_window_s)
        self._sleep = sleep
        self._clock = clock
        self._last_events_at = float("-inf")
        self._last_events: list[dict] = []
        self._posted: dict[tuple[str, str], float] = {}

    def _prune_posted(self, now: float) -> None:
        if self.dedup_window_s <= 0:
            self._posted.clear()
            return
        expired = [
            key
            for key, posted_at in self._posted.items()
            if now - posted_at >= self.dedup_window_s
        ]
        for key in expired:
            del self._posted[key]

    def run_once(self) -> int:
        snapshot = self.client.get_snapshot()
        now = self._clock()
        if now - self._last_events_at >= self.events_interval:
            payload = self.client.get_events()
            events = payload.get("events")
            self._last_events = events if isinstance(events, list) else []
            self._last_events_at = now

        active_analyzers: list[Analyzer] = []
        needs_frame = False
        for analyzer in self.analyzers:
            try:
                wants_frame = analyzer.wants_frame(snapshot)
            except Exception:
                LOGGER.warning("analyzer %s failed in wants_frame", analyzer.name, exc_info=True)
                continue
            active_analyzers.append(analyzer)
            needs_frame = needs_frame or wants_frame

        frame = self.client.get_frame() if needs_frame else None
        posted = 0
        for analyzer in active_analyzers:
            try:
                annotations = analyzer.analyze(snapshot, self._last_events, frame)
            except Exception:
                LOGGER.warning("analyzer %s failed in analyze", analyzer.name, exc_info=True)
                continue
            for annotation in annotations:
                key = (annotation.kind, annotation.detail)
                now = self._clock()
                self._prune_posted(now)
                last_posted = self._posted.get(key)
                if (
                    last_posted is not None
                    and now - last_posted < self.dedup_window_s
                ):
                    continue
                if self.client.post_annotation(annotation):
                    self._posted[key] = now
                    posted += 1
        return posted

    def run_forever(self) -> None:
        backoff = 2.0
        while True:
            try:
                self.run_once()
                backoff = 2.0
                self._sleep(self.snapshot_interval)
            except KeyboardInterrupt:
                return
            except Exception:
                LOGGER.warning("worker loop failed; backing off", exc_info=True)
                try:
                    self._sleep(backoff)
                except KeyboardInterrupt:
                    return
                except Exception:
                    LOGGER.warning("worker sleep failed", exc_info=True)
                backoff = min(60.0, backoff * 2.0)
