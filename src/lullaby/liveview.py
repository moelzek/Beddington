"""LAN-only live camera view for Lullaby.

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
import json
import subprocess
import threading
from collections.abc import Callable, Iterable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_SOI = b"\xff\xd8"  # JPEG start-of-image
_EOI = b"\xff\xd9"  # JPEG end-of-image
_BOUNDARY = b"frame"


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
                break
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
    return hmac.compare_digest(provided, expected)


# The sensors shown as dashboard tabs/graphs. ``scale`` converts the stored value
# for display (gas ohms -> kilo-ohms); ``bool`` marks on/off readings (0/1 graph).
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
html,body{margin:0;background:#000;color:#eee;height:100%;
font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
#tabs{display:flex;overflow-x:auto;background:#111;border-bottom:1px solid #222;
position:sticky;top:0;-webkit-overflow-scrolling:touch}
#tabs button{flex:0 0 auto;background:none;border:none;color:#9aa;
padding:12px 14px;font-size:14px}
#tabs button.active{color:#fff;border-bottom:2px solid #4ea1ff}
.panel{display:none}
.panel.active{display:block}
#cam.panel.active{display:flex;align-items:center;justify-content:center;position:relative;
height:calc(100vh - 48px);height:calc(100dvh - 48px);background:#000}
#cam img{max-width:100%;max-height:100%;object-fit:contain;display:block}
#readings{position:absolute;left:0;right:0;bottom:0;display:flex;gap:14px;flex-wrap:wrap;
padding:10px 14px;background:rgba(0,0,0,.5)}
#readings span{white-space:nowrap}
#readings .mode{font-weight:700}
.nightnote{position:absolute;left:12px;right:12px;top:38%;text-align:center;
padding:14px 16px;border-radius:10px;color:#dde;font-size:16px;
background:rgba(20,24,48,.72);display:none}
.chartwrap{padding:14px}
.cur{font-size:24px;font-weight:700;margin:4px 0 12px}
canvas{width:100%;height:300px;background:#0c0c0c;border:1px solid #222;border-radius:8px}
.digest{white-space:pre-wrap;font-size:15px;line-height:1.7;color:#ddd;margin:0}
.note{color:#777;padding:12px 14px;font-size:12px}
</style></head><body>
<div id="tabs"></div>
<div id="cam" class="panel active">
  <img src="__STREAM__" alt="Live camera view">
  <div id="nightnote" class="nightnote">🌙 It's dark — the radar and motion sensor are watching.</div>
  <div id="readings"></div>
</div>
<div id="charts"></div>
<div class="note">LAN only · no recording · no audio</div>
<script>
const READINGS="__READINGS__",HISTORY="__HISTORY__",DIGEST="__DIGEST__",SENSORS=__SENSORS__;
let active="cam",HIST={};
const tabs=document.getElementById("tabs"),charts=document.getElementById("charts");
function tab(id,label){const b=document.createElement("button");b.textContent=label;
b.dataset.tab=id;b.onclick=function(){show(id)};tabs.appendChild(b);}
tab("cam","Camera");
if(DIGEST){tab("night","Night");
const np=document.createElement("div");np.className="panel";np.id="p-night";
np.innerHTML='<div class="chartwrap"><pre id="digest-text" class="digest">Loading…</pre></div>';
charts.appendChild(np);}
SENSORS.forEach(function(s){tab(s.key,s.label);
const p=document.createElement("div");p.className="panel";p.id="p-"+s.key;
p.innerHTML='<div class="chartwrap"><div class="cur" id="cur-'+s.key+'">collecting…</div>'
+'<canvas id="cv-'+s.key+'"></canvas></div>';charts.appendChild(p);});
async function loadDigest(){const e=document.getElementById("digest-text");if(!e)return;
try{const r=await fetch(DIGEST,{cache:"no-store"});if(r.ok){const d=await r.json();
e.textContent=d.text||"No summary yet.";}else{e.textContent="No summary yet.";}}
catch(x){e.textContent="No summary yet.";}}
function show(id){active=id;
document.querySelectorAll(".panel").forEach(function(p){p.classList.remove("active")});
document.getElementById(id==="cam"?"cam":"p-"+id).classList.add("active");
document.querySelectorAll("#tabs button").forEach(function(b){
b.classList.toggle("active",b.dataset.tab===id)});
if(id==="night")loadDigest();else if(id!=="cam")draw();}
const ORDER=["temperature","humidity","pressure","air","light","presence","vitals"];
async function poll(){try{const r=await fetch(READINGS,{cache:"no-store"});
if(r.ok){const d=await r.json();const el=document.getElementById("readings");el.innerHTML="";
if(d.mode){const m=document.createElement("span");m.className="mode";
m.textContent=d.mode==="night"?"🌙 Night":"☀️ Day";el.appendChild(m);}
ORDER.forEach(function(k){if(d[k]){const s=document.createElement("span");
s.textContent=d[k];el.appendChild(s);}});
const nn=document.getElementById("nightnote");
if(nn)nn.style.display=(d.mode==="night")?"block":"none";}}catch(e){}setTimeout(poll,3000);}
async function load(){try{const r=await fetch(HISTORY,{cache:"no-store"});
if(r.ok)HIST=await r.json();}catch(e){}
SENSORS.forEach(function(s){const h=HIST[s.key];if(!h)return;
const c=document.getElementById("cur-"+s.key);const n=h.points.length;
if(c)c.textContent=n?(s.bool?(h.points[n-1][1]?"yes":"no")
:(h.points[n-1][1]+(h.unit?" "+h.unit:""))):"no reading yet";});
draw();}
function draw(){const s=SENSORS.find(function(x){return x.key===active});if(!s)return;
const h=HIST[s.key];const cv=document.getElementById("cv-"+s.key);if(!cv||!h)return;
const ctx=cv.getContext("2d"),W=cv.width=cv.clientWidth*2,H=cv.height=600;
ctx.clearRect(0,0,W,H);const p=h.points||[];
if(p.length<2){ctx.fillStyle="#777";ctx.font="30px sans-serif";
ctx.fillText("collecting data…",30,60);return;}
const ys=p.map(function(q){return q[1]});let mn=Math.min.apply(0,ys),mx=Math.max.apply(0,ys);
if(h.bool){mn=0;mx=1;}if(mn===mx){mn-=1;mx+=1;}
const x0=p[0][0],x1=p[p.length-1][0]||x0+1,pad=70;
function X(t){return pad+(t-x0)/((x1-x0)||1)*(W-1.3*pad);}
function Y(v){return H-pad-(v-mn)/((mx-mn)||1)*(H-2*pad);}
ctx.strokeStyle="#333";ctx.lineWidth=2;ctx.beginPath();
ctx.moveTo(pad,pad);ctx.lineTo(pad,H-pad);ctx.lineTo(W-10,H-pad);ctx.stroke();
ctx.fillStyle="#999";ctx.font="26px sans-serif";
ctx.fillText(mx.toFixed(h.bool?0:1),8,pad+18);ctx.fillText(mn.toFixed(h.bool?0:1),8,H-pad);
ctx.strokeStyle="#4ea1ff";ctx.lineWidth=4;ctx.beginPath();
p.forEach(function(q,i){const x=X(q[0]),y=Y(q[1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
ctx.stroke();}
show("cam");poll();load();setInterval(load,5000);
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
    sensors: tuple[dict[str, object], ...],
    title: str,
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
    return (
        _DASHBOARD_TEMPLATE.replace("__TITLE__", title)
        .replace("__STREAM__", stream_path)
        .replace("__READINGS__", readings_path)
        .replace("__HISTORY__", history_path)
        .replace("__DIGEST__", digest_path)
        .replace("__SENSORS__", spec)
    )


def build_viewer_html(
    stream_path: str,
    title: str = "Lullaby live view",
    readings_path: str | None = None,
    history_path: str | None = None,
    digest_path: str | None = None,
    sensors: tuple[dict[str, object], ...] = DASHBOARD_SENSORS,
) -> str:
    """A full-screen viewer page for the MJPEG stream.

    With ``history_path`` it renders the full tabbed dashboard (a Camera tab plus
    one graph tab per sensor, and a Night tab when ``digest_path`` is given). With
    only ``readings_path`` it renders the simple bottom-overlay. With neither it
    is video only.
    """
    if history_path:
        return _dashboard_page(
            stream_path, readings_path or "", history_path, digest_path or "", sensors, title
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
            f'const RP="{readings_path}";'
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
        f"<title>{title}</title>"
        "<style>html,body{margin:0;background:#000;height:100%;}"
        "img{width:100vw;height:100vh;object-fit:contain;display:block;}"
        ".panel{position:fixed;left:0;right:0;bottom:0;display:flex;gap:16px;"
        "flex-wrap:wrap;padding:10px 14px;background:rgba(0,0,0,.55);color:#fff;"
        "font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}"
        ".panel span{white-space:nowrap;}</style>"
        "</head><body>"
        f'<img src="{stream_path}" alt="Live camera view">'
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

    ``night`` enables a low-light mode (longer shutter + higher gain) that helps
    when a dim night-light is on; a fully dark room still needs a NoIR camera and
    IR light. The longer shutter naturally lowers the achievable frame rate.
    """
    cmd = [
        binary,
        "--camera", str(camera),
        "-t", "0",
        "--codec", "mjpeg",
        "--width", str(width),
        "--height", str(height),
        "--framerate", str(fps),
        "--nopreview",
        "--inline",
        "-o", "-",
    ]
    if night:
        cmd += ["--shutter", "120000", "--gain", "8.0", "--denoise", "cdn_off"]
    return cmd


