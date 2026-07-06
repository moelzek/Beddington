"""LAN-only live camera view for Beddington.

Serves a Motion-JPEG stream over plain HTTP so a phone on the *same WiFi* can
watch the camera in a browser. Privacy-first by construction:

  * **LAN only** — nothing is sent to the Internet; the Pi simply listens on the
    home network. Keep the home router from port-forwarding this port.
  * **Token required** — every request must carry the shared token, so a random
    device on the network can't open the stream.
  * **No recording** — frames are streamed to connected viewers and never written
    to disk. No audio is captured or served.

The camera frames come from ``rpicam-vid --codec mjpeg`` (the standard Pi tool),
read behind a small ``FrameSource`` adapter so the HTTP logic is testable with a
fake source and no hardware. The pure helpers (JPEG framing, multipart wrapping,
the viewer page, the auth check, the rpicam command) are all unit-tested.
"""

from __future__ import annotations

import hmac
import html
import json
import math
import re
import ssl
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .liveaudio import (
    TALK_MAX_BYTES,
    AudioBroker,
    AudioClientTooSlow,
    AudioUnavailable,
    TalkBusy,
    TalkPlaybackError,
    TalkPlayer,
    TalkRejected,
)

_SOI = b"\xff\xd8"  # JPEG start-of-image
_EOI = b"\xff\xd9"  # JPEG end-of-image
_BOUNDARY = b"frame"

# Cap the in-progress JPEG frame buffer so a wedged/garbled camera (one SOI
# then a long run with no EOI) can't grow ``buf`` without bound and OOM the Pi.
_MAX_JPEG_BYTES = 8 * 1024 * 1024

# Cap concurrent MJPEG stream viewers so slow/malicious readers can't exhaust
# the ThreadingHTTPServer's threads/FDs and starve everyone else of live view.
_MAX_STREAM_VIEWERS = 6
_STREAM_VIEWERS = threading.Semaphore(_MAX_STREAM_VIEWERS)
# Socket write timeout (seconds) for a stream connection, so a stalled write
# raises instead of pinning a handler thread forever.
_STREAM_WRITE_TIMEOUT = 20.0
# Header read timeout (seconds) for newly accepted connections, so a client that
# drips request bytes cannot pin a handler before authentication.
_HEADER_READ_TIMEOUT = 5.0
_ANNOTATION_BODY_MAX_BYTES = 8 * 1024
_ANNOTATION_DETAIL_MAX_CHARS = 2000
_ANNOTATION_KIND_RE = re.compile(r"^worker_[a-z0-9_]{1,40}$")
_ANNOTATION_RATE_LIMIT = 30
_ANNOTATION_RATE_WINDOW_S = 60.0
_TALK_CONTENT_TYPES = ("audio/webm", "audio/mp4", "audio/ogg")


class _DaemonThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer whose per-connection threads are daemons, so a stuck
    stream handler (e.g. a slow-loris viewer wedged in ``wfile.write``) can never
    block interpreter shutdown or ``server_close``."""

    daemon_threads = True


def _html_attr(value: object) -> str:
    return html.escape(str(value), quote=True)


def _js_string_content(value: object) -> str:
    return json.dumps(str(value))[1:-1]


def iter_jpeg_frames(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Split a Motion-JPEG byte stream into complete JPEG frames.

    ``rpicam-vid --codec mjpeg`` writes back-to-back JPEGs; each starts with
    ``FF D8`` and ends with ``FF D9``. Yields one ``bytes`` per complete frame,
    buffering partial data across chunk boundaries.
    """
    buf = bytearray()
    for chunk in chunks:
        buf.extend(chunk)
        while True:
            start = buf.find(_SOI)
            if start < 0:
                # No frame start in view; keep only a trailing byte (a split FF).
                if len(buf) > 1:
                    del buf[:-1]
                break
            end = buf.find(_EOI, start + 2)
            if end < 0:
                # Incomplete frame — drop leading junk, wait for more bytes.
                if start > 0:
                    del buf[:start]
                    start = 0
                # Guard against a wedged stream (SOI then endless non-EOI bytes):
                # if the in-progress frame blows past the cap, this SOI is junk.
                # Drop it (keep only the trailing byte, in case it's a split FF)
                # and resync on the next SOI instead of buffering forever.
                if len(buf) > _MAX_JPEG_BYTES:
                    del buf[:-1]
                break
            if end + 2 - start > _MAX_JPEG_BYTES:
                # We found an EOI, but the "frame" from this SOI to it is bigger
                # than any real JPEG — so this SOI is junk we synced onto (with a
                # valid frame buffered after it). Drop this SOI and resync on the
                # next one instead of yielding one giant corrupt frame.
                nxt = buf.find(_SOI, start + 2)
                if nxt < 0:
                    del buf[:-1]  # keep a trailing FF for a split marker
                    break
                del buf[:nxt]
                continue
            yield bytes(buf[start : end + 2])
            del buf[: end + 2]


def multipart_frame(jpeg: bytes, boundary: bytes = _BOUNDARY) -> bytes:
    """Wrap one JPEG as a multipart/x-mixed-replace chunk for the browser."""
    return (
        b"--" + boundary + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    )


def is_authorised(provided: str, expected: str) -> bool:
    """Constant-time token check. An empty expected token never authorises."""
    if not expected:
        return False
    try:
        return hmac.compare_digest(provided, expected)
    except TypeError:
        return False


_ALERT_TTL_SECONDS = 45.0


