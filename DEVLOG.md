# DEVLOG — Lab Witness build journal

Reverse-chronological. One block per day: **what got done · what's blocked · the single outcome for tomorrow.** This is also raw material for the Demo Night story — keep it honest, keep it short. Canonical decisions/status live in [memory.md](memory.md); the forward plan / build sequence lives in [ROADMAP.md](ROADMAP.md) — check each day's outcome against the current tier (A → B → C). This file is the narrative of *what actually happened at the bench*.

---

## Sat 13 Jun 2026 — Workshop #1 — assembly

> Same day as the Day-0 block below; logged separately as the day's mode shifted from ordering to building.

We're in-person at Workshop #1 — 3D printers humming, a full tool bench, mentors on hand. The plan flips from *ordering* to *assembly*: all kit is in hand and the Pi 5 rig is on the table in front of me, so today is hands-on.

**Timeline revised** (Mo's confirmation): Workshop #1 today (13 Jun) · home/remote tinkering 14–20 Jun · Workshop #2 (integration) Sun 21 Jun · demo ≈28 Jun (was 7 Jul) · v0 freeze PROPOSED ~24 Jun (was 20 Jun, pending Mo's sign-off). Canonical dates live in [memory.md](memory.md).

**Compute call changed (Mo, today):** use the **AI HAT+ 26 TOPS (Hailo-8)** for v0. The HAT is in hand and fits on the Pi 5, so v0 vision runs Hailo-accelerated detection rather than CPU-first OpenCV (state machine + timing logic still on the CPU). This reverses the earlier "no AI HAT+ for v0" call — see [memory.md](memory.md).

**First assembly tasks (today)**
- Clip the active cooler onto the Pi 5.
- Fit the **AI HAT+ (Hailo-8)** on top (stacks over the cooler via the GPIO header + standoffs; PCIe ribbon to the Pi).
- Flash Pi OS to the microSD card.
- Connect Camera Module 3 (Pi-5-compatible cable).
- 3D-print a top-down camera mount.
- First boot + grab a test photo.

**Still open**
- CV/embedded dev not yet confirmed — rig's here, but no one to own it from week two yet.
- Ordered step-list for the dilution series still to write (Mo's bench intuition = ground truth).

**Progress so far:** microSD flashed with Raspberry Pi OS (64-bit); Wi-Fi + SSH configured; running **headless** (no micro-HDMI on hand, so controlled from the laptop over Wi-Fi). Active cooler going on next. Full step-by-step lives in [BUILD.md](BUILD.md).

**Blocked / to-verify:** Pi-5 camera adapter cable (22→15 pin) likely still needed (verify on opening the camera box); SSH password to confirm at first boot; confirm the cooler part is the fan cooler, not a passive case.

### Evening — first boot achieved 🎉

We have first boot — the Pi 5 is online. Getting there was a slog. I tried for ages to reach it **headless** over wifi and got nowhere: `labwitness.local` never resolved (mDNS just wouldn't answer), Raspberry Pi Connect showed no device, and SSH to every IP on the LAN came back refused or timed out. Hours gone, convinced something was badly broken.

The breakthrough was plugging in a **monitor via micro-HDMI** (the port nearest the USB-C), following the hackathon's official "London Calling / Edge AI on a Raspberry Pi" quickstart — which quietly assumes a monitor + keyboard + mouse for first boot. The moment a screen came up it was obvious: the Pi had booted fine all along. It simply hadn't **joined the wifi** — network icon showing a red slash, clock wrong because it never synced. I connected wifi **manually** via the desktop network icon and it was straight online.

Lessons, written down so I never lose this evening again:

- **The kit/guide assumes a monitor for first boot.** Headless-only (SSH over wifi) was the hard path and failed silently. Reliable first boot = monitor (micro-HDMI, port nearest USB-C) + keyboard/mouse.
- **The AI HAT+ was not the problem** — the Pi booted cleanly with it mounted. (The HAT is now the v0 vision compute — see [memory.md](memory.md).)
- **The OS/flash were always fine.** The one real gremlin was the wifi auto-join from the Imager config not taking — fixed by connecting manually on the desktop.
- **A micro-HDMI connection is required** to get a screen on the Pi 5 (only full-size HDMI was on hand earlier — this was the missing piece).

### Late night — the Pi can see 👁️

Connected the Camera Module 3 to the Pi 5 via the Pi-5 adapter cable (narrow 22-pin end into the Pi, wide 15-pin end into the camera). `rpicam-hello --list-cameras` picked up **camera 0: imx708** — the Camera Module 3 sensor — straight away. Then ran the full remote loop end-to-end and it all worked: SSH from the Mac into the Pi, `rpicam-still` to grab a still on the Pi, `scp` to pull it back to the Mac. The pipeline's there.

One snag: the images came out **black**. The camera itself is fine — it detects and captures cleanly — but the lens is still covered. The Camera Module 3 ships with a clear protective film on the lens and it's almost certainly still on (the capture showed analog gain pinned at 16, i.e. starved for light), plus it was the small hours and dark. Next session's fix is a ten-second job: peel the film off the lens, point it at a lit scene, re-shoot. After that it's ready for object detection — the `~/vision` venv is already set up.

---

## Day 0 — Fri 13 Jun 2026

**Done**
- Gates locked: mock bench (Blue Garage) · serial-dilution protocol · timing-only deviations · Pi 5 4GB + Cam Module 3 + **AI HAT+ 26 TOPS (Hailo-8), used for v0** (Hailo-accelerated detection; state machine + timing on CPU). *(Updated 13 Jun: HAT now in hand — reverses the earlier CPU-first/no-HAT call.)*
- Project operating system set up: CLAUDE.md, context.md, agents.md, skills.md, memory.md.
- Judging rubric confirmed: Novelty · Deployment · Impact (was four axes).

**Blocked / open**
- Kit not yet ordered — shipping is the silent killer against 20 Jun.
- CV/embedded dev not yet confirmed (owns the rig from Day 7 — non-negotiable).
- Ordered step-list for the dilution series not yet written (Mo's bench intuition = ground truth).
- Hardware gaps noted: microSD, Pi-5 camera cable, micro-HDMI (see hardware-inventory).

**Tomorrow's single outcome (Day 1)**
- Flash Pi OS, boot, camera live, run a Hailo-accelerated detection demo on the Pi 5 via the **AI HAT+ (Hailo-8)**. Pure "does the rig see anything" day.
