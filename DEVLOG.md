# DEVLOG — Lab Witness build journal

Reverse-chronological. One block per day: **what got done · what's blocked · the single outcome for tomorrow.** This is also raw material for the Demo Night story — keep it honest, keep it short. Canonical decisions/status live in [memory.md](memory.md); the forward plan / build sequence lives in [ROADMAP.md](ROADMAP.md) — check each day's outcome against the current tier (A → B → C). This file is the narrative of *what actually happened at the bench*.

---

## Sun 14 Jun 2026 — software skeleton (reusing Hatch)

**Done**
- Stood up the Lab Witness code skeleton, mirroring the build-doc §3 architecture (Camera → Perception → State machine → Decision → Notion/Flag). Package `lab_witness/`: `protocol.py` (the timing state machine), `runtime.py` (perceivers + act sinks + the loop).
- **Reused the Hatch decision kernel.** `BrainPerceiver` wraps `hatch-brain`'s `Brain.decide(frame, policy)` — one whitelist action per protocol step — so the perception spine isn't rebuilt from scratch. `pyproject.toml` depends on `hatch-brain` from the Hatch repo (ADR-0009: the brain is a reusable, archetype-agnostic kernel).
- **Demoable with no hardware:** `examples/serial_dilution.py` replays a dilution where the incubation over-runs; the live deviation flag fires mid-step at 63s. `tests/test_protocol.py` — 5 deterministic timing tests, all passing.
- The hard CV is decoupled behind a one-method `Perceiver` interface, so the CV dev's classical-OpenCV path drops in without touching the loop (de-risks the single biggest reliability lever).

**Blocked / open**
- CV/embedded dev still unconfirmed (owns the rig from Day 7 — non-negotiable).
- Notion write + on-screen banner are stubs (`NotionNotebook`, `ConsoleFlag`) pending the connector + rig.
- Merge Hatch PR #1 before relying on `BrainPerceiver` live — it carries the per-action persistence fix the multi-step use needs.

**Tomorrow's single outcome**
- Per the day-by-day plan: boot the Pi, camera live, a classical OpenCV detection demo on the bare Pi 5 — the software skeleton is ready to receive it.

---

## Sat 13 Jun 2026 — Workshop #1 — assembly

> Same day as the Day-0 block below; logged separately as the day's mode shifted from ordering to building.

We're in-person at Workshop #1 — 3D printers humming, a full tool bench, mentors on hand. The plan flips from *ordering* to *assembly*: all kit is in hand and the Pi 5 rig is on the table in front of me, so today is hands-on.

**Timeline revised** (Mo's confirmation): Workshop #1 today (13 Jun) · home/remote tinkering 14–20 Jun · Workshop #2 (integration) Sun 21 Jun · demo ≈28 Jun (was 7 Jul) · v0 freeze PROPOSED ~24 Jun (was 20 Jun, pending Mo's sign-off). Canonical dates live in [memory.md](memory.md).

**First assembly tasks (today)**
- Clip the active cooler onto the Pi 5.
- Flash Pi OS to the microSD card.
- Connect Camera Module 3 (Pi-5-compatible cable).
- 3D-print a top-down camera mount.
- First boot + grab a test photo.

**Still open**
- CV/embedded dev not yet confirmed — rig's here, but no one to own it from week two yet.
- Ordered step-list for the dilution series still to write (Mo's bench intuition = ground truth).

**Progress so far:** microSD flashed with Raspberry Pi OS (64-bit); Wi-Fi + SSH configured; running **headless** (no micro-HDMI on hand, so controlled from the laptop over Wi-Fi). Active cooler going on next. Full step-by-step lives in [BUILD.md](BUILD.md).

**Blocked / to-verify:** Pi-5 camera adapter cable (22→15 pin) likely still needed (verify on opening the camera box); SSH password to confirm at first boot; confirm the cooler part is the fan cooler, not a passive case.

---

## Day 0 — Fri 13 Jun 2026

**Done**
- Gates locked: mock bench (Blue Garage) · serial-dilution protocol · timing-only deviations · Pi 5 4GB + Cam Module 3, CPU-first (OpenCV/MediaPipe), **no AI HAT+ for v0** (deferred).
- Project operating system set up: CLAUDE.md, context.md, agents.md, skills.md, memory.md.
- Judging rubric confirmed: Novelty · Deployment · Impact (was four axes).

**Blocked / open**
- Kit not yet ordered — shipping is the silent killer against 20 Jun.
- CV/embedded dev not yet confirmed (owns the rig from Day 7 — non-negotiable).
- Ordered step-list for the dilution series not yet written (Mo's bench intuition = ground truth).
- Hardware gaps noted: microSD, Pi-5 camera cable, micro-HDMI (see hardware-inventory).

**Tomorrow's single outcome (Day 1)**
- Flash Pi OS, boot, camera live, run a classical OpenCV (or MediaPipe) detection demo on the bare Pi 5 — CPU-first, no AI HAT+. Pure "does the rig see anything" day.