class _AlertState:
    """Thread-safe holder for the single active LAN alert.

    The always-on assistant POSTs ``/alert`` when it detects sustained crying;
    the dashboard polls ``/alerts.json`` and, when ``active`` and ``seq`` has
    changed, raises the banner, beeps and fires a browser notification. An alert
    is only ``active`` while it is fresh (raised within the TTL), so a missed
    ``clear`` still self-heals when the crying stops posting.
    """

    def __init__(self, ttl_seconds: float = _ALERT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._seq = 0
        self._title = ""
        self._message = ""
        self._score = 0.0
        self._raised_at: float | None = None

    def raise_alert(
        self, title: str, message: str, score: float = 0.0
    ) -> dict[str, object]:
        with self._lock:
            self._seq += 1
            self._title = str(title)
            self._message = str(message)
            self._score = float(score)
            self._raised_at = time.monotonic()
            return {"ok": True, "seq": self._seq}

    def clear(self) -> dict[str, object]:
        with self._lock:
            self._raised_at = None
            return {"ok": True}

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            if self._raised_at is None:
                age: float | None = None
                active = False
            else:
                age = time.monotonic() - self._raised_at
                active = age <= self._ttl
            return {
                "active": active,
                "title": self._title,
                "message": self._message,
                "score": self._score,
                "seq": self._seq,
                "age_seconds": age,
            }


# The sensors shown in the Engineering debug graphs. ``scale`` converts the stored
# value for display (gas ohms -> kilo-ohms); ``bool`` marks on/off readings.
DASHBOARD_SENSORS: tuple[dict[str, object], ...] = (
    {"key": "room_temperature_c", "label": "Temp", "unit": "°C"},
    {"key": "room_humidity_pct", "label": "Humidity", "unit": "%"},
    {"key": "room_pressure_hpa", "label": "Pressure", "unit": "hPa"},
    {"key": "room_gas_resistance_ohms", "label": "Air", "unit": "kΩ", "scale": 0.001},
    {"key": "room_illuminance_lx", "label": "Light", "unit": "lux"},
    {"key": "target_distance_cm", "label": "Distance", "unit": "cm"},
    {"key": "radar_respiratory_rate", "label": "Breathing", "unit": "/min"},
    {"key": "radar_heart_rate_bpm", "label": "Heart", "unit": "bpm"},
    {"key": "person_present", "label": "Presence", "bool": True},
    {"key": "motion_detected", "label": "Motion", "bool": True},
)


def history_series(
    history: Iterable[tuple[float, dict[str, object]]],
    sensors: tuple[dict[str, object], ...] = DASHBOARD_SENSORS,
) -> dict[str, object]:
    """Turn a list of (timestamp, snapshot) samples into per-sensor time series
    ready for the dashboard graphs. Booleans become 0/1; ``scale`` is applied."""
    samples = list(history)
    series: dict[str, object] = {}
    for spec in sensors:
        key = str(spec["key"])
        scale = float(spec.get("scale", 1))
        points: list[list[float]] = []
        for ts, snapshot in samples:
            value = snapshot.get(key)
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                value = float(value) * scale
            else:
                continue
            points.append([round(float(ts), 1), round(value, 3)])
        series[key] = {
            "label": spec["label"],
            "unit": spec.get("unit", ""),
            "bool": bool(spec.get("bool", False)),
            "points": points,
        }
    return series


_DASHBOARD_TEMPLATE = """<!doctype html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box}
:root{color-scheme:dark;--bg:#050607;--surface:#101312;--surface2:#151917;
--text:#F4EFE6;--muted:#B8B0A6;--border:#2B302E;--primary:#58C7B0;
--urgent:#FF6B6B;--attention:#E8B154;--line:#202522;--tabbar:60px}
body.notabs{--tabbar:0px}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);
font:16px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
button,select{font:inherit}
button{min-height:44px}
button:focus-visible,select:focus-visible,details summary:focus-visible,
[role="button"]:focus-visible{outline:2px solid var(--primary);outline-offset:3px}
.view[hidden]{display:none}
.page{width:min(100%,760px);margin:0 auto;padding:16px 14px calc(var(--tabbar) + 28px)}
#alertbanner{display:none;position:fixed;top:0;left:0;right:0;z-index:50;
background:#B4232C;color:#fff;font-weight:800;font-size:15px;
padding:12px 14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.5)}
.t2-alerts{display:grid;gap:8px;width:min(100%,430px)}
.t2-alert-card{border:1px solid rgba(232,177,84,.78);border-radius:12px;
background:rgba(27,22,13,.92);padding:12px;color:var(--text)}
.t2-alert-title{font-size:15px;font-weight:800;line-height:1.25;margin:0 0 4px}
.t2-alert-message,.t2-alert-action{color:var(--muted);font-size:13px;line-height:1.35}
.t2-alert-action{margin-top:6px;color:var(--attention);font-weight:800}
.health-dots{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 14px}
.health-dot{display:inline-flex;align-items:center;gap:5px;color:var(--muted);
font-size:12px;line-height:1.2;min-height:24px}
.health-dot::before{content:"";width:9px;height:9px;border-radius:50%;background:var(--attention);
box-shadow:0 0 0 2px rgba(232,177,84,.12)}
.health-dot.fresh::before{background:var(--primary);box-shadow:0 0 0 2px rgba(88,199,176,.14)}
.health-dot.error::before{background:var(--urgent);box-shadow:0 0 0 2px rgba(255,107,107,.14)}
.camera-frame{position:relative;display:flex;align-items:center;justify-content:center;
overflow:hidden;height:calc(100vh - 60px);height:calc(100dvh - var(--tabbar));
min-height:420px;background:#000}
.camera-frame img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.camera-frame img.rot90,.camera-frame img.rot270{position:absolute;top:50%;left:50%;
width:calc(100dvh - var(--tabbar));height:100vw;max-width:none;max-height:none}
.camera-frame img.rot90{transform:translate(-50%,-50%) rotate(90deg)}
.camera-frame img.rot270{transform:translate(-50%,-50%) rotate(270deg)}
.camera-frame img.rot180{transform:rotate(180deg)}
.stream-error{display:none;position:absolute;inset:auto 12px 150px 12px;z-index:5;
padding:12px;border-radius:10px;background:rgba(16,19,18,.92);color:var(--text);
text-align:center;border:1px solid var(--border)}
.cam-top{position:absolute;top:0;left:0;right:0;z-index:6;padding:64px 14px 44px;
display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none;
background:linear-gradient(180deg,rgba(0,0,0,.6) 0%,rgba(0,0,0,.22) 62%,transparent 100%)}
.cam-top>*{pointer-events:auto}
.live-chip{position:absolute;left:14px;top:16px;display:inline-flex;align-items:center;gap:6px;
font-size:12px;font-weight:800;letter-spacing:.06em;color:#fff;
background:rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.18);border-radius:999px;
padding:6px 11px;backdrop-filter:blur(8px)}
.live-chip i{width:7px;height:7px;border-radius:50%;background:#FF5F57}
.cam-tools{position:absolute;right:14px;top:12px;display:flex;gap:8px}
.mode-btn,.rot-btn{display:inline-flex;align-items:center;min-height:34px;cursor:pointer;
border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:6px 12px;
background:rgba(0,0,0,.45);color:#fff;font-size:12px;font-weight:700;white-space:nowrap;
backdrop-filter:blur(8px)}
.state-chip{max-width:86%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:10px 20px;
font-size:16px;font-weight:700;color:#fff;background:rgba(0,0,0,.45);backdrop-filter:blur(10px)}
.readings-overlay{display:flex;justify-content:center;align-items:center;flex-wrap:wrap;
max-width:92%;text-shadow:0 1px 3px rgba(0,0,0,.8)}
.reading-pill{display:inline-flex;align-items:center;color:rgba(244,239,230,.82);
font-size:13px;font-weight:600;white-space:nowrap}
.reading-pill:not(:last-child)::after{content:"·";margin:0 7px;color:rgba(244,239,230,.5)}
.cam-actions{position:absolute;left:0;right:0;bottom:0;z-index:6;padding:76px 14px 18px;
display:flex;justify-content:center;align-items:center;gap:14px;
background:linear-gradient(0deg,rgba(0,0,0,.72) 26%,transparent 100%)}
.audio-section,.audio-controls{display:contents}
.audio-btn{border-radius:999px;background:rgba(255,255,255,.12);
border:1px solid rgba(255,255,255,.22);color:#fff;font-size:14px;font-weight:750;
padding:13px 20px;backdrop-filter:blur(10px);min-width:96px}
#talk-btn{background:#fff;border-color:#fff;color:#0B0D0C;padding:15px 24px}
.audio-btn.on{background:#0e4d43;border-color:var(--primary);color:#fff}
.audio-btn.talking,#talk-btn.talking{background:#5c2630;border-color:#9a4350;color:#fff}
.audio-btn:disabled{opacity:.5}
.audio-status{position:absolute;left:0;right:0;bottom:82px;text-align:center;
color:rgba(244,239,230,.85);font-size:12.5px;min-height:17px;text-shadow:0 1px 3px rgba(0,0,0,.8)}
.monitor-note{position:absolute;left:0;right:0;bottom:2px;z-index:6;text-align:center;
color:rgba(184,176,166,.55);font-size:10.5px;pointer-events:none}
#tabs{position:fixed;left:0;right:0;bottom:0;height:var(--tabbar);z-index:30;display:flex;
background:rgba(8,10,9,.94);backdrop-filter:blur(14px);border-top:1px solid var(--border)}
.tab-btn{flex:1;background:none;border:none;color:var(--muted);font-size:12.5px;
font-weight:750;letter-spacing:.02em;min-height:0;cursor:pointer}
.tab-btn.active{color:var(--primary)}
#sound-sheet{position:fixed;inset:0;z-index:40;display:none}
#sound-sheet.open{display:block}
.sheet-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.sheet-panel{position:absolute;left:50%;transform:translateX(-50%);width:min(100%,560px);bottom:0;max-height:80dvh;overflow:auto;
background:var(--surface);border-top:1px solid var(--border);
border-radius:18px 18px 0 0;padding:6px 16px 30px}
.sheet-handle{width:44px;height:5px;border-radius:999px;background:var(--border);margin:8px auto 10px}
.nightnote{position:absolute;left:0;right:0;bottom:122px;text-align:center;padding:6px 14px;
color:rgba(244,239,230,.7);font-size:12px;display:none;z-index:4;text-shadow:0 1px 3px rgba(0,0,0,.8)}
.camera-chips{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;
align-items:center;max-width:92%;pointer-events:none}
.camera-chip{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
border:1px solid rgba(244,239,230,.16);border-radius:999px;padding:4px 10px;
background:rgba(8,10,9,.72);color:var(--text);font-size:12px;line-height:1.35;
backdrop-filter:blur(6px)}
.state-grid{display:grid;gap:12px;margin-bottom:14px}
.state-hero,.action-card,.room-action-card,.card,.engineering{
border:1px solid var(--border);border-radius:14px;background:var(--surface);padding:14px}
.state-label{font-size:24px;line-height:1.2;font-weight:800;letter-spacing:0;margin:0 0 8px}
.meta-line{color:var(--muted);font-size:13px;line-height:1.35}
.activity-slider{margin-top:14px;padding-top:12px;border-top:1px solid rgba(43,48,46,.78)}
.activity-labels{display:flex;justify-content:space-between;color:var(--muted);
font-size:12px;font-weight:800;margin-bottom:7px}
.activity-track{position:relative;height:10px;border-radius:999px;
background:linear-gradient(90deg,#345B8A 0%,#58C7B0 45%,#E8B154 78%,#FF6B6B 100%);
box-shadow:inset 0 0 0 1px rgba(244,239,230,.1);opacity:.96}
.activity-track.dim{opacity:.34;filter:saturate(.7)}
.activity-thumb{position:absolute;top:50%;left:0;width:18px;height:18px;border-radius:50%;
transform:translate(-50%,-50%);background:#58C7B0;border:2px solid #080a09;
box-shadow:0 0 0 2px rgba(88,199,176,.36);transition:left .45s ease,opacity .2s ease}
.activity-track.dim .activity-thumb{opacity:0}
.activity-caption{min-height:17px;color:var(--muted);font-size:12px;margin-top:6px}
.action-panel{display:grid;gap:10px}
.action-card{display:block;width:100%;text-align:left;color:var(--text);text-decoration:none}
.action-card.actionable{cursor:pointer;border-color:rgba(88,199,176,.65)}
.action-label{font-size:17px;line-height:1.3;font-weight:750;margin:0 0 6px}
.action-detail{margin:0;color:var(--muted)}
.room-action-card{border-color:rgba(232,177,84,.75);background:#1b160d}
.sensor-area{display:grid;gap:12px;margin-bottom:14px}
.sensor-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.sensor-card{min-width:0;border:1px solid var(--border);border-radius:8px;background:var(--surface);
padding:11px;display:grid;gap:4px}
.sensor-name{color:var(--muted);font-size:12px;font-weight:800}
.sensor-value{font-size:15px;font-weight:750;line-height:1.25;overflow-wrap:break-word}
.sensor-age,.sensor-extra{color:var(--muted);font-size:12px;line-height:1.3}
.section-title{font-size:22px;line-height:1.25;margin:6px 0 14px;font-weight:800}
.digest{white-space:pre-wrap;font-size:15.5px;line-height:1.6;color:var(--text);margin:0}
.summary-row{display:grid;gap:12px;margin-bottom:14px}
.summary-card summary{min-height:44px;display:flex;align-items:center;cursor:pointer;
font-size:17px;font-weight:750}
.summary-card[open] summary{margin-bottom:10px}
.motion-donut-card{min-width:0}
.motion-donut-body{display:grid;grid-template-columns:92px minmax(0,1fr);gap:12px;align-items:center}
.motion-donut-canvas{position:relative;width:92px;height:92px}
#motion-donut{width:92px;height:92px;display:block}
.motion-donut-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
padding:4px;text-align:center;color:var(--muted);font-size:12px;line-height:1.25}
.motion-donut-empty[hidden]{display:none}
.motion-legend{display:grid;gap:5px}
.motion-legend-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:7px;
align-items:center;color:var(--muted);font-size:12px;line-height:1.25}
.motion-dot{width:8px;height:8px;border-radius:50%;background:var(--border)}
.motion-dot.moving{background:#58C7B0}.motion-dot.still{background:#6D7672}
.motion-dot.missing{background:#2B302E;border:1px solid #454C48}
.crying-list{display:grid;gap:7px;color:var(--text);font-size:14px;line-height:1.35}
.crying-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:baseline}
.cry-when{color:var(--muted);font-variant-numeric:tabular-nums}
.cry-dur{color:var(--muted)}
.cry-more{color:var(--muted);font-size:12px}
.soothe-section{margin:0;padding:4px 2px 0}
.cur{font-size:15px;line-height:1.3;font-weight:650;color:var(--muted);margin:0 0 10px}
.soothe-section .section-title{font-size:19px;margin:0 0 4px}
.sbtns{display:grid;gap:10px}
.sbtn{background:#17201d;color:var(--text);border:1px solid var(--border);border-radius:8px;
padding:11px 14px;font-size:15px;font-weight:800}
.squick{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;
align-items:end;border:1px solid var(--border);border-radius:8px;padding:10px;background:var(--surface2)}
.squick label{display:block;color:var(--muted);font-size:12px;font-weight:800;margin:0 0 6px}
.sselect{width:100%;min-height:44px;background:#080a09;color:var(--text);border:1px solid var(--border);
border-radius:8px;padding:10px;font-size:15px}
.squick .sbtn{min-width:92px}
.sbtn.on{background:#0e4d43;border-color:#58C7B0}
.sbtn.stop{background:#4c1d24;border-color:#7a3340}
.sbtn.cry{background:#5c2630;border-color:#9a4350;font-weight:850;width:100%}
.sstatus{width:100%;min-height:20px;color:var(--primary);font-size:13px}
.engineering{margin-bottom:14px}
.engineering summary{min-height:44px;display:flex;align-items:center;cursor:pointer;
font-size:17px;font-weight:750}
.sensor-picks{display:flex;gap:8px;overflow-x:auto;padding:4px 0 12px;-webkit-overflow-scrolling:touch}
.sensor-chip{flex:0 0 auto;min-height:44px;background:#111815;color:var(--muted);
border:1px solid var(--border);border-radius:999px;padding:8px 13px;font-size:13px;font-weight:800}
.sensor-chip.active{color:var(--text);border-color:#58C7B0;background:#0e302b}
.chart-panel[hidden]{display:none}
.chartwrap{padding:0}
.chart-panel canvas{width:100%;height:300px;background:#080a09;border:1px solid var(--border);
border-radius:8px;display:block}
.note{color:var(--muted);padding:14px 0 0;font-size:12px;text-align:center}
@media (min-width:720px){
.state-grid{grid-template-columns:1.1fr .9fr;align-items:start}
.sensor-area{grid-template-columns:1fr 1fr}
}
@media (max-width:420px){
.health-dot span{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.cam-actions{gap:10px}.audio-btn{min-width:0;padding:12px 16px}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important}}
</style></head><body__BODY_CLASS__>
<div id="alertbanner" role="alert" aria-live="assertive"></div>
<main>
<section id="view-monitor" class="view" aria-label="Live camera">
  <div id="cam" class="camera-frame">
    <img id="live-img" src="__STREAM__" alt="Live camera view">
    <div id="stream-error" class="stream-error" role="status">Camera stream is full. Try another viewer in a moment.</div>
    <div id="nightnote" class="nightnote">Night eye - low-light camera view. Radar and motion readings remain available.</div>
    <div class="cam-top">
      <div class="live-chip"><i></i>LIVE</div>
      <div id="cam-tools" class="cam-tools" aria-label="Camera controls"></div>
      __STATE_CHIP__
      <div id="readings" class="readings-overlay"></div>
      __CAMERA_CHIPS__
      __T2_ALERTS__
    </div>
    __ACTION_BAR__
    <div class="monitor-note">__PRIVACY_BADGE__</div>
  </div>
</section>
__TONIGHT_VIEW__
__ENGINEERING_VIEW__
</main>
__SOUND_SHEET__
__TABS__
<script>
const READINGS="__READINGS__",HISTORY="__HISTORY__",DIGEST="__DIGEST__",SOOTHE="__SOOTHE__",ALERTS="__ALERTS__",EVENTS="__EVENTS__",SNAPSHOT="__SNAPSHOT__",AUDIO="__AUDIO__",TALK="__TALK__",ROTATE=__ROTATE__,SENSORS=__SENSORS__;
let HIST={},STATE=null,LASTDIGEST=0,LASTHISTORY=0,activeSensor=SENSORS.length?SENSORS[0].key:"";
let snapshotFailures=0,LASTEVENTS=0;
const SEENT2SEQ={};
const HAS_STATE=!!SNAPSHOT,MODEURL=READINGS?READINGS.replace("/readings.json","/mode"):"";
async function loadDigest(){if(!DIGEST)return;const e=document.getElementById("digest-text");if(!e)return;
const now=Date.now();if(now-LASTDIGEST<60000 && e.dataset.loaded==="1")return;LASTDIGEST=now;
try{const r=await fetch(DIGEST,{cache:"no-store"});if(r.ok){const d=await r.json();
e.textContent=d.text||"I don't have enough history yet for a night summary.";}else{e.textContent="I don't have enough history yet for a night summary.";}}
catch(x){e.textContent="I don't have enough history yet for a night summary.";}e.dataset.loaded="1";}
function renderSoothe(d){const now=document.getElementById("soothe-now"),soothePlaying=d.playing==="talk"?null:d.playing;
if(now)now.textContent=d.talk?"playing your voice":(soothePlaying?("playing "+String(soothePlaying).replace(/_/g," ")):"Nothing playing");
const box=document.getElementById("soothe-btns");if(!box)return;box.innerHTML="";
const presets=d.presets||[];
addCurrentSootheControl(box,presets,soothePlaying);
if(d.default){const cb=document.createElement("button");cb.className="sbtn cry";
cb.textContent="Baby crying - comfort now";
cb.onclick=function(){soothePost("action=play&preset="+encodeURIComponent(d.default),"Playing "+String(d.default).replace(/_/g," "))};
box.appendChild(cb);}
const as=d.autosoothe||{enabled:false,preset:""};
addAutoSootheControl(box,presets,as,d.default||"");}
function presetText(p){return String(p.label||p.key).replace(/_/g," ");}
function presetSelect(presets,selected,placeholder){
const sel=document.createElement("select");sel.className="sselect";
const first=document.createElement("option");first.value="";first.textContent=placeholder;sel.appendChild(first);
presets.forEach(function(p){const opt=document.createElement("option");opt.value=p.key;
opt.textContent=presetText(p)+" · "+String(p.category||"sound");opt.selected=p.key===selected;sel.appendChild(opt);});
return sel;}
function addCurrentSootheControl(box,presets,playing){
const row=document.createElement("div");row.className="squick";
const wrap=document.createElement("div");const label=document.createElement("label");
label.textContent="Current sound";wrap.appendChild(label);
const sel=presetSelect(presets,playing||"","Choose sound...");
sel.onchange=function(){if(sel.value)soothePost("action=play&preset="+encodeURIComponent(sel.value),"Playing "+sel.options[sel.selectedIndex].textContent);};
wrap.appendChild(sel);row.appendChild(wrap);
const st=document.createElement("button");st.className="sbtn stop";st.textContent="Stop";
st.onclick=function(){soothePost("action=stop","Stopping sound")};row.appendChild(st);box.appendChild(row);}
function addAutoSootheControl(box,presets,as,defaultPreset){
const row=document.createElement("div");row.className="squick";
const wrap=document.createElement("div");const label=document.createElement("label");
label.textContent="Cry trigger sound";wrap.appendChild(label);
const selected=as.preset||defaultPreset||"";
const sel=presetSelect(presets,selected,"Choose sound...");
sel.onchange=function(){if(sel.value)autoPost(1,sel.value);};wrap.appendChild(sel);row.appendChild(wrap);
const tg=document.createElement("button");tg.className="sbtn"+(as.enabled?" on":"");
tg.textContent=as.enabled?"On":"Off";
tg.onclick=function(){autoPost(as.enabled?0:1, selected)};row.appendChild(tg);box.appendChild(row);}
function setSootheStatus(text){const s=document.getElementById("soothe-status");if(s)s.textContent=text||"";}
async function autoPost(enabled,preset){setSootheStatus(enabled?"Auto-soothe on":"Auto-soothe off");
try{await fetch(SOOTHE.replace("/soothe?","/autosoothe?")
+"&enabled="+enabled+"&preset="+encodeURIComponent(preset),{method:"POST",cache:"no-store"});}
catch(e){setSootheStatus("Could not reach auto-soothe");}loadSoothe();}
async function soothePost(qs,pending){setSootheStatus(pending||"Sending…");
try{const r=await fetch(SOOTHE+"&"+qs,{method:"POST",cache:"no-store"});
if(r.ok){const d=await r.json();renderSoothe(d);
if(d.ok===false){setSootheStatus("Could not play sound"+(d.reason?": "+d.reason:""));}
else if(d.playing){setSootheStatus("Playing "+String(d.playing).replace(/_/g," "));}
else{setSootheStatus("Stopped");}}else{setSootheStatus("Dashboard request failed");}}
catch(e){setSootheStatus("Could not reach player");}}
async function loadSoothe(){try{const r=await fetch(SOOTHE.replace("/soothe?","/soothe.json?"),{cache:"no-store"});
if(r.ok)renderSoothe(await r.json());}catch(e){}}
let LISTENCTX=null,LISTENABORT=null,LISTENNEXT=0,LISTENCARRY=new Uint8Array(0),LISTENON=false,LISTENPAUSED=false;
let TALKREC=null,TALKSTREAM=null,TALKCHUNKS=[],TALKTIMER=null,TALKING=false,TALKHELD=false;
function audioStatus(t){const s=el("audio-status");if(s)s.textContent=t||"";}
function setListenButton(){const b=el("listen-btn");if(!b)return;b.classList.toggle("on",LISTENON);b.textContent=LISTENON?"Listening":"Listen";}
function stopListen(msg){LISTENON=false;if(LISTENABORT)LISTENABORT.abort();LISTENABORT=null;
if(LISTENCTX){try{LISTENCTX.close();}catch(e){}}LISTENCTX=null;LISTENCARRY=new Uint8Array(0);setListenButton();if(msg)audioStatus(msg);}
function schedulePcm(chunk){if(!LISTENCTX||LISTENPAUSED||!chunk||!chunk.length)return;
let data=chunk;if(LISTENCARRY.length){data=new Uint8Array(LISTENCARRY.length+chunk.length);data.set(LISTENCARRY,0);data.set(chunk,LISTENCARRY.length);}
const even=data.length-(data.length%2);LISTENCARRY=data.slice(even);if(even<=0)return;
const view=new DataView(data.buffer,data.byteOffset,even),samples=even/2;
const buf=LISTENCTX.createBuffer(1,samples,16000),out=buf.getChannelData(0);
for(let i=0;i<samples;i++)out[i]=Math.max(-1,view.getInt16(i*2,true)/32768);
const src=LISTENCTX.createBufferSource();src.buffer=buf;src.connect(LISTENCTX.destination);
LISTENNEXT=Math.max(LISTENNEXT,LISTENCTX.currentTime+0.3);src.start(LISTENNEXT);LISTENNEXT+=buf.duration;}
async function startListen(){if(LISTENON||!AUDIO)return;try{const AC=window.AudioContext||window.webkitAudioContext;
if(!AC){audioStatus("Listen is not available in this browser.");return;}LISTENCTX=new AC();if(LISTENCTX.resume)await LISTENCTX.resume();
LISTENABORT=new AbortController();LISTENNEXT=LISTENCTX.currentTime+0.3;LISTENON=true;setListenButton();audioStatus("Listening");
const r=await fetch(AUDIO,{cache:"no-store",signal:LISTENABORT.signal});if(!r.ok||!r.body)throw new Error("audio");
const reader=r.body.getReader();while(LISTENON){const part=await reader.read();if(part.done)break;schedulePcm(part.value);}
if(LISTENON)stopListen("Listen stopped");}catch(e){if(LISTENON)stopListen("Could not start listen");}}
function chooseTalkMime(){const opts=["audio/webm;codecs=opus","audio/mp4","audio/ogg;codecs=opus"];
if(!window.MediaRecorder||!MediaRecorder.isTypeSupported)return "";
for(let i=0;i<opts.length;i++)if(MediaRecorder.isTypeSupported(opts[i]))return opts[i];return "";}
function restoreListenAfterTalk(){LISTENPAUSED=false;if(LISTENCTX&&LISTENON&&LISTENCTX.resume){try{LISTENCTX.resume();}catch(e){}}}
async function sendTalkBlob(blob){try{audioStatus("Sending talk");
const r=await fetch(TALK,{method:"POST",cache:"no-store",headers:{"Content-Type":blob.type||"audio/webm"},body:blob});
if(r.ok){const d=await r.json();audioStatus("Played "+Number(d.seconds||0).toFixed(1)+"s");}
else if(r.status===409)audioStatus("Talk is busy");
else if(r.status===413)audioStatus("Talk clip was too long");
else audioStatus("Talk failed");}catch(e){audioStatus("Could not send talk");}finally{restoreListenAfterTalk();}}
async function beginTalk(ev){if(TALKING||!TALK)return;ev.preventDefault();TALKHELD=true;
if(!window.isSecureContext){TALKHELD=false;audioStatus("Talk needs the https:// URL.");return;}
if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||!window.MediaRecorder){TALKHELD=false;audioStatus("Talk is not available in this browser.");return;}
try{LISTENPAUSED=true;if(LISTENCTX&&LISTENCTX.suspend){await LISTENCTX.suspend();
if(!TALKHELD){restoreListenAfterTalk();return;}}
const stream=await navigator.mediaDevices.getUserMedia({audio:true});
if(!TALKHELD){stream.getTracks().forEach(function(t){t.stop();});restoreListenAfterTalk();return;}
TALKSTREAM=stream;TALKCHUNKS=[];
const mime=chooseTalkMime(),opts=mime?{mimeType:mime}:{};TALKREC=new MediaRecorder(TALKSTREAM,opts);
TALKREC.ondataavailable=function(e){if(e.data&&e.data.size)TALKCHUNKS.push(e.data);};
TALKREC.onstop=function(){const type=TALKREC&&TALKREC.mimeType?TALKREC.mimeType:(TALKCHUNKS[0]&&TALKCHUNKS[0].type)||"audio/webm";
const blob=new Blob(TALKCHUNKS,{type:type});if(TALKSTREAM)TALKSTREAM.getTracks().forEach(function(t){t.stop();});
TALKSTREAM=null;TALKING=false;TALKHELD=false;const b=el("talk-btn");if(b)b.classList.remove("talking");if(blob.size)sendTalkBlob(blob);else restoreListenAfterTalk();};
TALKREC.start();TALKING=true;const b=el("talk-btn");if(b){b.classList.add("talking");try{b.setPointerCapture(ev.pointerId);}catch(e){}}
audioStatus("Talking");TALKTIMER=setTimeout(endTalk,20000);}catch(e){TALKING=false;TALKHELD=false;audioStatus("Could not start talk");restoreListenAfterTalk();}}
function endTalk(ev){if(ev&&ev.preventDefault)ev.preventDefault();TALKHELD=false;if(TALKTIMER){clearTimeout(TALKTIMER);TALKTIMER=null;}
if(TALKREC&&TALKREC.state!=="inactive")TALKREC.stop();}
function setupAudioControls(){const lb=el("listen-btn"),tb=el("talk-btn");if(!lb||!tb)return;
lb.onclick=function(){LISTENON?stopListen("Listen off"):startListen();};
if(!window.isSecureContext){tb.disabled=true;audioStatus("Talk needs the https:// URL.");return;}
tb.addEventListener("pointerdown",beginTalk);tb.addEventListener("pointerup",endTalk);tb.addEventListener("pointercancel",endTalk);}
const ORDER=["temperature","humidity","pressure","air","light","presence","vitals"];
let LASTMODE={};
function el(id){return document.getElementById(id);}
function text(id,value){const n=el(id);if(n)n.textContent=value;}
function formatAge(v){return typeof v==="number"?Math.max(0,Math.round(v))+"s ago":"age unknown";}
function formatNum(v,d){return typeof v==="number"?v.toFixed(d).replace(/\\.0$/,""):null;}
function tsTime(ts){if(!ts)return "";const ms=ts<1000000000000?ts*1000:ts;
try{return new Date(ms).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});}catch(e){return "";}}
function setHidden(id,hidden){const n=el(id);if(n)n.hidden=hidden;}
function makePill(txt,cls){const s=document.createElement("span");s.className=cls||"reading-pill";s.textContent=txt;return s;}
function makeOverlayButton(txt,cls,handler,label){const b=document.createElement("button");b.type="button";b.className=cls;
b.textContent=txt;if(label)b.setAttribute("aria-label",label);b.onclick=handler;return b;}
function applyMode(mode){document.body.classList.toggle("night",mode==="night");
document.body.classList.toggle("day",mode!=="night");const nn=el("nightnote");
if(nn)nn.style.display=(mode==="night")?"block":"none";const cam=el("cam");
if(cam)cam.classList.toggle("night",mode==="night");}
function renderOverlay(items,mode,modeAuto){const r=el("readings"),tools=el("cam-tools");
if(tools){tools.innerHTML="";
if(mode && MODEURL){tools.appendChild(makeOverlayButton((mode==="night"?"Night":"Day")+(modeAuto?" · auto":" · manual"),"mode-btn",cycleMode,"Camera mode"));
LASTMODE={mode:mode,mode_auto:!!modeAuto};}
tools.appendChild(makeOverlayButton("Rotate "+curRot+"°","rot-btn",cycleRot,"Rotate video"));}
if(r){r.innerHTML="";items.forEach(function(item){if(item)r.appendChild(makePill(item));});}
applyMode(mode);}
function renderReadings(d){const el=document.getElementById("readings");el.innerHTML="";
const items=[];ORDER.forEach(function(k){if(d[k])items.push(d[k]);});renderOverlay(items,d.mode,d.mode_auto);}
function overlayFromSnapshot(d){const items=[],vitals=d.vitals||{};
if(vitals.respiratory_rate!==null&&vitals.respiratory_rate!==undefined)items.push("breathing "+formatNum(vitals.respiratory_rate,0)+"/min");
const vision=d.vision||{};renderOverlay(items,vision.mode,vision.mode_auto);}
async function cycleMode(){const set=LASTMODE.mode_auto?"day":(LASTMODE.mode==="day"?"night":"");
if(!MODEURL)return;try{await fetch(MODEURL+"&set="+set,{method:"POST",cache:"no-store"});}catch(e){}
if(SNAPSHOT){loadSnapshot(true);return;}
try{const r=await fetch(READINGS,{cache:"no-store"});if(r.ok)renderReadings(await r.json());}catch(e){}}
async function pollReadings(){if(!READINGS||SNAPSHOT)return;try{const r=await fetch(READINGS,{cache:"no-store"});
if(r.ok)renderReadings(await r.json());}catch(e){}setTimeout(pollReadings,3000);}
function renderStateUnavailable(){text("state-chip","State unavailable");text("state-label","Monitor unreachable — it may be offline. Live camera may still work.");
text("confidence-line","");text("since-line","");text("action-label","Check the camera");text("action-detail","Use the live view for a direct look.");
setHidden("room-action",true);renderActivity(null);renderRoomChip({});renderT2Alerts([]);
const r=el("readings");if(r&&!r.childElementCount)renderOverlay([],LASTMODE.mode,LASTMODE.mode_auto);}
function renderHealth(h){["camera","readings","radar","history"].forEach(function(k){const item=h&&h[k]?h[k]:{status:"missing"};
const n=el("health-"+k);if(!n)return;const status=String(item.status||"missing");
n.className="health-dot "+status;n.setAttribute("aria-label",k+" "+status);const s=n.querySelector("span");if(s)s.textContent=k;});}
function setCard(id,value,age,extra,hide){const card=el("card-"+id);if(!card)return;card.hidden=!!hide;
text("val-"+id,value);text("age-"+id,age||"");text("extra-"+id,extra||"");}
function setChip(id,value){const n=el(id);if(!n)return;n.textContent=value||"";n.hidden=!value;}
function roomChipPart(room,key,dec,unit,label){const o=room&&room[key]?room[key]:{},v=o.value;
if(!(typeof v==="number"&&isFinite(v)))return "";const n=formatNum(v,dec);return n===null?"":n+(unit?(" "+unit):"")+(label?(" "+label):"");}
function renderRoomChip(room){const parts=[],t=roomChipPart(room,"temperature_c",1,"°C",""),h=roomChipPart(room,"humidity_pct",0,"%","humidity");
if(t)parts.push(t);if(h)parts.push(h);setChip("camera-chip-room",parts.join(" · "));}
function renderActivity(d){const box=el("activity-slider"),track=el("activity-track"),thumb=el("activity-thumb"),cap=el("activity-caption");
if(!box||!track||!thumb||!cap)return;const v=d&&typeof d.arousal_score==="number"&&isFinite(d.arousal_score)?d.arousal_score:null;
if(v===null){track.classList.add("dim");cap.textContent="no reading";box.setAttribute("aria-label","Activity: no reading");return;}
const pct=Math.max(0,Math.min(1,v))*100;thumb.style.left=pct+"%";track.classList.remove("dim");cap.textContent="";
box.setAttribute("aria-label","Activity: "+Math.round(pct)+" percent between Still and Moving");}
function renderSensorCards(d){const room=d.room||{},presence=d.presence||{},motion=d.motion||{},vitals=d.vitals||{};
function rv(key,unit,dec){const o=room[key]||{};return o.value===null||o.value===undefined?["no reading",formatAge(o.age_s)]:
[formatNum(o.value,dec)+(unit?(" "+unit):""),formatAge(o.age_s)];}
let v=rv("temperature_c","°C",1);setCard("temp",v[0],v[1],"",false);
v=rv("humidity_pct","%",0);setCard("humidity",v[0],v[1],"",false);
v=rv("pressure_hpa","hPa",0);setCard("pressure",v[0],v[1],"",false);
v=rv("gas_kohm","kΩ",1);setCard("air",v[0],v[1],"",false);
v=rv("illuminance_lx","lux",0);setCard("light",v[0],v[1],"",false);
let pv="No presence reading";if(presence.value===true)pv="Presence detected";else if(presence.value===false)pv="No one detected";
let pextra="";if(typeof presence.target_distance_cm==="number")pextra=Math.round(presence.target_distance_cm)+" cm";
setCard("presence",pv,formatAge(presence.age_s),pextra,false);
let mv=motion.value===null||motion.value===undefined?"no reading":(motion.value?"Movement detected":"No movement detected");
let mextra=typeof motion.transitions_window==="number"?motion.transitions_window+" changes in history window":"";
setCard("motion",mv,formatAge(motion.age_s),mextra,false);
const rr=vitals.respiratory_rate;if(rr===null||rr===undefined){setCard("vitals","","","",true);}
else{let vv="breathing "+formatNum(rr,0)+"/min";if(vitals.heart_rate_bpm!==null&&vitals.heart_rate_bpm!==undefined)vv+=" · heart "+formatNum(vitals.heart_rate_bpm,0)+" bpm";
setCard("vitals",vv,formatAge(vitals.age_s),"rough radar estimate",false);}}
function renderAction(d){const a=d.recommended_action||{},card=el("action-card");
text("action-label",a.label||"No suggested action");text("action-detail",a.detail||"Based on the current readings.");
if(card){const canGo=a.key==="comfort_now"&&!!SOOTHE;card.classList.toggle("actionable",canGo);
card.setAttribute("role",canGo?"button":"group");card.tabIndex=canGo?0:-1;card.onclick=canGo?function(){openSoundSheet();}:null;
card.onkeydown=canGo?function(ev){if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();card.click();}}:null;}
const room=d.room_action,rc=el("room-action");if(!rc)return;if(room){setHidden("room-action",false);
text("room-action-label",room.label||"Check the room");text("room-action-detail",room.detail||"The readings need a direct look.");}
else setHidden("room-action",true);}
function notifyT2(item){const seq=item&&typeof item.seq==="number"?item.seq:null;
if(seq===null||SEENT2SEQ[seq])return;SEENT2SEQ[seq]=true;
try{if(item.notification&&item.notification.browser&&"Notification" in window&&Notification.permission==="granted")
new Notification(item.title||"Attention",{body:item.message||""});}catch(e){}}
function renderT2Alerts(alerts){const box=el("t2-alerts");if(!box)return;box.innerHTML="";
(alerts||[]).filter(function(a){return a&&a.tier==="T2"&&a.active;}).forEach(function(a){
notifyT2(a);const card=document.createElement("div");card.className="t2-alert-card";
const title=document.createElement("div");title.className="t2-alert-title";title.textContent=a.title||"Attention";card.appendChild(title);
const msg=document.createElement("div");msg.className="t2-alert-message";msg.textContent=a.message||"";card.appendChild(msg);
const action=a.action||{};if(action.label){const act=document.createElement("div");act.className="t2-alert-action";act.textContent=action.label;card.appendChild(act);}
box.appendChild(card);});box.hidden=!box.childElementCount;}
function renderSnapshot(d){STATE=d;snapshotFailures=0;renderHealth(d.health||{});overlayFromSnapshot(d);renderActivity(d);renderRoomChip(d.room||{});
text("state-chip",d.label||"Reading the room...");text("state-label",d.label||"Reading the room...");
const c=d.confidence||{};text("confidence-line",c.band?("confidence: "+c.band+(c.basis?" · "+c.basis:"")):"");
const since=tsTime(d.since_ts);text("since-line",since?"since "+since:"");renderAction(d);renderT2Alerts(d.alerts||[]);renderSensorCards(d);}
let SNAPTIMER=null;
async function loadSnapshot(force){if(!SNAPSHOT)return;
if(SNAPTIMER){clearTimeout(SNAPTIMER);SNAPTIMER=null;}
try{const r=await fetch(SNAPSHOT,{cache:"no-store"});
if(!r.ok)throw new Error("snapshot");const d=await r.json();
if(d&&d.error==="snapshot_unavailable"){renderStateUnavailable();}else{renderSnapshot(d);}}
catch(e){snapshotFailures++;if(force||snapshotFailures>=2||!STATE)renderStateUnavailable();}
SNAPTIMER=setTimeout(loadSnapshot,3000);}
function eventSeenTs(e){if(!e)return null;
if(typeof e.end==="number")return e.end;if(typeof e.ended_ts==="number")return e.ended_ts;
if(e.end===null||e.ended_ts===null)return Date.now()/1000;
if(typeof e.start==="number")return e.start;if(typeof e.started_ts==="number")return e.started_ts;return null;}
function caregiverAge(ts){const age=Math.max(0,Date.now()/1000-ts);
if(age<90)return "just now";if(age<3600)return Math.min(59,Math.max(1,Math.round(age/60)))+"m ago";
return Math.max(1,Math.round(age/3600))+"h ago";}
function renderCaregiverChip(d){const events=d&&Array.isArray(d.events)?d.events:[];let latest=null;
events.forEach(function(e){if(!e||e.kind!=="caregiver_present")return;const ts=eventSeenTs(e);
if(ts!==null&&(latest===null||ts>latest))latest=ts;});
setChip("camera-chip-caregiver",latest===null?"":"Caregiver seen "+caregiverAge(latest));}
function fmtDuration(s){if(!(typeof s==="number"&&isFinite(s))||s<0)return "";
if(s<60)return "under a minute";const m=Math.round(s/60);if(m<60)return m+" min";
const h=Math.floor(m/60),r=m%60;return h+"h"+(r?" "+r+"m":"");}
function renderCryingCard(d){const list=el("crying-list"),count=el("crying-count");if(!list||!count)return;
if(!d){count.textContent="no data";list.textContent="Crying history is unavailable right now.";return;}
const wh=fmtWindowHours(d.window_hours);
const rows=(Array.isArray(d.events)?d.events:[]).filter(function(e){
return e&&e.kind==="crying"&&typeof e.started_ts==="number";})
.sort(function(a,b){return b.started_ts-a.started_ts;});
if(!rows.length){count.textContent="none heard · last "+wh+"h";
list.textContent="No crying heard in this window.";return;}
count.textContent=rows.length+(rows.length===1?" episode":" episodes")+" · last "+wh+"h";
list.innerHTML="";rows.slice(0,8).forEach(function(e){
const row=document.createElement("div");row.className="crying-row";
const when=document.createElement("span");when.className="cry-when";when.textContent=tsTime(e.started_ts)||"--:--";
const label=document.createElement("span");label.textContent="Crying heard";
const dur=document.createElement("span");dur.className="cry-dur";
if(e.ended_ts===null||e.ended_ts===undefined)dur.textContent="ongoing";
else dur.textContent=fmtDuration(e.ended_ts-e.started_ts)||"brief";
row.appendChild(when);row.appendChild(label);row.appendChild(dur);list.appendChild(row);});
if(rows.length>8){const more=document.createElement("div");more.className="cry-more";
more.textContent="+"+(rows.length-8)+" earlier in this window";list.appendChild(more);}}
function renderEvents(d){renderCaregiverChip(d);renderCryingCard(d);}
async function loadEvents(force){if(!EVENTS)return;const now=Date.now();if(!force&&now-LASTEVENTS<15000)return;LASTEVENTS=now;
try{const r=await fetch(EVENTS,{cache:"no-store"});if(r.ok)renderEvents(await r.json());else renderEvents(null);}
catch(e){renderEvents(null);}}
function visibleNow(n){if(!n||n.offsetParent===null)return false;const r=n.getBoundingClientRect(),vh=window.innerHeight||document.documentElement.clientHeight||0;
return r.bottom>=0&&r.top<=vh;}
function historyNeeded(){const eng=el("engineering"),donut=el("motion-donut-card");
return !!((eng&&eng.open)||(donut&&donut.open&&visibleNow(donut)));}
function fmtTime(t){const d=new Date(t*1000);
return ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2);}
function fmtWindowHours(h){if(!(typeof h==="number"&&isFinite(h)&&h>0))return "--";
const v=h>=10?Math.round(h):(Math.round(h*10)/10);return String(Math.max(.1,v)).replace(/\\.0$/,"");}
function motionPoints(h){const pts=h&&Array.isArray(h.points)?h.points:[];return pts.map(function(q){return [Number(q[0]),Number(q[1])];})
.filter(function(q){return isFinite(q[0])&&(q[1]===0||q[1]===1);}).sort(function(a,b){return a[0]-b[0];});}
function medianGap(g){if(!g.length)return 0;const a=g.slice().sort(function(x,y){return x-y;}),m=Math.floor(a.length/2);
return a.length%2?a[m]:(a[m-1]+a[m])/2;}
function setMotionLegend(m,s,n){const total=m+s+n,mp=total?Math.round(m/total*100):0,sp=total?Math.round(s/total*100):0,np=total?Math.round(n/total*100):0;
text("motion-pct-moving",mp+"%");text("motion-pct-still",sp+"%");text("motion-pct-missing",np+"%");}
function donutArc(ctx,cx,cy,r,w,a0,a1,color){if(a1<=a0)return;ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=w;ctx.arc(cx,cy,r,a0,a1);ctx.stroke();}
function drawMotionDonut(){const card=el("motion-donut-card");if(!card)return;const h=HIST.motion_detected||{},p=motionPoints(h);
let wh=typeof HIST.window_hours==="number"?HIST.window_hours:null;if((wh===null||!isFinite(wh)||wh<=0)&&p.length>1)wh=(p[p.length-1][0]-p[0][0])/3600;
text("motion-window",fmtWindowHours(wh));const cv=el("motion-donut"),empty=el("motion-donut-empty");if(!cv)return;
const ctx=cv.getContext("2d");if(!ctx)return;const size=cv.clientWidth||92,scale=window.devicePixelRatio||1;cv.width=size*scale;cv.height=size*scale;ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,size,size);
if(p.length<2){if(empty)empty.hidden=false;setMotionLegend(0,0,0);return;}
const gaps=[];for(let i=0;i<p.length-1;i++){const dt=p[i+1][0]-p[i][0];if(dt>0)gaps.push(dt);}
const med=medianGap(gaps);let moving=0,still=0,missing=0;for(let i=0;i<p.length-1;i++){const dt=p[i+1][0]-p[i][0];if(dt<=0)continue;
if(med&&dt>2*med)missing+=dt;else if(p[i][1]===1)moving+=dt;else still+=dt;}
const total=moving+still+missing;if(total<=0){if(empty)empty.hidden=false;setMotionLegend(0,0,0);return;}
if(empty)empty.hidden=true;setMotionLegend(moving,still,missing);const cx=size/2,cy=size/2,r=size/2-9,w=14;let a=-Math.PI/2;
[[moving,"#58C7B0"],[still,"#6D7672"],[missing,"#2B302E"]].forEach(function(seg){const next=a+seg[0]/total*Math.PI*2;donutArc(ctx,cx,cy,r,w,a,next,seg[1]);a=next;});}
async function loadHistory(force){if(!HISTORY)return;if(!force&&!historyNeeded())return;const now=Date.now();
if(!force&&now-LASTHISTORY<5000)return;LASTHISTORY=now;try{const r=await fetch(HISTORY,{cache:"no-store"});
if(r.ok)HIST=await r.json();}catch(e){}
SENSORS.forEach(function(s){const h=HIST[s.key];if(!h)return;
const c=document.getElementById("cur-"+s.key);const n=h.points.length;
if(c)c.textContent=n?(s.bool?(h.points[n-1][1]?"yes":"no")
:(h.points[n-1][1]+(h.unit?" "+h.unit:""))):"no reading";});
drawMotionDonut();draw();}
function historyTick(){loadHistory(false);setTimeout(historyTick,5000);}
function selectSensor(key){activeSensor=key;document.querySelectorAll(".sensor-chip").forEach(function(b){b.classList.toggle("active",b.dataset.sensor===key);});
document.querySelectorAll(".chart-panel").forEach(function(p){p.hidden=p.id!=="p-"+key;});loadHistory(true);}
function draw(){const eng=el("engineering");if(eng&&!eng.open)return;
const s=SENSORS.find(function(x){return x.key===activeSensor});if(!s)return;
const h=HIST[s.key];const cv=document.getElementById("cv-"+s.key);if(!cv||!h)return;
const ctx=cv.getContext("2d"),W=cv.width=cv.clientWidth*2,H=cv.height=600;
ctx.clearRect(0,0,W,H);const p=h.points||[];
if(p.length<2){ctx.fillStyle="#B8B0A6";ctx.font="30px sans-serif";
ctx.fillText("Collecting readings...",30,60);return;}
const ys=p.map(function(q){return q[1]});let mn=Math.min.apply(0,ys),mx=Math.max.apply(0,ys);
if(h.bool){mn=0;mx=1;}if(mn===mx){mn-=1;mx+=1;}
const x0=p[0][0],x1=p[p.length-1][0]||x0+1,pad=70;
function X(t){return pad+(t-x0)/((x1-x0)||1)*(W-1.3*pad);}
function Y(v){return H-pad-(v-mn)/((mx-mn)||1)*(H-2*pad);}
ctx.strokeStyle="#2B302E";ctx.lineWidth=2;ctx.beginPath();
ctx.moveTo(pad,pad);ctx.lineTo(pad,H-pad);ctx.lineTo(W-10,H-pad);ctx.stroke();
ctx.fillStyle="#B8B0A6";ctx.font="26px sans-serif";
ctx.fillText(mx.toFixed(h.bool?0:1),8,pad+18);ctx.fillText(mn.toFixed(h.bool?0:1),8,H-pad);
[0,1/3,2/3,1].forEach(function(f,i,arr){const t=x0+f*(x1-x0),x=X(t);
ctx.strokeStyle="#2B302E";ctx.beginPath();ctx.moveTo(x,H-pad);ctx.lineTo(x,H-pad+10);ctx.stroke();
ctx.textAlign=i===0?"left":(i===arr.length-1?"right":"center");
ctx.fillText(fmtTime(t),x,H-pad+44);});
ctx.textAlign="start";
ctx.strokeStyle="#58C7B0";ctx.lineWidth=4;ctx.beginPath();
p.forEach(function(q,i){const x=X(q[0]),y=Y(q[1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
ctx.stroke();}
let curRot=parseInt(localStorage.getItem("beddingtonRotate"));if(isNaN(curRot))curRot=ROTATE;
function applyRot(){var ci=document.querySelector("#cam img");if(ci)ci.className=curRot?("rot"+curRot):"";}
function cycleRot(){curRot=(curRot+90)%360;try{localStorage.setItem("beddingtonRotate",curRot);}catch(e){}
applyRot();var rb=document.querySelector(".rot-btn");if(rb)rb.textContent="Rotate "+curRot+"°";}
applyRot();
const liveImg=document.getElementById("live-img");if(liveImg)liveImg.onerror=function(){const e=el("stream-error");if(e)e.style.display="block";};
document.querySelectorAll(".sensor-chip").forEach(function(b){b.onclick=function(){selectSensor(b.dataset.sensor);};});
const engineering=el("engineering");if(engineering)engineering.addEventListener("toggle",function(){if(engineering.open)selectSensor(activeSensor);});
const donutCard=el("motion-donut-card");if(donutCard)donutCard.addEventListener("toggle",function(){if(donutCard.open)loadHistory(true);});
window.addEventListener("scroll",function(){loadHistory(false);},{passive:true});
window.addEventListener("resize",function(){drawMotionDonut();draw();},{passive:true});
// --- LAN cry-alert: poll /alerts.json, show banner, beep + notify on new alert ---
let ALERTCTX=null,ALERTGESTURE=false,LASTALERTSEQ=-1;
function alertUnlock(){if(ALERTGESTURE)return;ALERTGESTURE=true;
try{if("Notification" in window && Notification.permission==="default")
Notification.requestPermission();}catch(e){}
try{const AC=window.AudioContext||window.webkitAudioContext;
if(AC){if(!ALERTCTX)ALERTCTX=new AC();if(ALERTCTX.resume)ALERTCTX.resume();}}catch(e){}}
function alertBeep(){try{const AC=window.AudioContext||window.webkitAudioContext;
if(!AC)return;if(!ALERTCTX)ALERTCTX=new AC();if(ALERTCTX.resume)ALERTCTX.resume();
const ctx=ALERTCTX,t0=ctx.currentTime;
for(let i=0;i<4;i++){const o=ctx.createOscillator(),g=ctx.createGain();
o.type="square";o.frequency.value=i%2?880:1320;const s=t0+i*0.28;
g.gain.setValueAtTime(0.0001,s);g.gain.exponentialRampToValueAtTime(0.6,s+0.02);
g.gain.exponentialRampToValueAtTime(0.0001,s+0.22);
o.connect(g);g.connect(ctx.destination);o.start(s);o.stop(s+0.24);}}catch(e){}}
function alertNotify(title,message){try{if(!("Notification" in window))return;
if(Notification.permission==="granted")new Notification(title,{body:message});}catch(e){}}
function showAlert(d){const b=document.getElementById("alertbanner");if(!b)return;
b.textContent="🔔 "+(d.title||"Alert")+" — "+(d.message||"");b.style.display="block";}
function hideAlert(){const b=document.getElementById("alertbanner");if(b)b.style.display="none";}
async function pollAlerts(){if(!ALERTS)return;
try{const r=await fetch(ALERTS,{cache:"no-store"});if(!r.ok)return;const d=await r.json();
if(d && d.active){showAlert(d);
if(typeof d.seq==="number" && d.seq!==LASTALERTSEQ){LASTALERTSEQ=d.seq;
alertBeep();alertNotify(d.title||"Alert",d.message||"");}}
else{hideAlert();}}catch(e){}}
document.addEventListener("click",alertUnlock,{once:false});
document.addEventListener("touchstart",alertUnlock,{once:false});
if(ALERTS){pollAlerts();setInterval(pollAlerts,2500);}
if(EVENTS){loadEvents(true);setInterval(function(){loadEvents(false);},15000);}
if(AUDIO&&TALK){setupAudioControls();window.addEventListener("pagehide",function(){stopListen();});}
if(DIGEST){loadDigest();setInterval(loadDigest,60000);}
if(SOOTHE)loadSoothe();
if(SNAPSHOT)loadSnapshot(true);else pollReadings();
if(HISTORY){drawMotionDonut();historyTick();}
// --- tab bar + sound sheet ---
function openSoundSheet(){const s=el("sound-sheet");if(!s)return;s.classList.add("open");loadSoothe();}
function closeSoundSheet(){const s=el("sound-sheet");if(s)s.classList.remove("open");}
function switchView(name){document.querySelectorAll(".view").forEach(function(v){v.hidden=v.id!=="view-"+name;});
document.querySelectorAll(".tab-btn").forEach(function(b){b.classList.toggle("active",b.dataset.view===name);});
if(name==="eng"){const eng=el("engineering");
if(eng&&!eng.open)eng.open=true;else selectSensor(activeSensor);loadHistory(true);}
if(name==="tonight"){loadDigest();loadEvents(true);loadHistory(true);}
window.scrollTo(0,0);}
document.querySelectorAll(".tab-btn").forEach(function(b){b.onclick=function(){switchView(b.dataset.view);};});
const soundBtn=el("sound-btn");if(soundBtn)soundBtn.onclick=openSoundSheet;
const soundSheetEl=el("sound-sheet");if(soundSheetEl){const bd=soundSheetEl.querySelector(".sheet-backdrop");
if(bd)bd.onclick=closeSoundSheet;}
document.addEventListener("keydown",function(ev){if(ev.key==="Escape")closeSoundSheet();});
</script></body></html>"""


def day_night_mode(
    lux: float,
    previous: str = "day",
    *,
    dark_below: float = 10.0,
    light_above: float = 30.0,
) -> str:
    """Day or night from the light level, with hysteresis so it does not flap at
    dusk: switch to night only when clearly dark, back to day only when clearly
    lit. Returns ``previous`` while the lux sits in the in-between band."""
    if previous == "night":
        return "day" if lux > light_above else "night"
    return "night" if lux < dark_below else "day"


def _dashboard_page(
    stream_path: str,
    readings_path: str,
    history_path: str,
    digest_path: str,
    soothe_path: str,
    audio_path: str,
    talk_path: str,
    sensors: tuple[dict[str, object], ...],
    title: str,
    rotate: int = 0,
    alerts_path: str = "",
    snapshot_path: str = "",
    events_path: str = "",
) -> str:
    spec = json.dumps(
        [
            {
                "key": s["key"],
                "label": s["label"],
                "unit": s.get("unit", ""),
                "bool": bool(s.get("bool", False)),
            }
            for s in sensors
        ]
    )
    state_chip = ""
    t2_alerts = ""
    health_dots = ""
    eng_state = ""
    camera_chips = ""
    if snapshot_path or events_path:
        camera_chips = '<div id="camera-chips" class="camera-chips" aria-label="Camera context">'
        if snapshot_path:
            camera_chips += (
                '<div id="camera-chip-room" class="camera-chip" '
                'aria-label="Room readings" hidden></div>'
            )
        if events_path:
            camera_chips += (
                '<div id="camera-chip-caregiver" class="camera-chip" '
                'aria-label="Caregiver observation" hidden></div>'
            )
        camera_chips += "</div>"
    if snapshot_path:
        state_chip = (
            '<div id="state-chip" class="state-chip" aria-live="polite">'
            "Reading the room...</div>"
        )
        t2_alerts = (
            '<section id="t2-alerts" class="t2-alerts" aria-live="polite" hidden></section>'
        )
        health_dots = (
            '<div id="health-dots" class="health-dots" aria-label="Device health">'
            '<span id="health-camera" class="health-dot" aria-label="camera missing"><span>camera</span></span>'
            '<span id="health-readings" class="health-dot" aria-label="readings missing"><span>readings</span></span>'
            '<span id="health-radar" class="health-dot" aria-label="radar missing"><span>radar</span></span>'
            '<span id="health-history" class="health-dot" aria-label="history missing"><span>history</span></span>'
            "</div>"
        )
        eng_state = (
            '<section id="state-home" class="state-grid">'
            '<section id="state-hero" class="BabyStateHero state-hero" aria-live="polite" aria-label="Baby state">'
            '<div id="state-label" class="state-label">Reading the room...</div>'
            '<div id="confidence-line" class="meta-line"></div>'
            '<div id="since-line" class="meta-line"></div>'
            '<div id="activity-slider" class="activity-slider" role="img" aria-label="Activity: no reading">'
            '<div class="activity-labels"><span>Still</span><span>Moving</span></div>'
            '<div id="activity-track" class="activity-track dim">'
            '<span id="activity-thumb" class="activity-thumb"></span>'
            "</div>"
            '<div id="activity-caption" class="activity-caption">no reading</div>'
            "</div>"
            "</section>"
            '<section id="action-panel" class="action-panel" aria-label="Suggested action">'
            '<div id="action-card" class="action-card" role="group">'
            '<div id="action-label" class="action-label">Reading the room...</div>'
            '<p id="action-detail" class="action-detail">Current readings will appear here.</p>'
            "</div>"
            '<div id="room-action" class="room-action-card" hidden>'
            '<div id="room-action-label" class="action-label">Check the room</div>'
            '<p id="room-action-detail" class="action-detail">The readings need a direct look.</p>'
            "</div>"
            "</section>"
            "</section>"
            '<section id="sensor-area" class="sensor-area">'
            '<div id="sensor-cards" class="sensor-cards" aria-label="Current readings">'
            '<div id="card-temp" class="sensor-card"><div class="sensor-name">Temp</div><div id="val-temp" class="sensor-value">no reading</div><div id="age-temp" class="sensor-age"></div><div id="extra-temp" class="sensor-extra"></div></div>'
            '<div id="card-humidity" class="sensor-card"><div class="sensor-name">Humidity</div><div id="val-humidity" class="sensor-value">no reading</div><div id="age-humidity" class="sensor-age"></div><div id="extra-humidity" class="sensor-extra"></div></div>'
            '<div id="card-pressure" class="sensor-card"><div class="sensor-name">Pressure</div><div id="val-pressure" class="sensor-value">no reading</div><div id="age-pressure" class="sensor-age"></div><div id="extra-pressure" class="sensor-extra"></div></div>'
            '<div id="card-air" class="sensor-card"><div class="sensor-name">Air</div><div id="val-air" class="sensor-value">no reading</div><div id="age-air" class="sensor-age"></div><div id="extra-air" class="sensor-extra"></div></div>'
            '<div id="card-light" class="sensor-card"><div class="sensor-name">Light</div><div id="val-light" class="sensor-value">no reading</div><div id="age-light" class="sensor-age"></div><div id="extra-light" class="sensor-extra"></div></div>'
            '<div id="card-presence" class="sensor-card"><div class="sensor-name">Presence</div><div id="val-presence" class="sensor-value">No presence reading</div><div id="age-presence" class="sensor-age"></div><div id="extra-presence" class="sensor-extra"></div></div>'
            '<div id="card-motion" class="sensor-card"><div class="sensor-name">Motion</div><div id="val-motion" class="sensor-value">no reading</div><div id="age-motion" class="sensor-age"></div><div id="extra-motion" class="sensor-extra"></div></div>'
            '<div id="card-vitals" class="sensor-card" hidden><div class="sensor-name">Vitals</div><div id="val-vitals" class="sensor-value"></div><div id="age-vitals" class="sensor-age"></div><div id="extra-vitals" class="sensor-extra">rough radar estimate</div></div>'
            "</div>"
            "</section>"
        )
    tonight_card = (
        '<details id="tonight" class="card tonight-card summary-card" open>'
        "<summary>Night summary</summary>"
        '<div id="digest-text" class="digest">I don\'t have enough history yet for a night summary.</div>'
        "</details>"
        if digest_path
        else ""
    )
    motion_card = (
        '<details id="motion-donut-card" class="card motion-donut-card summary-card" aria-label="Motion summary" open>'
        '<summary id="motion-donut-title"><span>Motion · last <span id="motion-window">--</span>h</span></summary>'
        '<div class="motion-donut-body">'
        '<div class="motion-donut-canvas">'
        '<canvas id="motion-donut" role="img" aria-label="Motion chart"></canvas>'
        '<div id="motion-donut-empty" class="motion-donut-empty">Collecting readings...</div>'
        "</div>"
        '<div id="motion-legend" class="motion-legend" aria-label="Motion legend">'
        '<div class="motion-legend-row"><span class="motion-dot moving"></span><span>Moving</span><span id="motion-pct-moving">0%</span></div>'
        '<div class="motion-legend-row"><span class="motion-dot still"></span><span>Still</span><span id="motion-pct-still">0%</span></div>'
        '<div class="motion-legend-row"><span class="motion-dot missing"></span><span>No reading</span><span id="motion-pct-missing">0%</span></div>'
        "</div>"
        "</div>"
        "</details>"
        if history_path
        else ""
    )
    crying_card = (
        '<details id="crying-card" class="card crying-card summary-card" aria-label="Crying summary" open>'
        '<summary id="crying-title"><span>Crying · <span id="crying-count">no data yet</span></span></summary>'
        '<div id="crying-list" class="crying-list">Collecting observations...</div>'
        "</details>"
        if events_path
        else ""
    )
    digest_section = (
        f'<section id="summary-row" class="summary-row">{tonight_card}{motion_card}{crying_card}</section>'
        if tonight_card or motion_card or crying_card
        else ""
    )
    soothe_section = (
        '<section id="soothe" class="soothe-section">'
        '<h2 class="section-title">Soothe</h2>'
        '<div class="cur" id="soothe-now">Loading...</div>'
        '<div id="soothe-status" class="sstatus"></div>'
        '<div id="soothe-btns" class="sbtns"></div>'
        "</section>"
        if soothe_path
        else ""
    )
    audio_enabled = bool(audio_path and talk_path)
    privacy_badge = (
        "LAN only · no cloud · live audio available · nothing recorded"
        if audio_enabled
        else "LAN only · no cloud · no recording · no audio streaming"
    )
    audio_section = (
        '<section id="audio" class="audio-section" aria-label="Live audio">'
        '<div class="audio-controls">'
        '<button id="listen-btn" type="button" class="audio-btn">Listen</button>'
        '<button id="talk-btn" type="button" class="audio-btn">Hold to talk</button>'
        "</div>"
        '<div id="audio-status" class="audio-status" role="status"></div>'
        "</section>"
        if audio_enabled
        else ""
    )
    sensor_buttons = ""
    sensor_charts = ""
    if history_path:
        for index, sensor in enumerate(sensors):
            key = _html_attr(sensor["key"])
            label = _html_attr(sensor["label"])
            active = " active" if index == 0 else ""
            hidden = "" if index == 0 else " hidden"
            sensor_buttons += (
                f'<button type="button" class="sensor-chip{active}" '
                f'data-sensor="{key}">{label}</button>'
            )
            sensor_charts += (
                f'<div class="chart-panel" id="p-{key}"{hidden}>'
                '<div class="chartwrap">'
                f'<div class="cur" id="cur-{key}">Collecting readings...</div>'
                f'<canvas id="cv-{key}"></canvas>'
                "</div></div>"
            )
    engineering_section = (
        '<details id="engineering" class="engineering">'
        "<summary>Charts</summary>"
        '<div id="sensor-picks" class="sensor-picks" aria-label="Sensor charts">'
        f"{sensor_buttons}"
        "</div>"
        '<div id="charts" class="debug-charts">'
        f"{sensor_charts}"
        "</div>"
        "</details>"
        if history_path
        else ""
    )
    sound_button = (
        '<button id="sound-btn" type="button" class="audio-btn">Sound</button>'
        if soothe_path
        else ""
    )
    action_bar = (
        f'<div id="cam-actions" class="cam-actions">{audio_section}{sound_button}</div>'
        if audio_section or sound_button
        else ""
    )
    sound_sheet = (
        '<div id="sound-sheet" role="dialog" aria-modal="true" aria-label="Soothing sounds">'
        '<div class="sheet-backdrop"></div>'
        '<div class="sheet-panel"><div class="sheet-handle"></div>'
        f"{soothe_section}</div></div>"
        if soothe_section
        else ""
    )
    tonight_view = (
        '<section id="view-tonight" class="view" hidden aria-label="Tonight">'
        '<div class="page"><h1 class="section-title">Tonight</h1>'
        f'{digest_section}<div class="note">{privacy_badge}</div></div></section>'
        if digest_section
        else ""
    )
    eng_inner = health_dots + eng_state + engineering_section
    engineering_view = (
        '<section id="view-eng" class="view" hidden aria-label="Engineering">'
        '<div class="page"><h1 class="section-title">More data</h1>'
        f'{eng_inner}<div class="note">{privacy_badge}</div></div></section>'
        if eng_inner
        else ""
    )
    tab_buttons = (
        '<button type="button" class="tab-btn active" data-view="monitor">Monitor</button>'
    )
    if tonight_view:
        tab_buttons += (
            '<button type="button" class="tab-btn" data-view="tonight">Tonight</button>'
        )
    if engineering_view:
        tab_buttons += (
            '<button type="button" class="tab-btn" data-view="eng">More data</button>'
        )
    tabs = (
        f'<nav id="tabs" aria-label="Dashboard views">{tab_buttons}</nav>'
        if tonight_view or engineering_view
        else ""
    )
    body_class = "" if tabs else ' class="notabs"'
    return (
        _DASHBOARD_TEMPLATE.replace("__TITLE__", _html_attr(title))
        .replace("__BODY_CLASS__", body_class)
        .replace("__STREAM__", _html_attr(stream_path))
        .replace("__CAMERA_CHIPS__", camera_chips)
        .replace("__STATE_CHIP__", state_chip)
        .replace("__T2_ALERTS__", t2_alerts)
        .replace("__ACTION_BAR__", action_bar)
        .replace("__TONIGHT_VIEW__", tonight_view)
        .replace("__ENGINEERING_VIEW__", engineering_view)
        .replace("__SOUND_SHEET__", sound_sheet)
        .replace("__TABS__", tabs)
        .replace("__PRIVACY_BADGE__", privacy_badge)
        .replace("__READINGS__", _js_string_content(readings_path))
        .replace("__HISTORY__", _js_string_content(history_path))
        .replace("__DIGEST__", _js_string_content(digest_path))
        .replace("__SOOTHE__", _js_string_content(soothe_path))
        .replace("__ALERTS__", _js_string_content(alerts_path))
        .replace("__EVENTS__", _js_string_content(events_path))
        .replace("__SNAPSHOT__", _js_string_content(snapshot_path))
        .replace("__AUDIO__", _js_string_content(audio_path))
        .replace("__TALK__", _js_string_content(talk_path))
        .replace("__ROTATE__", str(int(rotate)))
        .replace("__SENSORS__", spec)
    )


def build_viewer_html(
    stream_path: str,
    title: str = "Beddington live view",
    readings_path: str | None = None,
    history_path: str | None = None,
    digest_path: str | None = None,
    soothe_path: str | None = None,
    audio_path: str | None = None,
    talk_path: str | None = None,
    sensors: tuple[dict[str, object], ...] = DASHBOARD_SENSORS,
    rotate: int = 0,
    alerts_path: str | None = None,
    snapshot_path: str | None = None,
    events_path: str | None = None,
) -> str:
    """A full-screen viewer page for the MJPEG stream.

    With dashboard data or controls it renders the live camera, optional
    state-first dashboard sections, optional Soothe and Tonight sections, and
    Engineering graphs behind a collapsed disclosure. With only
    ``readings_path`` it renders the simple bottom-overlay. With neither it is
    video only.
    """
    if (
        history_path
        or digest_path
        or soothe_path
        or alerts_path
        or snapshot_path
        or audio_path
        or events_path
    ):
        return _dashboard_page(
            stream_path,
            readings_path or "",
            history_path or "",
            digest_path or "",
            soothe_path or "",
            audio_path or "",
            talk_path or "",
            sensors,
            title,
            rotate,
            alerts_path or "",
            snapshot_path or "",
            events_path or "",
        )
    overlay = ""
    script = ""
    if readings_path:
        overlay = (
            '<div class="panel">'
            '<span id="r-temp"></span><span id="r-hum"></span>'
            '<span id="r-presence"></span><span id="r-vitals"></span>'
            "</div>"
        )
        script = (
            "<script>"
            f"const RP={json.dumps(readings_path)};"
            "function set(id,v){var e=document.getElementById(id);"
            "e.textContent=v||'';e.style.display=v?'inline':'none';}"
            "async function poll(){try{const r=await fetch(RP,{cache:'no-store'});"
            "if(r.ok){const d=await r.json();set('r-temp',d.temperature);"
            "set('r-hum',d.humidity);set('r-presence',d.presence);"
            "set('r-vitals',d.vitals);}}catch(e){}setTimeout(poll,3000);}poll();"
            "</script>"
        )
    return (
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_html_attr(title)}</title>"
        "<style>html,body{margin:0;background:#000;height:100%;}"
        "img{width:100vw;height:100vh;object-fit:contain;display:block;}"
        ".panel{position:fixed;left:0;right:0;bottom:0;display:flex;gap:16px;"
        "flex-wrap:wrap;padding:10px 14px;background:rgba(0,0,0,.55);color:#fff;"
        "font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}"
        ".panel span{white-space:nowrap;}</style>"
        "</head><body>"
        f'<img src="{_html_attr(stream_path)}" alt="Live camera view">'
        f"{overlay}{script}"
        "</body></html>"
    )


