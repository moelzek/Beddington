# Lab Witness

**A Pi over the bench that watches a scientist work, silently writes the lab notebook, and flags when reality drifts from the protocol.**

> The missing sensor for the self-driving lab — it watches the bench so discovery agents can trust the data. It passively documents a human scientist and catches protocol errors, cheaply, with no robots and no typing.

This repo holds the **code skeleton** plus the project's operating docs. For live state, decisions and the sprint plan, start at **[memory.md](memory.md)** (the single source of truth) and **[CLAUDE.md](CLAUDE.md)** (the router).

## Try it now (no hardware)

```bash
python3 examples/serial_dilution.py
```

You'll see a mock serial dilution: each step logged with a timestamp, and a **live deviation flag** firing when the incubation over-runs its window. No camera, model, or Pi needed.

Run the tests:

```bash
python3 tests/test_protocol.py        # or: pytest tests
```

## How it works (build-doc §3 architecture)

```
[Top-down camera] --frames--> [Perception] --Observation--> [State machine]
                                                                  |
                                          step + timing events    v
        [Notion notebook]  <--  [Decision: log-worthy? deviation?]  -->  [Live flag]
```

- **Perception** (`lab_witness/runtime.py`) — frame in, `Observation(step_id)` out. Swappable:
  - `MockPerceiver` — scripted, for the demo + tests.
  - `BrainPerceiver` — reuses **hatch-brain** (`Brain.decide(frame, policy)`), one action per step. The kernel debounces, so a flicker can't jump the sequence.
  - *OpenCVPerceiver* — the v0 classical-CV path, the CV dev's to own. The `Perceiver` interface is the whole contract.
- **State machine** (`lab_witness/protocol.py`) — walks the ordered protocol, times each step, and flags an over- or under-run against the step's `min/max` window. Catches an over-run **live**, mid-step, not just at the end. Pure Python, fully tested.
- **Act** — `Notebook` (timestamped entries; `ConsoleNotebook` now, `NotionNotebook` stub for the real write) and `Flag` (the on-screen banner / LED; `ConsoleFlag` now).

## Going live

1. Install the decision kernel (reused from Hatch — ADR-0009):
   ```bash
   pip install -e ../hatch/brain        # local dev
   # or, from the repo:
   pip install 'hatch-brain @ git+https://github.com/moelzek/hatch.git#subdirectory=brain'
   ```
   **Merge hatch PR #1 first** — it carries the per-action persistence fix `BrainPerceiver` needs (distinct step ids must not share one escalation streak).
2. Swap `MockPerceiver` for `BrainPerceiver` (cloud VLM), or wire the CV dev's classical-CV `OpenCVPerceiver`.
3. Wire `NotionNotebook` (model it on the Granola->Notion pipeline) and the on-screen banner / LED.

## Structure

- `lab_witness/` — the package: `protocol.py` (state machine), `runtime.py` (perceivers + sinks + loop).
- `examples/serial_dilution.py` — the runnable mock demo.
- `tests/test_protocol.py` — deterministic timing tests.
- Operating docs (start at [CLAUDE.md](CLAUDE.md)): [memory.md](memory.md), [agents.md](agents.md), [context.md](context.md), [ROADMAP.md](ROADMAP.md), [BUILD.md](BUILD.md), [lab-witness-v0-build-doc.md](lab-witness-v0-build-doc.md).

## Scope reminder

v0 = one top-down camera, one dilution series, **timing deviations only**, frozen 20 Jun. Reagent-order / skipped-step detection, protocols.io, multi-bench — all v2 narrative. (See [agents.md](agents.md) guardrails.)
