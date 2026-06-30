<div align="center">

# Beddington

**A privacy-first baby cry monitor that runs entirely on your own device. No cloud, no streaming, no account.**

<br />

[![Star this repo](https://img.shields.io/github/stars/moelzek/Beddington?style=for-the-badge&logo=github&label=%E2%AD%90%20Star%20this%20repo&color=yellow)](https://github.com/moelzek/Beddington/stargazers)
&nbsp;&nbsp;
[![Follow @moelzek](https://img.shields.io/badge/Follow_%40moelzek-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/moelzek)

<br />

[![Python 3.11–3.14](https://img.shields.io/badge/python-3.11%E2%80%933.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
&nbsp;
[![Runs on Raspberry Pi](https://img.shields.io/badge/runs%20on-Raspberry%20Pi-A22846?style=for-the-badge&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
&nbsp;
[![Data stays on device](https://img.shields.io/badge/data-100%25%20on--device-2EA043?style=for-the-badge)](#privacy-and-safety)

---

Most baby monitors send audio and video to a vendor's cloud. Beddington keeps everything on the device in front of you. It listens for sustained crying, logs each episode, writes a plain-language night log and a morning digest, and can play one soothing sound before it pings you. Raw audio and video never leave the device. It is an assistive notebook for tired parents, not a medical device, and it runs with every cloud feature switched off.

[Quickstart](#quickstart) · [How it works](#how-it-works) · [Features](#what-it-does-today) · [Configuration](#configuration) · [Privacy](#privacy-and-safety)

</div>

## Why Beddington exists

You want to know when your baby is crying. You do not want a microphone in the nursery uploading your child's sounds to someone else's servers, on someone else's terms, with someone else's retention policy.

Beddington runs the cry detection on your own hardware, a Raspberry Pi or a laptop. The audio is analysed on the device and thrown away. What you keep is a short event record, a readable night log, and a morning digest. Nothing about your night leaves the room unless you explicitly turn on the optional text-only digest polish.

## What it does today

| What | How |
|---|---|
| On-device cry detection | The official YAMNet TFLite "Baby cry, infant cry" model, run locally on your audio |
| Fewer false alarms | A confidence threshold, sustained-duration debounce, release delay, and notification cooldown you can tune |
| Readable night log + morning digest | Plain-text `night-log.txt` and `morning-digest.txt`, plus a structured `events.json` |
| One soothing sound, your choice | Optional Tier 1 plays one selected sound or music preset before it notifies you |
| Quiet checks while soothing | Pauses, listens, and requires repeated quiet readings before it logs that crying has stopped |
| Laptop or Raspberry Pi | A `.wav` file or a live USB microphone runs the same detector and state machine |
| Private by construction | Raw audio and video never leave the device; cloud features are off by default |
| Optional LLM digest polish | Only derived event text is sent, and only when you pass `--llm` |

## Quickstart

Use Python 3.11 to 3.14.

```bash
git clone https://github.com/moelzek/Beddington.git
cd Beddington
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ".[dev]"
```

Point `analyze` at any short `.wav` of a crying baby. A 10 to 30 second clip is plenty. The development sample recording is kept out of this public repo, so bring your own audio file:

```bash
beddington --config config/default.toml analyze path/to/crying.wav \
  --output output/sample-night
```

The first run downloads and verifies the official 3.9 MB YAMNet TFLite model into `~/.cache/beddington/models/`, then processes the audio locally. You should see something like:

```text
[Beddington] Sustained crying detected (...). Please check the baby.
Beddington detected 1 sustained crying episode...
Events: output/sample-night/events.json
Readable log: output/sample-night/night-log.txt
Morning digest: output/sample-night/morning-digest.txt
```

Open the three output files:

```bash
cat output/sample-night/night-log.txt
cat output/sample-night/morning-digest.txt
python -m json.tool output/sample-night/events.json
```

Generated output is gitignored.

## How it works

```text
  microphone or .wav            YAMNet (on-device)          deterministic state machine            you
 ───────────────────►  cry score  ───────────────►  threshold · debounce · cooldown  ───────►  night log
                                                            + optional soothe preset             morning digest
                                                                                                 notification
```

1. Audio comes from a `.wav` file or a live 16 kHz mono microphone window.
2. The local YAMNet model returns a baby-cry score for each window. The audio is then discarded.
3. A deterministic state machine decides what counts as a real episode: the score must clear a threshold, stay high for a sustained duration, and respect a release delay and a cooldown between notifications.
4. Optionally, Beddington plays one configured soothe preset and runs quiet checks before it escalates to a notification.
5. You get an `events.json`, a readable `night-log.txt`, and a `morning-digest.txt`.

Detection and timing are deterministic. The optional language model only ever rewrites the final text digest, and only if you ask it to.

## More commands

```bash
# Listen on a live microphone for 60 seconds (needs the mic extra)
python -m pip install ".[mic]"
beddington --config config/default.toml listen --seconds 60 --output output/live

# Try the Tier 1 soothe preset in dry-run mode (records the preset, no sound)
beddington --config config/tier1-demo.toml analyze path/to/crying.wav --output output/tier1-demo

# Preview the selected soothe sound through your speaker, briefly
beddington --config config/default.toml preview-soothe --seconds 5

# Run the hardware-free test suite (no model download, no mic, no API key)
python -m pytest
```

On Raspberry Pi OS the microphone path may also need `sudo apt install libportaudio2`.

Beddington also has bench-only, local-only camera utilities (`camera-smoke`, `visual-change`, `camera-change`) that write derived metrics and delete raw frames by default. They do not run nursery video, and video never triggers or suppresses a notification.

## Configuration

Everything lives in [config/default.toml](config/default.toml). The knobs that matter most for false alarms:

| Setting | What it does | Default |
|---|---|---|
| `threshold` | Minimum YAMNet baby-cry score to count | `0.40` |
| `sustained_seconds` | How long the score must stay high before an event | `1.5` |
| `release_seconds` | How long it must stay low before the episode ends | — |
| `notification_cooldown_seconds` | Minimum time between notifications | — |

YAMNet scores are uncalibrated model scores, not probabilities. Tune them against recordings from your own room before you rely on notifications. Soothe behaviour (`soothe.enabled`, `soothe.preset`, `soothe.player`, and the `quiet_check` block) is documented in the same file.

The bundled soothe sounds in [assets/soothe/](assets/soothe/) are local audition assets for testing the preset path and dashboard controls. The womb-like file is research/audition material, not medical or safety evidence, and not evidence that any sound will settle a given baby.

## What's inside

```text
src/beddington/    application code
tests/             hardware-free tests
config/            deterministic thresholds and feature flags
assets/soothe/     local soothe sounds and dashboard catalog
output/            generated logs (gitignored)
```

## Privacy and safety

- Raw audio and video never leave the device. Only derived event text is ever sent anywhere, and only when you pass `--llm`.
- Beddington does not diagnose illness and does not detect SIDS, apnoea, or fever. It is not a medical device and does not replace adult supervision or approved monitoring equipment.
- Uncertain interpretations are labelled **best guess**.
- Keep the companion beside the cot, never in it, and keep hot compute in a vented base.
- The complete app works with every cloud feature disabled. Never commit your `.env`.

---

<div align="center">

Built by [Mo Elzek](https://github.com/moelzek)

<br />

**If Beddington is useful to you, star it so other parents can find it.**

[![Star this repo](https://img.shields.io/github/stars/moelzek/Beddington?style=for-the-badge&logo=github&label=%E2%AD%90%20Star%20this%20repo&color=yellow)](https://github.com/moelzek/Beddington/stargazers)
&nbsp;&nbsp;
[![Follow @moelzek](https://img.shields.io/badge/Follow_%40moelzek-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/moelzek)

</div>