def rpicam_vid_command(
    *,
    camera: int = 0,
    width: int = 640,
    height: int = 480,
    fps: int = 15,
    night: bool = False,
    binary: str = "rpicam-vid",
) -> list[str]:
    """Build the rpicam-vid argv that streams MJPEG to stdout.

    ``night`` enables a low-light mode: the longest exposure that still fits the
    frame period, plus high gain. It helps when a dim night-light is on; a fully
    dark room still needs an IR lamp for the NoIR night camera.
    """
    # Night: 12 fps like the day eye, with the longest shutter that fits the
    # 83ms frame period (80ms), gain 5, denoise off so faint detail survives.
    # ~30x light boost for a near-dark room; drop back toward 1.6 if the image
    # blows out under strong IR illumination.
    NIGHT_FPS, NIGHT_SHUTTER_US, NIGHT_GAIN = 12, 80000, 5
    cmd = [
        binary,
        "--camera", str(camera),
        "-t", "0",
        "--codec", "mjpeg",
        "--width", str(width),
        "--height", str(height),
        "--framerate", str(NIGHT_FPS if night else fps),
        "--nopreview",
        "--inline",
        "-o", "-",
    ]
    if night:
        cmd += [
            "--shutter", str(NIGHT_SHUTTER_US),
            "--gain", str(NIGHT_GAIN),
            "--denoise", "cdn_off",
        ]
    return cmd