class FrameBroker:
    """Fan-out of the latest frame to any number of connected viewers."""

    def __init__(self) -> None:
        self._frame: bytes | None = None
        self._seq = 0
        self._cond = threading.Condition()
        self._closed = False

    def publish(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
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

    def wait_for_frame(
        self, last_seq: int, timeout: float = 5.0
    ) -> tuple[int, bytes | None]:
        """Block until a frame newer than ``last_seq`` is published (or timeout)."""
        with self._cond:
            if self._seq == last_seq and not self._closed:
                self._cond.wait(timeout)
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
    broker: FrameBroker,
    token: str,
    title: str,
    readings_provider: Callable[[], dict[str, object]] | None = None,
    history_provider: Callable[[], dict[str, object]] | None = None,
    digest_provider: Callable[[], dict[str, object]] | None = None,
) -> type[BaseHTTPRequestHandler]:
    class _LiveViewHandler(BaseHTTPRequestHandler):
        server_version = "LullabyLiveView/1"

        def _provided_token(self) -> str:
            query = parse_qs(urlparse(self.path).query)
            return (query.get("token") or [""])[0]

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"unauthorised")

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            path = urlparse(self.path).path
            if not is_authorised(self._provided_token(), token):
                self._deny()
                return
            if path == "/":
                readings_path = (
                    f"/readings.json?token={token}" if readings_provider else None
                )
                history_path = (
                    f"/history.json?token={token}" if history_provider else None
                )
                digest_path = (
                    f"/digest.json?token={token}" if digest_provider else None
                )
                body = build_viewer_html(
                    f"/stream.mjpg?token={token}",
                    title,
                    readings_path,
                    history_path,
                    digest_path=digest_path,
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/readings.json", "/history.json", "/digest.json"):
                provider = {
                    "/readings.json": readings_provider,
                    "/history.json": history_provider,
                    "/digest.json": digest_provider,
                }[path]
                payload = provider() if provider else {}
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/stream.mjpg":
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}",
                )
                self.send_header("Cache-Control", "no-cache, private")
                self.end_headers()
                seq = 0
                try:
                    while True:
                        seq, frame = broker.wait_for_frame(seq)
                        if frame is None:
                            if broker.closed:
                                break
                            continue
                        self.wfile.write(multipart_frame(frame))
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

        def log_message(self, *_args: object) -> None:  # keep the console quiet
            return

    return _LiveViewHandler


def serve_live_view(
    *,
    host: str,
    port: int,
    token: str,
    source: object,
    title: str = "Lullaby live view",
    readings_provider: Callable[[], dict[str, object]] | None = None,
    history_provider: Callable[[], dict[str, object]] | None = None,
    digest_provider: Callable[[], dict[str, object]] | None = None,
) -> None:
    """Serve the live view until interrupted. ``source`` must expose
    ``frames() -> Iterator[bytes]`` and ``close()`` (RpicamFrameSource or a fake).

    ``readings_provider`` returns the latest readings (``/readings.json``, shown in
    the overlay); ``history_provider`` returns the per-sensor time series
    (``/history.json``, drawn in the graph tabs); ``digest_provider`` returns the
    night summary (``/digest.json``, shown in the Night tab).
    """
    broker = FrameBroker()
    pump = threading.Thread(target=_pump, args=(source, broker), daemon=True)
    pump.start()
    handler = _make_handler(
        broker, token, title, readings_provider, history_provider, digest_provider
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        source.close()  # type: ignore[attr-defined]
        broker.close()
