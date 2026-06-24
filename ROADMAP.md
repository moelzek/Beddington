# ROADMAP.md — Lullaby Tier 0–5

> Forward sequence only. Live state and decisions are in [memory.md](memory.md). Build one tier at a time; later tiers require Mo’s explicit approval.

## Feature placement from baby-monitor app screenshots

Mo wants the common baby-monitor app capabilities represented in the roadmap.
They are placed here, but still inherit Lullaby's privacy and safety rules.

| Screenshot feature | Roadmap placement | Notes |
|---|---|---|
| Smart baby monitoring: sound plus video | Tier 0 for local cry/audio detection; Tier 2 for local video | The wording stays assistive. Lullaby must not promise complete safety or replace adult supervision. |
| Smart noise and cry detection | Tier 0/Tier 1 audio pipeline, plus later audio refinements | Cry detection exists. Later important-sound classes can be added as local, tunable observations with false-alarm controls. |
| Instant alerts for noise | Tier 0 now; parent-app push alerts later | Current alerts are console/desktop. Phone push alerts belong in the parent-app layer after auth/privacy design. |
| Instant alerts for connection issues | Parent-app and reliability layer | Add Pi heartbeat, camera/microphone health checks, and "connection lost" alerts before any nursery reliance. |
| Instant alerts for low battery | Parent-app and power-health layer | The Pi is mains-powered today. Later alerts should cover Pi under-voltage, UPS/power-bank battery, and parent-device app status where available. |
| Advanced night vision | Tier 2 dark-room hardware decision | Requires NoIR camera plus safely mounted IR illumination. No night-video claim until the hardware and mount gate pass. |
| Multiple parent devices | Parent-app and sharing layer | Start with household pairing and derived alerts/digests. Live video on phones needs a separate privacy-boundary decision. |
| Share with family | Parent-app and sharing layer | Needs invite/revoke controls, roles, audit log, and encrypted transport. |
| Unlimited video monitoring | Tier 2 plus parent-app layer | Treat as local live viewing only after thermal, privacy, and mount gates. No cloud recording by default. |

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

Future audio refinements belong here only if they remain local and testable:
important-sound categories beyond crying, per-room calibration, better false
alarm review, and user-tunable alert thresholds.

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
- [ ] Pi MAX98357 speaker/amplifier bench test at low volume; deferred by Mo on 2026-06-23.
- [x] Pi live cry-detection smoke test with USB microphone.
- [x] Quiet-check loop: briefly lower or pause the selected preset, listen, and require repeated quiet checks before saying crying is no longer detected.
- [ ] Echo-cancellation experiment: use the known selected preset as a reference signal so the microphone can better ignore Lullaby’s own speaker.
- [ ] Recorded parent voice asset.
- [ ] Optional “likely hungry — best guess” from crying plus time since feed.

**Gate:** Mo approved starting Tier 1 on 2026-06-21. Keep work laptop-first
until the audio-output hardware is bench-tested safely.

### Current task: Tier 2A physical mock-up check

Purpose: turn [camera-mount-plan.md](camera-mount-plan.md) into a real proposed
location before any nursery camera use.

1. Choose the actual mount type and location.
2. Mark the 3-foot exclusion zone around the cot or sleep surface.
3. Sketch or photograph the camera, Pi base, power, and cable route.
4. Confirm there are no reachable cables, loops, loose parts, or cot-mounted
   hardware.
5. Run a bench thermal check before any long nursery run.
6. Keep raw frames local and video supporting-only.

### Future cry-stopped verification while soothing

- [ ] Keep audio ML as the primary signal for “crying still detected”.
- [ ] Add listen-only checks during long playback windows before marking crying as no longer detected.
- [ ] Require multiple quiet checks rather than one quiet moment.
- [ ] Use camera/video later only as supporting context: visible agitation, movement trend, or stillness trend.
- [ ] Use radar/breathing later only as non-medical context if approved; never as proof that the baby is safe, asleep, or breathing normally.
- [ ] If audio, video, or sensor context disagree, keep checking or notify the parent.
- [ ] Log wording must stay honest: “crying no longer detected”, not “baby is asleep” or “baby is safe”.

## Tier 2 — local video observations