class FrameBroker:
    """Fan-out of the latest frame to any number of connected viewers."""

    def __init__(self) -> None:
        self._frame: bytes | None = None
        self._published_at: float | None = None
        self._seq = 0
        self._cond = threading.Condition()
        self._closed = False

    def publish(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
            self._published_at = time.monotonic()
            self._seq += 1
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def closed(self) -> bool:
        with self._cond:
            return self._closed

    def frame_age(self) -> float | None:
        with self._cond:
            if self._published_at is None:
                return None
            return max(0.0, time.monotonic() - self._published_at)

    def wait_for_frame(
        self, last_seq: int, timeout: float = 5.0
    ) -> tuple[int, bytes | None]:
        """Block until a frame newer than ``last_seq`` is published (or timeout)."""
        with self._cond:
            deadline = time.monotonic() + timeout
            while self._seq == last_seq and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._seq, None
                self._cond.wait(remaining)
            if self._closed:
                return self._seq, None
            return self._seq, self._frame


class RpicamFrameSource:
    """Live frames from rpicam-vid. Yields complete JPEGs from its stdout."""

    def __init__(self, command: list[str]) -> None:
        self._command = command
        self._proc: subprocess.Popen[bytes] | None = None

    def frames(self) -> Iterator[bytes]:
        self._proc = subprocess.Popen(
            self._command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        stdout = self._proc.stdout
        assert stdout is not None

        def _chunks() -> Iterator[bytes]:
            while True:
                data = stdout.read(8192)
                if not data:
                    return
                yield data

        yield from iter_jpeg_frames(_chunks())

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _pump(source: object, broker: FrameBroker) -> None:
    try:
        for frame in source.frames():  # type: ignore[attr-defined]
            broker.publish(frame)
    finally:
        broker.close()


def _make_handler(
    broker: object,
    token: str,
    title: str,
    readings_provider: Callable[[], dict[str, object]] | None = None,
    history_provider: Callable[[], dict[str, object]] | None = None,
    digest_provider: Callable[[], dict[str, object]] | None = None,
    soothe: object | None = None,
    mode_setter: Callable[[str | None], str] | None = None,
    rotate: int = 0,
    alert_state: _AlertState | None = None,
    snapshot_provider: Callable[[dict[str, object]], dict[str, object]] | None = None,
    events_provider: Callable[[], dict[str, object]] | None = None,
    worker_token: str = "",
    annotation_sink: Callable[[str, float, str], int | None] | None = None,
    audio_broker: AudioBroker | None = None,
    talk_player: TalkPlayer | None = None,
) -> type[BaseHTTPRequestHandler]:
    annotation_attempts: deque[float] = deque()
    annotation_lock = threading.Lock()
    audio_enabled = audio_broker is not None and talk_player is not None
    audio_viewers = (
        threading.Semaphore(audio_broker.max_listeners) if audio_broker is not None else None
    )

    class _LiveViewHandler(BaseHTTPRequestHandler):
        server_version = "BeddingtonLiveView/1"

        def setup(self) -> None:
            super().setup()
            try:
                self.connection.settimeout(_HEADER_READ_TIMEOUT)
            except OSError:
                pass

        def _provided_token(self) -> str:
            query = parse_qs(urlparse(self.path).query)
            return (query.get("token") or [""])[0]

        def _auth_tiers(self, provided: str) -> tuple[bool, bool]:
            full = is_authorised(provided, token)
            worker = bool(worker_token) and is_authorised(provided, worker_token)
            return full, worker

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"unauthorised")

        def _forbid(self) -> None:
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"forbidden")

        def _require_full_audio_token(self, full: bool, worker: bool) -> bool:
            if full:
                return True
            if worker:
                self._forbid()
            else:
                self._deny()
            return False

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            path = urlparse(self.path).path
            if path == "/audio.pcm" and not audio_enabled:
                self.send_error(404)
                return
            provided = self._provided_token()
            full, worker = self._auth_tiers(provided)
            if not (full or worker):
                self._deny()
                return
            if path == "/":
                link_token = token if full else provided
                readings_path = (
                    f"/readings.json?token={link_token}" if readings_provider else None
                )
                history_path = (
                    f"/history.json?token={link_token}" if history_provider else None
                )
                digest_path = (
                    f"/digest.json?token={link_token}" if digest_provider else None
                )
                soothe_path = f"/soothe?token={link_token}" if soothe is not None else None
                alerts_path = (
                    f"/alerts.json?token={link_token}" if alert_state is not None else None
                )
                events_path = (
                    f"/events.json?token={link_token}" if events_provider is not None else None
                )
                snapshot_path = (
                    f"/snapshot.json?token={link_token}"
                    if snapshot_provider is not None
                    else None
                )
                body = build_viewer_html(
                    f"/stream.mjpg?token={link_token}",
                    title,
                    readings_path,
                    history_path,
                    digest_path=digest_path,
                    soothe_path=soothe_path,
                    rotate=rotate,
                    alerts_path=alerts_path,
                    snapshot_path=snapshot_path,
                    events_path=events_path,
                    audio_path=(
                        f"/audio.pcm?token={link_token}"
                        if audio_enabled and full
                        else None
                    ),
                    talk_path=(
                        f"/talk?token={link_token}"
                        if audio_enabled and full
                        else None
                    ),
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path in (
                "/readings.json",
                "/history.json",
                "/digest.json",
                "/events.json",
            ):
                provider = {
                    "/readings.json": readings_provider,
                    "/history.json": history_provider,
                    "/digest.json": digest_provider,
                    "/events.json": events_provider,
                }[path]
                payload = provider() if provider else {}
                self._send_json(payload)
            elif path == "/soothe.json":
                talk_playing = talk_player.playing() if talk_player is not None else False
                soothe_playing = soothe.playing() if soothe is not None else None
                combined_playing = soothe_playing or ("talk" if talk_playing else None)
                payload = (
                    {
                        "presets": soothe.presets(),
                        "playing": combined_playing,
                        "talk": talk_playing,
                        "context": soothe.context(),
                        "default": soothe.default(),
                        "autosoothe": soothe.autosoothe(),
                    }
                    if soothe is not None
                    else {"presets": [], "playing": combined_playing, "talk": talk_playing}
                )
                self._send_json(payload)
            elif path == "/alerts.json":
                self._send_json(
                    alert_state.snapshot() if alert_state is not None else {"active": False}
                )
            elif path == "/snapshot.json":
                if snapshot_provider is None:
                    self.send_error(404)
                    return
                frame_age = broker.frame_age() if hasattr(broker, "frame_age") else None
                ctx = {
                    "alerts": (
                        alert_state.snapshot()
                        if alert_state is not None
                        else {"active": False}
                    ),
                    "camera_frame_age_s": frame_age,
                }
                self._send_json(snapshot_provider(ctx))
            elif path == "/frame.jpg":
                if not hasattr(broker, "wait_for_frame"):
                    self.send_error(404)
                    return
                seq, frame = broker.wait_for_frame(0, timeout=2.0)  # type: ignore[attr-defined]
                if frame is None:
                    self._send_json({"ok": False, "error": "no frame"}, status=503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.send_header("X-Frame-Seq", str(seq))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(frame)
            elif path == "/stream.mjpg":
                # Cap concurrent viewers: a full house of slow/malicious readers
                # must not exhaust threads/FDs. Over the cap -> 503, don't open
                # another unbounded stream. The slot is released in ``finally``.
                if not _STREAM_VIEWERS.acquire(blocking=False):
                    self.send_error(503, "Too many viewers")
                    return
                try:
                    # Give the connection a write timeout so a stalled/non-reading
                    # client raises (OSError/TimeoutError) instead of pinning this
                    # handler thread forever. Integration-only: exercised by real
                    # sockets, not the unit fakes.
                    try:
                        self.connection.settimeout(_STREAM_WRITE_TIMEOUT)
                    except OSError:
                        pass
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}",
                    )
                    self.send_header("Cache-Control", "no-cache, private")
                    self.end_headers()
                    seq = 0
                    # A _ModeBroker hands out a per-viewer cursor so a day/night
                    # mode switch is detected for THIS stream and doesn't block on
                    # a stale cross-broker seq. A plain FrameBroker has no cursor
                    # and behaves exactly as before.
                    cursor = (
                        broker.new_cursor() if hasattr(broker, "new_cursor") else None
                    )
                    try:
                        while True:
                            if cursor is not None:
                                seq, frame = broker.wait_for_frame(seq, cursor=cursor)
                            else:
                                seq, frame = broker.wait_for_frame(seq)
                            if frame is None:
                                active_closed = (
                                    broker.active_closed(cursor)
                                    if cursor is not None
                                    and hasattr(broker, "active_closed")
                                    else broker.closed
                                )
                                if active_closed:
                                    break
                                continue
                            self.wfile.write(multipart_frame(frame))
                    # Broaden beyond BrokenPipe/ConnectionReset: OSError also
                    # covers TimeoutError (stalled write), ConnectionAbortedError
                    # and EPIPE — drop the viewer cleanly on any of these.
                    except OSError:
                        pass
                finally:
                    _STREAM_VIEWERS.release()
            elif path == "/audio.pcm":
                if not self._require_full_audio_token(full, worker):
                    return
                self._handle_audio_stream()
            else:
                self.send_error(404)

        def _handle_audio_stream(self) -> None:
            if audio_broker is None or audio_viewers is None:
                self.send_error(404)
                return
            if not audio_viewers.acquire(blocking=False):
                self.send_error(503, "Too many audio listeners")
                return
            listener_added = False
            try:
                try:
                    audio_broker.add_listener()
                    listener_added = True
                    seq, first = audio_broker.wait_for_block(0, timeout=2.0)
                except AudioUnavailable:
                    self._send_json(
                        {"ok": False, "error": "audio unavailable"},
                        status=503,
                    )
                    return
                except AudioClientTooSlow:
                    self._send_json(
                        {"ok": False, "error": "audio listener too slow"},
                        status=503,
                    )
                    return
                if first is None:
                    self._send_json(
                        {"ok": False, "error": "audio unavailable"},
                        status=503,
                    )
                    return
                try:
                    self.connection.settimeout(_STREAM_WRITE_TIMEOUT)
                except OSError:
                    pass
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(first)
                while True:
                    try:
                        seq, block = audio_broker.wait_for_block(seq, timeout=2.0)
                    except (AudioUnavailable, AudioClientTooSlow):
                        break
                    if block is None:
                        continue
                    self.wfile.write(block)
            except OSError:
                pass
            finally:
                if listener_added:
                    audio_broker.remove_listener()
                audio_viewers.release()

        def _send_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _annotation_rate_limited(self) -> bool:
            now = time.monotonic()
            cutoff = now - _ANNOTATION_RATE_WINDOW_S
            with annotation_lock:
                while annotation_attempts and annotation_attempts[0] < cutoff:
                    annotation_attempts.popleft()
                if len(annotation_attempts) >= _ANNOTATION_RATE_LIMIT:
                    return True
                annotation_attempts.append(now)
                return False

        def _handle_annotate(self) -> None:
            if self._annotation_rate_limited():
                self._send_json({"ok": False, "error": "rate limited"}, status=429)
                return
            if annotation_sink is None:
                self.send_error(404)
                return
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._send_json(
                    {"ok": False, "error": "content length required"},
                    status=411,
                )
                return
            try:
                length = int(raw_length)
            except ValueError:
                self._send_json(
                    {"ok": False, "error": "content length required"},
                    status=411,
                )
                return
            if length < 0:
                self._send_json(
                    {"ok": False, "error": "content length required"},
                    status=411,
                )
                return
            if length > _ANNOTATION_BODY_MAX_BYTES:
                self._send_json({"ok": False, "error": "body too large"}, status=413)
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json({"ok": False, "error": "invalid json"}, status=400)
                return
            if not isinstance(payload, dict):
                self._send_json(
                    {"ok": False, "error": "body must be an object"},
                    status=400,
                )
                return

            kind = payload.get("kind")
            if not isinstance(kind, str) or not _ANNOTATION_KIND_RE.fullmatch(kind):
                self._send_json({"ok": False, "error": "bad kind"}, status=400)
                return
            raw_detail = payload.get("detail")
            if not isinstance(raw_detail, str):
                self._send_json({"ok": False, "error": "detail required"}, status=400)
                return
            detail = raw_detail.strip()
            if not detail:
                self._send_json({"ok": False, "error": "detail required"}, status=400)
                return
            if len(detail) > _ANNOTATION_DETAIL_MAX_CHARS:
                self._send_json({"ok": False, "error": "detail too long"}, status=400)
                return
            now_wall = time.time()
            if "ts" in payload:
                try:
                    ts = float(payload["ts"])
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "error": "bad ts"}, status=400)
                    return
                if (
                    not math.isfinite(ts)
                    or ts < now_wall - 24 * 3600
                    or ts > now_wall + 60
                ):
                    self._send_json({"ok": False, "error": "bad ts"}, status=400)
                    return
            else:
                ts = now_wall
            try:
                row_id = annotation_sink(kind, ts, detail)
            except Exception:
                self._send_json({"ok": False}, status=500)
                return
            self._send_json({"ok": True, "id": row_id})

        def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
            path = urlparse(self.path).path
            if path == "/talk" and not audio_enabled:
                self.send_error(404)
                return
            provided = self._provided_token()
            full, worker = self._auth_tiers(provided)
            if not (full or worker):
                self._deny()
                return
            if path == "/annotate":
                self._handle_annotate()
                return
            if path == "/talk":
                if not self._require_full_audio_token(full, worker):
                    return
                self._handle_talk()
                return
            if not full:
                self._deny()
                return
            if path == "/soothe" and soothe is not None:
                query = parse_qs(urlparse(self.path).query)
                action = (query.get("action") or [""])[0]
                preset = (query.get("preset") or [""])[0]
                context = (query.get("context") or [""])[0]
                if action == "play":
                    state = dict(soothe.play(preset, context))
                elif action == "stop":
                    state = dict(soothe.stop())
                else:
                    state = {"ok": False, "playing": soothe.playing()}
                state["presets"] = soothe.presets()
                state["context"] = soothe.context()
                state["default"] = soothe.default()
                state["autosoothe"] = soothe.autosoothe()
                self._send_json(state)
            elif path == "/mode" and mode_setter is not None:
                query = parse_qs(urlparse(self.path).query)
                requested = (query.get("set") or [""])[0]
                value = requested if requested in ("day", "night") else None
                mode = mode_setter(value)
                self._send_json({"mode": mode, "mode_auto": value is None})
            elif path == "/autosoothe" and soothe is not None:
                query = parse_qs(urlparse(self.path).query)
                enabled = (query.get("enabled") or ["0"])[0] in ("1", "true", "on")
                preset = (query.get("preset") or [""])[0]
                state = dict(soothe.set_autosoothe(enabled, preset))
                state["presets"] = soothe.presets()
                self._send_json(state)
            elif path == "/alert" and alert_state is not None:
                query = parse_qs(urlparse(self.path).query)
                if (query.get("action") or [""])[0] == "clear":
                    self._send_json(alert_state.clear())
                    return
                try:
                    score = float((query.get("score") or ["0"])[0])
                except ValueError:
                    score = 0.0
                self._send_json(
                    alert_state.raise_alert(
                        (query.get("title") or ["Cry detected"])[0],
                        (query.get("message") or [""])[0],
                        score,
                    )
                )
            else:
                self.send_error(404)

        def _handle_talk(self) -> None:
            if talk_player is None:
                self.send_error(404)
                return
            content_type = self.headers.get("Content-Type", "")
            content_base = content_type.split(";", 1)[0].strip().lower()
            if content_base not in _TALK_CONTENT_TYPES:
                self._send_json(
                    {"ok": False, "error": "unsupported content type"},
                    status=415,
                )
                return
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length) if raw_length is not None else -1
            except ValueError:
                length = -1
            if length < 0:
                self._send_json(
                    {"ok": False, "error": "content length required"},
                    status=411,
                )
                return
            if length > TALK_MAX_BYTES:
                self._send_json({"ok": False, "error": "body too large"}, status=413)
                return
            data = self.rfile.read(length)
            try:
                result = talk_player.play(data, content_type)
            except TalkBusy:
                self._send_json({"ok": False, "error": "talk busy"}, status=409)
                return
            except TalkRejected as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=413)
                return
            except TalkPlaybackError:
                self._send_json({"ok": False, "error": "talk playback failed"}, status=500)
                return
            self._send_json({"ok": True, "seconds": result.seconds})

        def log_message(self, *_args: object) -> None:  # keep the console quiet
            return

    return _LiveViewHandler


