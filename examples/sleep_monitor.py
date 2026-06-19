"""Mock Lullaby run: no camera, mic, network, or LLM required.

Run from the repo root:

    python3 examples/sleep_monitor.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lullaby import ConsoleAlert, ConsoleJournal, Lullaby, MockPerceiver, MonitorPolicy, Observation


SCRIPT = [
    (Observation(sound="quiet", motion="settled", view_clear=True), 0),
    (Observation(sound="fussing", motion="restless", view_clear=True), 10),
    (Observation(sound="crying", motion="restless", view_clear=True), 20),
    (Observation(sound="crying", motion="restless", view_clear=True), 42),
    (Observation(sound="crying", motion="restless", view_clear=False), 48),
    (Observation(sound="crying", motion="restless", view_clear=False), 57),
    (Observation(sound="quiet", motion="settled", view_clear=True), 70),
]


def main() -> int:
    app = Lullaby(
        MockPerceiver(observation for observation, _ in SCRIPT),
        policy=MonitorPolicy(crying_seconds=20, view_blocked_seconds=8),
        journal=ConsoleJournal(),
        alert=ConsoleAlert(),
    )
    print("Lullaby - local mock run\n")
    for _observation, t in SCRIPT:
        app.step(now=t)
    print("\nDone. Core check alerts ran without camera hardware or an LLM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