- [x] Pi Camera Module 3 hardware smoke test: `imx708` detected and a local no-preview still capture succeeded.
- [x] Tier 2A bench-only video gate: privacy, false-alarm, mount, and dark-room boundaries documented.
- [x] `camera-smoke` command: file metadata path plus Pi no-preview capture path.
- [x] `visual-change` command: deterministic local PGM/PPM frame-difference metrics.
- [x] Camera-linked visual-change smoke test with raw frames deleted by default.
- [x] Cot-safe mount and cable-routing plan before nursery deployment.
- [ ] Physical mock-up: selected mount location, marked 3-foot exclusion zone, cable route, and vented base check.
- [ ] Baby-absent nursery smoke test that writes only derived JSON reports.
- [ ] Dark-room hardware decision before night video.
- [ ] NoIR plus IR-illumination bench test before any "night vision" wording.
- [ ] Local live video viewer prototype after physical, privacy, and thermal gates.
- [ ] Long-running local video thermal soak before any continuous-monitoring claim.
- File/OpenCV adapter for laptop development.
- picamera2/Hailo adapter for Pi deployment.
- Active/still and face-covered observations.
- Supporting context for soothe verification: visible agitation, movement trend, and stillness trend while audio remains primary.
- No raw frames leave the device.

**Gate:** privacy review, false-alarm plan, cot-safe mount, and dark-room hardware decision.

## Tier 3 — radar presence and movement

- [ ] Bench-read MR60BHA2 through its ESP32 Wi-Fi/MQTT bridge.
- [ ] Verify cot-distance signal quality and mounting outside reach.
- Presence and gross movement.
- Supporting context for soothe verification: presence and gross movement trends only.
- Breathing, if ever displayed, is a non-medical trend only and never drives an alarm or suppresses a parent notification by itself.

**Gate:** mentor safety sign-off.

## Tier 4 — nursery environment

- [ ] Bench-read BME688 locally: temperature, humidity, pressure, and gas-resistance style raw readings.
- [ ] Decide safe placement away from the cot, nappy changes, liquids, and grab/reach paths.
- [ ] Calibrate room baseline before using readings in a digest.
- Room temperature/humidity trend in the morning digest.
- Experimental nappy VOC as a clearly labelled best guess, only after calibration and hygiene review.
- No body-temperature, fever, illness, or air-safety claim.

**Gate:** calibration, placement, and hygiene plan.

## Tier 5 — optional thermal trend

- Relative warmth trend and local visualisation.
- Never described as body temperature or fever detection.

**Gate:** explicit decision that the value justifies the risk and complexity. Default is to cut.

## Other owned sensors and hardware

These are useful, but they are not the next product signal by default.

- [ ] VL53L0X distance sensor: near-term bench utility for mount/enclosure checks; not baby-state inference.
- [ ] HC-SR04 distance sensor: lower priority because it needs a voltage divider; bench utility only.
- [ ] OLED display: bench status screen after the core sensor paths are stable.
- [ ] INMP441 I2S microphones: later audio-hardware upgrade after USB microphone remains reliable.
- [ ] Servo/PCA9685 movement: bench prototyping only, with separate power; not cot deployment by default.

## Parent app and reliability layer

This is not a sensor tier. It starts only after the local core and the relevant
hardware gates are stable.

- [ ] Parent app shell with current status, recent events, night log, and digest.
- [ ] Household pairing for more than one trusted parent device.
- [ ] Family sharing with roles, invite/revoke controls, and an audit trail.
- [ ] Push notifications for sustained crying/noise events after the local debounce rules fire.
- [ ] Connection-health alerts: Pi heartbeat, camera/microphone unavailable, and parent app disconnected.
- [ ] Power-health alerts: Pi under-voltage, thermal throttling, and later UPS/power-bank battery where available.
- [ ] Local-network live video view only after the Tier 2 mount, privacy, dark-room, and thermal gates pass.
- [ ] Remote access decision: derived alerts and digests first; raw live audio/video off-device requires a separate explicit privacy decision.

**Gate:** authentication, encryption, local pairing, permission revocation,
privacy review, and no weakening of the raw-audio/video boundary without an
explicit future decision.

## Cut order

If time or attention is tight, cut from Tier 5 downward. Never weaken privacy, safety, deterministic operation, or the ability to run with the LLM off.