class _ModeBroker:
    """Routes the stream to whichever per-mode FrameBroker matches the current
    mode, so the live view follows the day-eye / night-eye switch.

    Sequence numbers are per-broker, and the day/night brokers advance at very
    different rates (day ~12-15 fps, night ~2 fps). A viewer that hands its
    day-broker ``last_seq`` (say ~900) straight to the freshly-active night
    broker (seq ~120) would block until the night broker climbed past 900 —
    minutes of frozen stream. So switch detection is *per viewer*: on the first
    ``wait_for_frame`` after the active broker changes for this caller, we hand
    back the new broker's current frame immediately instead of waiting for its
    seq to exceed a stale cross-broker value.
    """

    def __init__(
        self, brokers: dict[str, FrameBroker], mode_getter: Callable[[], str]
    ) -> None:
        self._brokers = brokers
        self._mode_getter = mode_getter
        # Per-viewer switch tracking. The handler passes its own ``seq`` back to
        # us each call, so we identify a viewer by the identity of the broker it
        # last read from together with the object it belongs to; because each
        # viewer thread threads its own seq through, we keep the last-served
        # broker per caller via the seq the caller reports (see wait_for_frame).

    def _active(self) -> FrameBroker:
        return self._brokers.get(self._mode_getter()) or next(iter(self._brokers.values()))

    def wait_for_frame(
        self, last_seq: int, timeout: float = 5.0, cursor: "_StreamCursor | None" = None
    ) -> tuple[int, bytes | None]:
        active = self._active()
        if cursor is not None and cursor.broker is not active:
            # The active broker just changed for this viewer. Adapt: read from
            # the new broker relative to its OWN current seq, so the viewer gets
            # its next frame promptly rather than waiting out a stale seq from
            # the previously-active broker.
            cursor.broker = active
            with active._cond:  # noqa: SLF001 - sibling broker, snapshot current seq
                base_seq = active._seq
                have_frame = active._frame is not None and not active._closed
                frame = active._frame
            if have_frame:
                cursor.last_seq = base_seq
                return base_seq, frame
            # No frame buffered yet on the new broker; wait from its current seq.
            seq, frame = active.wait_for_frame(base_seq, timeout)
            cursor.last_seq = seq
            return seq, frame
        seq, frame = active.wait_for_frame(last_seq, timeout)
        if cursor is not None:
            cursor.broker = active
            cursor.last_seq = seq
        return seq, frame

    def new_cursor(self) -> "_StreamCursor":
        return _StreamCursor()

    @property
    def closed(self) -> bool:
        return all(broker.closed for broker in self._brokers.values())

    def active_closed(self, cursor: "_StreamCursor | None" = None) -> bool:
        active = (
            cursor.broker
            if cursor is not None and cursor.broker is not None
            else self._active()
        )
        return active.closed

    def frame_age(self) -> float | None:
        return self._active().frame_age()

    def close(self) -> None:
        for broker in self._brokers.values():
            broker.close()


