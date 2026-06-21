# DEVLOG — Lullaby build journal

Reverse-chronological. Keep entries short: what changed, what was learned, what is next. Canonical decisions and status belong in [memory.md](memory.md).

---

## 21 June 2026 — Tier 1 started

Mo explicitly approved starting Tier 1. The first slice keeps the build
laptop-first: a configurable soothe ladder can run in dry-run mode, write
`SOOTHE` lines to the night log, mention soothe attempts in the digest, and
move parent notification until after the ladder when crying persists.

**Next single outcome:** test a real local soothing audio file at low laptop
volume, then decide whether to bench-test the Pi speaker/amplifier.

### Generated soothe assets

Added synthetic local WAV assets for white noise, heartbeat-style pulses, and
soothing music. The default ladder points at them, but playback is still off
unless soothing is explicitly enabled and `soothe.player` is set to `auto`.

**Next single outcome:** preview the assets at low laptop volume.

## 18 June 2026 — project pivot

Lab Witness is retired as the main project and preserved under `Archive/`. The repository is now Lullaby, a privacy-first baby-monitor companion.

The active scope is Tier 0 only: process sample audio or a microphone locally, detect sustained crying with YAMNet, write a night log, generate a rule-based morning digest, and send one debounced notification. Development starts on a laptop with no nursery hardware attached.

**Next single outcome:** run the included sample recording end-to-end and open the generated log and digest.

### Tier 0 completed

The hardware-free spine now runs end-to-end. The public CC0 sample triggers one sustained-cry event and one console notification, then writes `events.json`, `night-log.txt`, and `morning-digest.txt`. Tests use injected detector scores, so they stay fast and offline.

YAMNet remains a trigger, not a source of truth: its output is logged as an uncalibrated model score and must be tuned against the real room. No private recording or model weight is committed.

**Next single outcome:** Mo reviews the Tier 0 outputs and decides whether Tier 1 should start.
