# DEVLOG — Lab Witness build journal

Reverse-chronological. One block per day: **what got done · what's blocked · the single outcome for tomorrow.** This is also raw material for the Demo Night story — keep it honest, keep it short. Canonical decisions/status live in [memory.md](memory.md); the forward plan / build sequence lives in [ROADMAP.md](ROADMAP.md) — check each day's outcome against the current tier (A → B → C). This file is the narrative of *what actually happened at the bench*.

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

**Live build log (in progress):**
- Set up the microSD card on the laptop and flashed **Raspberry Pi OS (64-bit)** using Raspberry Pi Imager v2.0.7, targeting the SanDisk microSD.
- In Imager customisation, configured **Wi-Fi** and enabled **SSH** (Remote access). Hostname/username set to `labwitness`. ⚠️ Password may not have been set — to verify at first connection; if missing, re-flash or add a password (cheap fix).
- Decided to run the Pi **headless** (no monitor): the only HDMI cable on hand is full-size, but the Pi 5 needs micro-HDMI — so control will be over wifi via SSH.
- SD card write started (watched progress in Imager). Next: fit the Active Cooler to the Pi 5 board.

**Open flags / to-verify:**
- Pi 5 camera adapter cable (22-pin → 15-pin) likely still needed — Camera Module 3 ships only the 15-pin cable, which does not fit the Pi 5. Verify when the camera box is opened.
- micro-HDMI gap (only full-size HDMI present) → running headless for now.
- "Active Cooler" box carried a contradictory sticker labelling it a "Case" (CM5A221) — confirm it's the fan cooler when opened.

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
