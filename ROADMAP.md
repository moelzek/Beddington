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

- [x] Configurable single-preset soothe mode and wait period.
- [x] Dry-run laptop mode that records soothe attempts without playing sound.
- [x] Parent notification moves after the selected preset when soothing is enabled.
- [x] Night log and morning digest mention soothe attempts.
- [x] Generated local WAV assets for uterine-style whoosh, white noise, heartbeat-style pulses, and soothing music.
- [x] Loop the selected short soothe WAV for long configured play windows.
- [x] Available presets include `white_noise`, `heartbeat`, and `soothing_music`; `uterine_whoosh` remains optional.
- [x] Low-volume local preview playback test on laptop.
- [x] Short looped real playback test on laptop.
- [x] Pi Bluetooth speaker playback test with Anker SoundCore.
- [x] Pi USB microphone capture test through Lullaby's microphone adapter.
- [ ] Pi MAX98357 speaker/amplifier bench test at low volume.
- [x] Pi live cry-detection smoke test with USB microphone.
- [ ] Quiet-check loop: briefly lower or pause the selected preset, listen, and require repeated quiet checks before saying crying is no longer detected.
- [ ] Echo-cancellation experiment: use the known selected preset as a reference signal so the microphone can better ignore Lullaby’s own speaker.
- [ ] Recorded parent voice asset.
- [ ] Optional “likely hungry — best guess” from crying plus time since feed.

**Gate:** Mo approved starting Tier 1 on 2026-06-21. Keep work laptop-first
until the audio-output hardware is bench-tested safely.

### Current task: Quiet-check loop

Purpose: while a selected soothe preset is playing, briefly lower or pause
playback, listen through the microphone, and require repeated quiet checks
before logging that crying is no longer detected.

1. Keep audio ML as the primary signal.
2. Add deterministic quiet-check windows during long soothe playback.
3. Require multiple quiet checks before saying crying is no longer detected.
4. Keep wording honest: “crying no longer detected”, not “baby is asleep” or
   “baby is safe”.

### Future cry-stopped verification while soothing

- [ ] Keep audio ML as the primary signal for “crying still detected”.
- [ ] Add listen-only checks during long playback windows before marking crying as no longer detected.
- [ ] Require multiple quiet checks rather than one quiet moment.
- [ ] Use camera/video later only as supporting context: visible agitation, movement trend, or stillness trend.
- [ ] Use radar/breathing later only as non-medical context if approved; never as proof that the baby is safe, asleep, or breathing normally.
- [ ] If audio, video, or sensor context disagree, keep checking or notify the parent.
- [ ] Log wording must stay honest: “crying no longer detected”, not “baby is asleep” or “baby is safe”.

## Tier 2 — local video observations

- File/OpenCV adapter for laptop development.
- picamera2/Hailo adapter for Pi deployment.
- Active/still and face-covered observations.
- Supporting context for soothe verification: visible agitation, movement trend, and stillness trend while audio remains primary.
- No raw frames leave the device.

**Gate:** privacy review, false-alarm plan, cot-safe mount, and dark-room hardware decision.

## Tier 3 — radar presence and movement

- MR60BHA2 through its ESP32 Wi-Fi/MQTT bridge.
- Presence and gross movement.
- Supporting context for soothe verification: presence and gross movement trends only.
- Breathing, if ever displayed, is a non-medical trend only and never drives an alarm or suppresses a parent notification by itself.

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