class _StreamCursor:
    """Per-viewer stream position so _ModeBroker can detect a mode switch for
    THIS viewer without cross-talk between concurrent viewers."""

    __slots__ = ("broker", "last_seq")

    def __init__(self) -> None:
        self.broker: FrameBroker | None = None
        self.last_seq = 0


def serve_live_view(
    *,
    host: str,
    port: int,
    token: str,
    source: object | None = None,
    sources: dict[str, object] | None = None,
    mode_getter: Callable[[], str] | None = None,
    title: str = "Beddington live view",
    readings_provider: Callable[[], dict[str, object]] | None = None,
    history_provider: Callable[[], dict[str, object]] | None = None,
    digest_provider: Callable[[], dict[str, object]] | None = None,
    soothe: object | None = None,
    mode_setter: Callable[[str | None], str] | None = None,
    rotate: int = 0,
    snapshot_provider: Callable[[dict[str, object]], dict[str, object]] | None = None,
    events_provider: Callable[[], dict[str, object]] | None = None,
    worker_token: str = "",
    annotation_sink: Callable[[str, float, str], int | None] | None = None,
    broker_sink: Callable[[object], None] | None = None,
    alert_state_sink: Callable[[object], None] | None = None,
    audio_broker: AudioBroker | None = None,
    talk_player: TalkPlayer | None = None,
    tls_cert: str | None = None,
    tls_key: str | None = None,
) -> None:
    """Serve the live view until interrupted.

    Pass a single ``source`` (``frames()`` + ``close()``), or ``sources`` — a
    {mode: source} map plus a ``mode_getter`` — to follow the day-eye / night-eye
    switch. ``*_provider`` callables back ``/readings.json``, ``/history.json``,
    ``/digest.json`` and ``/events.json``; ``soothe``
    (presets()/playing()/play()/stop()) backs the Soothe section.
    ``broker_sink`` receives the frame broker before serving starts, so the
    caller can late-bind ``broker.frame_age`` (the broker only exists here).
    ``alert_state_sink`` receives the alert state used by ``/alerts.json``.
    """
    if sources:
        brokers: dict[str, FrameBroker] = {}
        for mode, src in sources.items():
            mode_broker = FrameBroker()
            threading.Thread(target=_pump, args=(src, mode_broker), daemon=True).start()
            brokers[mode] = mode_broker
        getter = mode_getter or (lambda: next(iter(brokers)))
        broker: object = _ModeBroker(brokers, getter)

        def _close_sources() -> None:
            for src in sources.values():
                src.close()  # type: ignore[attr-defined]

    elif source is not None:
        single = FrameBroker()
        threading.Thread(target=_pump, args=(source, single), daemon=True).start()
        broker = single

        def _close_sources() -> None:
            source.close()  # type: ignore[attr-defined]

    else:
        raise ValueError("serve_live_view needs a source or sources")

    if broker_sink is not None:
        broker_sink(broker)
    alert_state = _AlertState()
    if alert_state_sink is not None:
        alert_state_sink(alert_state)
    handler = _make_handler(
        broker, token, title, readings_provider, history_provider, digest_provider,
        soothe, mode_setter, rotate, alert_state=alert_state,
        snapshot_provider=snapshot_provider, events_provider=events_provider,
        worker_token=worker_token, annotation_sink=annotation_sink,
        audio_broker=audio_broker, talk_player=talk_player,
    )
    httpd = _DaemonThreadingHTTPServer((host, port), handler)
    if tls_cert and tls_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls_cert), str(tls_key))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        _close_sources()
        broker.close()
        if audio_broker is not None:
            audio_broker.close()
