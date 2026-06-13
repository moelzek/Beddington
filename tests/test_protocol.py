"""Logic tests for the Lab Witness step machine — no camera, model, or hardware.

Run from the repo root with either:

    python3 tests/test_protocol.py
    pytest tests
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lab_witness.protocol import (
    Observation,
    Protocol,
    Step,
    StepMachine,
    TimingDeviation,
)


def _proto():
    return Protocol(
        "dilution",
        (
            Step("prep", "Prep", None, None),
            Step("mix", "Mix", 8, 12),
            Step("incubate", "Incubate", 30, 60),
            Step("read", "Read", None, None),
        ),
    )


def _types(events):
    return [type(e).__name__ for e in events]


def _devs(events):
    return [e for e in events if isinstance(e, TimingDeviation)]


def test_ordered_run_logs_each_step_with_no_deviation_when_in_window():
    m = StepMachine(_proto())
    assert _types(m.update(Observation("prep"), now=0)) == ["StepStarted"]
    ev = m.update(Observation("mix"), now=5)  # prep -> mix (prep untimed)
    assert _types(ev) == ["StepEnded", "StepStarted"] and _devs(ev) == []
    ev = m.update(Observation("incubate"), now=15)  # mix took 10s (window 8-12)
    assert _devs(ev) == []
    ev = m.update(Observation("read"), now=60)  # incubate took 45s (window 30-60)
    assert _devs(ev) == []
    assert _types(m.finish(now=70)) == ["StepEnded"]  # read, untimed


def test_over_run_flagged_at_step_end():
    m = StepMachine(_proto())
    m.update(Observation("prep"), now=0)
    m.update(Observation("mix"), now=2)
    ev = m.update(Observation("incubate"), now=20)  # mix ran 18s > 12 max
    devs = _devs(ev)
    assert len(devs) == 1 and devs[0].kind == "over" and devs[0].live is False


def test_over_run_flagged_live_mid_step_and_not_double_flagged():
    m = StepMachine(_proto())
    m.update(Observation("prep"), now=0)
    m.update(Observation("mix"), now=2)
    m.update(Observation("incubate"), now=14)  # mix 12s (fine); start incubate
    ev = m.update(Observation("incubate"), now=80)  # 66s in -> over 60 max, LIVE
    devs = _devs(ev)
    assert len(devs) == 1 and devs[0].kind == "over" and devs[0].live is True
    ev = m.update(Observation("read"), now=85)  # ending must not double-flag
    assert _devs(ev) == []


def test_under_run_flagged_at_step_end():
    m = StepMachine(_proto())
    m.update(Observation("prep"), now=0)
    m.update(Observation("mix"), now=2)
    ev = m.update(Observation("incubate"), now=6)  # mix ran 4s < 8 min
    devs = _devs(ev)
    assert len(devs) == 1 and devs[0].kind == "under" and devs[0].live is False


def test_unknown_or_out_of_order_observations_do_not_advance():
    m = StepMachine(_proto())
    m.update(Observation("prep"), now=0)
    assert m.update(Observation(None), now=1) == []
    assert m.update(Observation("read"), now=2) == []  # not the next step
    assert m.current.id == "prep"


if __name__ == "__main__":
    import traceback

    failed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
