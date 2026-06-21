# ROADMAP.md — Lullaby Tier 0–5

> Forward sequence only. Live state and decisions are in [memory.md](memory.md). Build one tier at a time; later tiers require Mo’s explicit approval.

## Tier 0 — audio spine

**Outcome:** a complete hardware-free nightly loop.

- WAV files on laptop and microphone adapter for Pi.
- YAMNet baby-cry detection behind an interface.
- Deterministic sustained-cry threshold, debounce, and cooldown.
- Timestamped JSON night log plus readable text log.
- Rule-based morning digest.
- Console notification and best-effort desktop notification.
- Optional LLM digest polish behind a disabled-by-default flag.
- Included sample audio and tests.

**Done when:** the README’s sample command produces detections, one sustained-cry notification, a night log, and a morning digest on a laptop with no hardware or cloud key.

## Tier 1 — soothe before escalation

- [x] Configurable soothe ladder and wait periods.
- [x] Dry-run laptop mode that records soothe attempts without playing sound.
- [x] Parent notification moves after the ladder when soothing is enabled.
- [x] Night log and morning digest mention soothe attempts.
- [x] Generated local WAV assets for white noise, heartbeat-style pulses, and soothing music.
- [ ] Real local audio-file playback test on laptop.
- [ ] Pi speaker/amplifier bench test at low volume.
- [ ] Recorded parent voice asset.
- [ ] Optional “likely hungry — best guess” from crying plus time since feed.

**Gate:** Mo approved starting Tier 1 on 2026-06-21. Keep work laptop-first
until the audio-output hardware is bench-tested safely.

## Tier 2 — local video observations

- File/OpenCV adapter for laptop development.
- picamera2/Hailo adapter for Pi deployment.
- Active/still and face-covered observations.
- No raw frames leave the device.

**Gate:** privacy review, false-alarm plan, cot-safe mount, and dark-room hardware decision.

## Tier 3 — radar presence and movement

- MR60BHA2 through its ESP32 Wi-Fi/MQTT bridge.
- Presence and gross movement.
- Breathing, if ever displayed, is a non-medical trend only and never drives an alarm.

**Gate:** mentor safety sign-off.

## Tier 4 — nursery environment

- Room temperature/humidity.
- Nappy VOC as a clearly labelled best guess.

**Gate:** calibration, placement, and hygiene plan.

## Tier 5 — optional thermal trend

- Relative warmth trend and local visualisation.
- Never described as body temperature or fever detection.

**Gate:** explicit decision that the value justifies the risk and complexity. Default is to cut.

## Cut order

If time or attention is tight, cut from Tier 5 downward. Never weaken privacy, safety, deterministic operation, or the ability to run with the LLM off.
