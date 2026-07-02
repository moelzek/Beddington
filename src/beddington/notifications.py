from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> dict[str, bool]: ...


@dataclass
class LocalNotifier:
    desktop: bool = True

    def notify(self, title: str, message: str) -> dict[str, bool]:
        print(f"[{title}] {message}")
        desktop_sent = self._desktop(title, message) if self.desktop else False
        return {"console": True, "desktop": desktop_sent}

    def _desktop(self, title: str, message: str) -> bool:
        try:
            system = platform.system()
            if system == "Darwin":
                script = (
                    f'display notification "{_escape(message)}" '
                    f'with title "{_escape(title)}"'
                )
                subprocess.run(
                    ["osascript", "-e", script],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            if system == "Linux" and shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", title, message],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        except (OSError, subprocess.CalledProcessError):
            return False
        return False


@dataclass
class LiveViewNotifier:
    """Posts a cry alert to the on-device live-view server so its dashboard can
    surface it (banner + alarm + browser notification) to a phone on the LAN.

    Stays on the device/LAN — nothing leaves the network. Best-effort: any
    failure (server down, no token) returns ``{"lan": False}`` rather than
    raising, so a missed alert never crashes the monitoring loop.
    """

    port: int = 8088
    token: str = ""
    host: str = "127.0.0.1"

    def notify(self, title: str, message: str) -> dict[str, bool]:
        if not self.token:
            return {"lan": False}
        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode(
            {"token": self.token, "title": title, "message": message}
        )
        url = f"http://{self.host}:{self.port}/alert?{params}"
        request = urllib.request.Request(
            url,
            data=b"",
            headers={"User-Agent": "beddington/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                response.read()
        except Exception:
            return {"lan": False}
        return {"lan": True}


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
