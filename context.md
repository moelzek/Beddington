# context.md — Lullaby: what and why

> Durable orientation. Live state and locked decisions are in [memory.md](memory.md).

## One-line purpose

Lullaby is a privacy-first baby-monitor companion that turns local observations into a useful overnight pattern and, in later tiers, tries a gentle soothe step before escalating to a parent.

## The problem

A simple “the baby is crying” alert often repeats something a parent can already hear. The more useful jobs are:

1. **Aggregate:** reconstruct the night into a pattern a sleep-deprived parent cannot reliably perceive at 03:00.
2. **Act:** attempt a configurable soothe step before escalating, while keeping the parent in control.

Tier 0 proves the first job with cry events, a night log, and a morning digest. Tier 1 introduces the second.

## What Lullaby is

- An assistive night notebook.
- A local-first event detector and logger.
- A hardware-free-first software project that later deploys to a Raspberry Pi 5.
- A deterministic application with an optional LLM for prose polish only.

## What Lullaby is not

- Not a medical device or diagnostic system.
- Not a SIDS, apnoea, fever, or vital-sign monitor.
- Not a replacement for adult supervision or approved monitoring equipment.
- Not a system that uploads nursery audio or video.
- Not a source of certainty about why a baby is crying.

## Product principles

- **Privacy is architectural:** raw audio/video stays on the device.
- **Honesty beats theatre:** uncertain interpretations are labelled best guesses with confidence.
- **Useful before clever:** Tier 0 works without a camera, cloud account, or connected hardware.
- **Safe physical design:** hot compute is vented and separate from any soft companion; nothing enters the cot.
- **Small replaceable adapters:** file inputs and mocks on a laptop swap for mic, picamera2, Hailo, or sensors later.

## Intended architecture

- Audio cry detection runs locally on CPU using YAMNet behind a detector interface.
- Video later runs locally through OpenCV/file adapters on a laptop and picamera2/Hailo on the Pi.
- Radar later remains its own ESP32 subsystem and sends small derived readings over Wi-Fi/MQTT.
- Logs and summaries are local by default.
- An optional cloud LLM receives only derived events/features/short text and never controls detection or timing.

## Success for Tier 0

A beginner can follow the README on a laptop, process an included sample `.wav`, see sustained-cry events, receive one debounced notification, and open both the night log and morning digest. No hardware or API key is attached.
