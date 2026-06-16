"""Mock end-to-end Lab Witness run — no camera, no model, no Pi.

Replays a serial dilution where the incubation deliberately over-runs, so you can
watch the timestamped notebook entries and the live deviation flag fire. Run:

    python3 examples/serial_dilution.py

A real run swaps MockPerceiver for BrainPerceiver (hatch-brain) or the CV dev's
OpenCVPerceiver — nothing else changes.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lab_witness import ConsoleFlag, ConsoleNotebook, MockPerceiver, Protocol, Step, Witness

DILUTION = Protocol(
    "Serial dilution (1:10 x 3)",
    (
        Step("label_tubes", "Label tubes 1-4"),
        Step("add_diluent", "Add 900 uL diluent to each"),
        Step("transfer", "Transfer 100 uL down the series"),
        Step("mix", "Vortex-mix each tube", min_seconds=5, max_seconds=12),
        Step("incubate", "Incubate", min_seconds=30, max_seconds=60),
        Step("read", "Read / aliquot out"),
    ),
)

# A scripted run: (step id the camera "sees", timestamp in seconds). We linger on
# 'incubate' past its 60s window to trip the live over-run flag.
SCRIPT = [
    ("label_tubes", 0),
    ("add_diluent", 8),
    ("transfer", 20),
    ("mix", 40),
    ("mix", 48),       # still mixing — 8s in, within 5-12
    ("incubate", 52),  # start incubate
    ("incubate", 90),  # 38s in — fine
    ("incubate", 115), # 63s in — OVER the 60s max -> live flag
    ("read", 120),     # end incubate (68s total) + start read
]


def main() -> int:
    witness = Witness(
        DILUTION,
        MockPerceiver(step_id for step_id, _ in SCRIPT),
        notebook=ConsoleNotebook(),
        flag=ConsoleFlag(),
    )
    print(f"Lab Witness — mock run of: {DILUTION.name}\n")
    for _step_id, t in SCRIPT:
        witness.step(frame=b"", now=t)
    witness.finish(now=125)
    print("\nDone. (Swap MockPerceiver for BrainPerceiver or the CV dev's OpenCVPerceiver to go live.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
