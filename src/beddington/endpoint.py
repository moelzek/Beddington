"""Pick which Ollama endpoint a voice call should use.

The Pi runs an always-on baseline model (``llama3.2:1b``). When an optional,
more capable desktop endpoint is configured (e.g. ``gemma3:12b``), voice calls
prefer it — but only while it is actually reachable on the LAN. If the desktop
is asleep or off, calls silently fall back to the Pi baseline, so nothing
degrades below the on-device experience.

Reachability is health-probed (not just attempted per request) so a sleeping
desktop does not add its connect latency to every utterance, and the result is
cached briefly to avoid probing on every call.
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from typing import Any

# The Pi is RAM-constrained (4GB shared with Whisper), so its model is unloaded
# after each call. The desktop has RAM to spare, so its model stays resident to
# avoid a multi-second reload of a 12B on every utterance.
_PI_KEEP_ALIVE = 0

# Positive probes are trusted for the configured window; negative probes expire
# faster so a desktop that just woke is picked up without a long stale window.
_NEGATIVE_CACHE_SECONDS = 10.0

# host -> (expires_at_monotonic, reachable)
_PROBE_CACHE: dict[str, tuple[float, bool]] = {}


@dataclass(frozen=True)
class OllamaTarget:
    host: str
    model: str
    keep_alive: object


def resolve_ollama_target(config: Any) -> OllamaTarget:
    """Return the endpoint a voice call should use for ``config``.

    Falls back to the primary (Pi) host+model whenever no upgrade host is
    configured or the upgrade host is not reachable right now.
    """
    primary_host = str(getattr(config, "host", ""))
    primary_model = str(getattr(config, "model", ""))
    primary = OllamaTarget(primary_host, primary_model, _PI_KEEP_ALIVE)

    upgrade_host = str(getattr(config, "upgrade_host", "")).strip()
    if not upgrade_host:
        return primary

    probe_timeout = float(getattr(config, "upgrade_probe_timeout", 1.0))
    cache_seconds = float(getattr(config, "upgrade_probe_cache_seconds", 60.0))
    if not _reachable(upgrade_host, probe_timeout, cache_seconds):
        return primary

    upgrade_model = str(getattr(config, "upgrade_model", "")).strip() or primary_model
    keep_alive = getattr(config, "upgrade_keep_alive", "10m")
    return OllamaTarget(upgrade_host.rstrip("/"), upgrade_model, keep_alive)


def _reachable(host: str, timeout: float, cache_seconds: float) -> bool:
    now = time.monotonic()
    cached = _PROBE_CACHE.get(host)
    if cached is not None and now < cached[0]:
        return cached[1]

    # A sleeping Wi-Fi NIC on the desktop often eats the first packet after
    # idle; one retry distinguishes "napping" from "off".
    ok = _probe(host, timeout) or _probe(host, timeout)
    ttl = cache_seconds if ok else min(cache_seconds, _NEGATIVE_CACHE_SECONDS)
    _PROBE_CACHE[host] = (now + ttl, ok)
    return ok


def _probe(host: str, timeout: float) -> bool:
    url = host.rstrip("/") + "/api/version"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "beddington/0.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except Exception:
        return False
