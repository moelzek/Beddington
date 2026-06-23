# DEVLOG — Lullaby build journal

Reverse-chronological. Keep entries short: what changed, what was learned, what is next. Canonical decisions and status belong in [memory.md](memory.md).

---

## 23 June 2026 - Tier 2A camera-smoke command

Mo asked to move to the next steps directly without waiting for another
approval. Captured the Tier 2A boundary in `tier2-video-gate.md`: bench-only
local video plumbing is allowed, while nursery deployment, face-covered
claims, Hailo, night vision, and any safety/asleep/breathing wording remain
gated.

Added `lullaby camera-smoke`. It can inspect an existing local JPEG/PNG for
hardware-free tests, or capture one no-preview Pi frame through `rpicam-still`.
The command writes only derived metadata to `camera-smoke.json` and deletes the
raw test frame by default.

Verified locally and on the Pi: 39 tests pass. On the Pi, `camera-smoke`
detected the `imx708` camera, produced a 640×480 JPEG metadata report, and left
only `output/pi-camera-smoke/camera-smoke.json`.

**Next single outcome:** add the first deterministic derived video observation
using local files/mocks before using the camera for any nursery context.

## 23 June 2026 - Camera hardware smoke test passed

Mo asked to put the MAX98357 wired-speaker bench test aside and move on. The
attached Camera Module 3 is visible on the Pi as `imx708`, with listed modes up
to 4608×2592. A no-preview `rpicam-still` capture produced a local 640×480
JPEG, metadata was readable, and the test image was deleted without copying raw
frames off the Pi.

**Next single outcome:** run the Tier 2 video gate review: privacy, false
alarms, cot-safe mounting/cable routing, and dark-room hardware decision.

## 23 June 2026 - Pi synced smoke gate passed

Installed a dedicated SSH key for `lab@lab.powerhub` so the Mac can reach the
Pi without repeated password prompts. Synced the quiet-check code to
`~/Labie`, then ran the hardware-free test suite and the short Tier 1 sample on
the Pi. Both passed; the Pi sample still logs `SOOTHE` before `NOTIFIED`.

Ran a 12-second live USB-microphone smoke test on the Pi. It analysed 17 local
audio windows and detected no sustained crying, as expected for a non-cry
room test. The microphone stream printed a few input-overflow warnings, so
that is worth watching during longer runs.

**Next single outcome:** power the Pi off, then wire one MAX98357 amplifier to
one 3W 4Ω speaker for a low-volume bench test.

## 23 June 2026 - Quiet-check loop implemented

Added deterministic Tier 1 quiet-check windows. While soothing is active,
Lullaby can pause playback, listen through the audio detector, require repeated
quiet checks, and only then log that crying is no longer detected. Parent
notification now stops playback when soothing escalates.

**Next single outcome:** run the hardware-free suite and a short Tier 1 sample,
then re-run Claude's review on the quiet-check diff.

## 23 June 2026 - Pi Bluetooth playback gate passed

Re-imaged the Pi, logged in as `lab`, copied Lullaby to `~/Labie`, installed a
lightweight editable environment, and verified the hardware-free tests pass on
the Pi. Paired the Anker SoundCore over Bluetooth, selected it as the default
audio output, and played the generated `soothing_music` preset successfully.

**Next single outcome:** with Pi power unplugged, wire one MAX98357 amplifier to
one 3W 4Ω speaker for a low-volume bench test.

### USB microphone capture gate

The USB mic appears as `USB PnP Sound Device` / `PCM2902 Audio Codec`. A raw
ALSA 5-second recording worked and played back through the Anker SoundCore.
Lullaby's Python microphone adapter initially failed because the mic accepts
44.1/48 kHz directly rather than 16 kHz; the adapter now falls back to the
device's native input rate and resamples internally to 16 kHz. Full tests pass
on the Pi.

A live `lullaby listen` run then downloaded YAMNet, analysed 12 live microphone
windows locally, and wrote `output/pi-live-mic/` logs. That run exposed and
fixed a Pi cache bug where moving the downloaded model from `/tmp` to
`~/.cache` failed across filesystems.

**Next single outcome:** implement deterministic quiet-check windows while
soothe playback is active; keep the MAX98357 wiring deferred.

## 22 June 2026 - Pi playback preview helper

Added `lullaby preview-soothe` so the next Pi audio check can play the selected
soothe preset briefly without starting cry detection or editing config. The
command overrides the long 30-minute preset window for a short low-volume smoke
test.

**Next single outcome:** pair a Bluetooth speaker on the Pi and run
`lullaby --config config/default.toml preview-soothe --seconds 5`.

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
