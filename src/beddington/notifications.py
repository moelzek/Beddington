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


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
