# Lullaby

Lullaby is a privacy-first baby-monitor companion. Tier 0 processes audio locally, records sustained crying events, writes a readable night log, and produces a morning digest. Later tiers may try a gentle soothe step before escalating. It is an assistive notebook, not a medical guardian: raw audio/video never leaves the device, uncertain interpretations are labelled best guesses, and the complete app works with cloud features disabled.

## What works now

- Laptop `.wav` input and optional live microphone input.
- Official YAMNet TFLite `Baby cry, infant cry` model score.
- Deterministic confidence threshold, sustained-duration debounce, release delay, and notification cooldown.
- Optional Tier 1 dry-run soothe ladder before parent notification.
- Local `events.json`, readable `night-log.txt`, and `morning-digest.txt`.
- Console notification plus best-effort macOS/Linux desktop notification.
- Optional provider-neutral LLM digest polish, disabled by default and restricted to derived event text.
- Tests that require no model download, microphone, hardware, or API key.

## Laptop quickstart

Use Python 3.11–3.14. The commands below use the machine’s `python3`; substitute `python3.12` if you want the exact version used for the primary acceptance run.

```bash
cd ~/Code/Labie
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ".[dev]"
```

Run the included public sample:

```bash
lullaby --config config/default.toml analyze \
  sample_data/crying_baby_cc0.wav \
  --output output/sample-night
```

The first run downloads and verifies the official 3.9 MB YAMNet TFLite model into `~/.cache/lullaby/models/`. The audio file is then processed locally. You should see:

```text
[Lullaby] Sustained crying detected (...). Please check the baby.
Lullaby detected 1 sustained crying episode...
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

## Try the Tier 1 soothe ladder

Tier 1 is explicit and off in the default config. The demo config uses dry-run
playback, so it records the soothe step without playing sound:

```bash
lullaby --config config/tier1-demo.toml analyze \
  sample_data/crying_baby_cc0.wav \
  --output output/tier1-demo
```

You should see a digest that says Lullaby tried one soothe step before
escalation. Open the readable log:

```bash
cat output/tier1-demo/night-log.txt
```

Expected: a `SOOTHE` line before any `NOTIFIED` line. The default ladder now
has three generated local sounds:

- [white_noise.wav](assets/soothe/white_noise.wav)
- [heartbeat.wav](assets/soothe/heartbeat.wav)
- [soothing_music.wav](assets/soothe/soothing_music.wav)

To test real playback later, edit [config/default.toml](config/default.toml),
set `soothe.player = "auto"`, keep the volume low, and run with `--soothe`.

To preview the generated sounds directly on your Mac:

```bash
afplay assets/soothe/white_noise.wav
afplay assets/soothe/heartbeat.wav
afplay assets/soothe/soothing_music.wav
```

## Run the tests

```bash
python -m pytest
```

Expected: all tests pass in under a few seconds. The tests use fake detector scores, so they do not download YAMNet.

## Use a microphone

Install the optional microphone dependency:

```bash
python -m pip install ".[mic]"
```

On Raspberry Pi OS you may also need:

```bash
sudo apt install libportaudio2
```

Listen for 60 seconds:

```bash
lullaby --config config/default.toml listen \
  --seconds 60 \
  --output output/live
```

The microphone adapter records 16 kHz mono windows and runs the same detector and state machine as the WAV workflow.

## Tune false alarms

Edit [config/default.toml](config/default.toml):

- `threshold`: minimum YAMNet baby-cry model score. Default `0.40`.
- `sustained_seconds`: how long the score must remain high before an event/notification. Default `1.5`.
- `release_seconds`: how long it must remain low before the episode ends.
- `notification_cooldown_seconds`: minimum time between notifications.

YAMNet scores are uncalibrated model scores, not probabilities. Tune against recordings from the real room before relying on notifications.

## Tune soothing

Edit [config/default.toml](config/default.toml):

- `soothe.enabled`: default `false`; can also be enabled per run with `--soothe`.
- `soothe.player`: `none` logs a dry run; `auto` plays a configured local sound file.
- `soothe.steps[].name`: label shown in the night log.
- `soothe.steps[].sound_path`: local audio file to play when `player = "auto"`.
- `soothe.steps[].wait_seconds`: how long Lullaby waits before the next soothe step or parent notification.

The included generated sounds are synthetic placeholders for testing the ladder,
not evidence that a particular sound will soothe a baby.

Keep the first real audio tests on a laptop at low volume before wiring the Pi speaker.

## Optional LLM polish

The rule-based digest is the default and needs no account. To try a compatible chat-completions provider:

```bash
cp .env.example .env
# Edit .env, then:
set -a
source .env
set +a
lullaby --config config/default.toml analyze \
  sample_data/crying_baby_cc0.wav \
  --output output/sample-night-llm \
  --llm
```

Only derived event text and the rule-based summary are sent. Raw audio is never sent. Never commit `.env`.

## Layout

```text
src/lullaby/       application code
tests/             hardware-free tests
sample_data/       public CC0 verification recording
config/            deterministic thresholds and feature flags
output/            generated logs (gitignored)
Archive/           retired Lab Witness material
```

## Project documents

- [memory.md](memory.md) — canonical state and decisions
- [baby-monitor-build-plan.md](baby-monitor-build-plan.md) — tiered build plan and BOM
- [baby-monitor-evaluation.md](baby-monitor-evaluation.md) — evaluation and safety gate
- [ROADMAP.md](ROADMAP.md) — Tier 0–5 sequence

## Safety and privacy

Lullaby does not diagnose illness, detect SIDS/apnoea/fever, or replace adult supervision or approved monitoring equipment. Keep any companion beside the cot, never in it, and keep hot compute in a vented base.
