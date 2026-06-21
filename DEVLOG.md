# DEVLOG — Lullaby build journal

Reverse-chronological. Keep entries short: what changed, what was learned, what is next. Canonical decisions and status belong in [memory.md](memory.md).

---

## 21 June 2026 — Tier 1 started

### Laptop playback gate

Low-volume laptop preview playback worked for the generated white-noise,
heartbeat-style, and soothing-music presets. A short repeated white-noise loop
also worked on the laptop.

**Next single outcome:** move to a Bluetooth speaker playback test on the Pi,
before wiring one MAX98357 speaker bench test.

### Hardware inventory guide

Mo added exact wiring notes for the owned servos, PCA9685 boards, USB-C PD
trigger boards, MAX98357 amplifiers, speakers, INMP441 mics, VL53L0X sensors,
HC-SR04 sensors, and OLEDs. Captured them in `hardware-guide.md` with a
bench-test order that keeps the simplest Pi tests first.

**Next single outcome:** run a Bluetooth speaker playback test on the Pi, then
move to one MAX98357 speaker bench test.

Mo explicitly approved starting Tier 1. The first slice keeps the build
laptop-first: a configurable soothe preset can run in dry-run mode, write
`SOOTHE` lines to the night log, mention soothe attempts in the digest, and
move parent notification until after the selected preset when crying persists.

**Next single outcome:** test a real local soothing audio file at low laptop
volume, then decide whether to bench-test the Pi speaker/amplifier.

### Generated soothe assets

Added synthetic local WAV assets for white noise, heartbeat-style pulses, and
soothing music. The default presets point at them, but playback is still off
unless soothing is explicitly enabled and `soothe.player` is set to `auto`.

**Next single outcome:** preview the assets at low laptop volume.

Added a stronger synthetic `uterine_whoosh.wav`. It is a womb-like
rumble/whoosh for output testing, not a recording or a soothe claim.

Mo pointed out that a few seconds is not a realistic settling window; it may
take around 30 minutes. The player now loops short local WAV files for a
separate `play_seconds` window; presets can now be configured for 30-minute
play windows.

Mo also clarified the product behaviour: parents should choose one soothe mode,
not have Lullaby cycle through every sound. Config now uses `soothe.preset`
with named presets; `white_noise` is the default, with heartbeat-style pulses,
soothing music, and the synthetic uterine whoosh available.

## 18 June 2026 — project pivot

Lab Witness is retired as the main project and preserved under `Archive/`. The repository is now Lullaby, a privacy-first baby-monitor companion.

The active scope is Tier 0 only: process sample audio or a microphone locally, detect sustained crying with YAMNet, write a night log, generate a rule-based morning digest, and send one debounced notification. Development starts on a laptop with no nursery hardware attached.

**Next single outcome:** run the included sample recording end-to-end and open the generated log and digest.

### Tier 0 completed

The hardware-free spine now runs end-to-end. The public CC0 sample triggers one sustained-cry event and one console notification, then writes `events.json`, `night-log.txt`, and `morning-digest.txt`. Tests use injected detector scores, so they stay fast and offline.

YAMNet remains a trigger, not a source of truth: its output is logged as an uncalibrated model score and must be tuned against the real room. No private recording or model weight is committed.

**Next single outcome:** Mo reviews the Tier 0 outputs and decides whether Tier 1 should start.
