# Lullaby

Lullaby is a privacy-first baby-monitor companion. Tier 0 processes audio locally, records sustained crying events, writes a readable night log, and produces a morning digest. Tier 1 may try one selected soothe preset before escalating. It is an assistive notebook, not a medical guardian: raw audio/video never leaves the device, uncertain interpretations are labelled best guesses, and the complete app works with cloud features disabled.

## What works now

- Laptop `.wav` input and optional live microphone input.
- Official YAMNet TFLite `Baby cry, infant cry` model score.
- Deterministic confidence threshold, sustained-duration debounce, release delay, and notification cooldown.
- Optional Tier 1 dry-run soothe preset before parent notification.
- Optional deterministic quiet-check windows during soothing.
- Short selected-preset soothe preview, including confirmed Pi Bluetooth playback.
- Pi USB microphone capture through Lullaby's microphone adapter.
- Pi Camera Module 3 hardware smoke test and Tier 2A bench-only camera metadata command.
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

## Try the Tier 1 soothe preset

Tier 1 is explicit and off in the default config. The demo config uses dry-run
playback, so it records the selected soothe preset without playing sound:

```bash
lullaby --config config/tier1-demo.toml analyze \
  sample_data/crying_baby_cc0.wav \
  --output output/tier1-demo
```

You should see a digest that says Lullaby tried one soothe preset before
escalation. Open the readable log:

```bash
cat output/tier1-demo/night-log.txt
```

Expected: a `SOOTHE` line before any `NOTIFIED` line. Lullaby chooses exactly
one configured preset; it does not cycle through every sound. The default
preset is `white_noise`. Available generated presets are:

- [uterine_whoosh.wav](assets/soothe/uterine_whoosh.wav)
- [white_noise.wav](assets/soothe/white_noise.wav)
- [heartbeat.wav](assets/soothe/heartbeat.wav)
- [soothing_music.wav](assets/soothe/soothing_music.wav)

The files themselves are short, but Lullaby can loop the selected preset for
the configured `play_seconds`. The default presets are set up for 30-minute
play windows when real playback is enabled.

To test real playback without running cry detection, select the speaker output
on the machine first, keep the volume low, then run:

```bash
lullaby --config config/default.toml preview-soothe --seconds 5
```

Expected: the selected `white_noise` preset plays briefly and then stops. This
has already passed on the Pi through a Bluetooth speaker. The quiet-check
software gate has also passed. The MAX98357 wired speaker test is deferred;
the active bench path is now Tier 2A camera metadata plumbing.

To preview the generated sounds directly on your Mac:

```bash
afplay assets/soothe/uterine_whoosh.wav
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

## Use the camera smoke test

Tier 2A is bench-only local video plumbing. It does not run nursery video
features and does not use video to trigger or suppress notifications.

On the Pi, run:

```bash
lullaby camera-smoke --output output/pi-camera-smoke
```

Expected: Lullaby captures one local no-preview test frame, writes
`output/pi-camera-smoke/camera-smoke.json`, and deletes the raw test frame by
default. The report contains derived metadata such as image size and camera
summary, not raw image data.

For hardware-free tests on a laptop, inspect an existing local JPEG or PNG:

```bash
lullaby camera-smoke --image path/to/local-test-image.jpg --output output/camera-smoke
```

Raw frames must stay local and must not be committed. The Tier 2 video boundary
is captured in [tier2-video-gate.md](tier2-video-gate.md).

## Compare local test frames

Use `visual-change` for the first deterministic derived video observation. It
compares two local PGM/PPM test frames and writes only change metrics:

```bash
lullaby visual-change \
  --before path/to/before.pgm \
  --after path/to/after.pgm \
  --output output/visual-change
```

Expected: `output/visual-change/visual-change.json` contains
`mean_absolute_difference`, `changed_pixel_ratio`, and either
`visual_change_detected` or `little_visual_change_detected`. This is a local
visual-change metric only, not a safety, sleep, breathing, or face-covering
assessment.

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
- `soothe.preset`: the one preset to use, such as `white_noise`, `heartbeat`, or `soothing_music`.
- `soothe.presets.<name>.sound_path`: local audio file to play when `player = "auto"`.
- `soothe.presets.<name>.play_seconds`: how long that preset may loop.
- `soothe.presets.<name>.wait_seconds`: how long Lullaby waits before parent notification.
- `soothe.quiet_check.enabled`: briefly pause or lower playback, listen, and
  require repeated quiet checks before logging that crying is no longer
  detected.
- `soothe.quiet_check.check_interval_seconds`: how often to run a quiet check
  while soothing is active.
- `soothe.quiet_check.listen_seconds`: how long each listen-only check lasts.
- `soothe.quiet_check.required_checks`: how many consecutive quiet checks are
  required. This must be at least `2`.
- `soothe.quiet_check.stop_on_notify`: stop playback when Lullaby escalates to a
  parent notification.

The included generated sounds are synthetic placeholders for testing the preset.
The uterine-style file is a generated womb-like rumble/whoosh, not a recording
and not evidence that a particular sound will soothe a baby.

Keep real audio tests at low volume. Do not wire the MAX98357 speaker bench test
unless the Pi is powered off first.

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
- [hardware-guide.md](hardware-guide.md) — wiring notes and bench-test order for owned parts
- [ROADMAP.md](ROADMAP.md) — Tier 0–5 sequence
- [tier2-video-gate.md](tier2-video-gate.md) — Tier 2A privacy, false-alarm, mount, and dark-room boundaries

## Safety and privacy

Lullaby does not diagnose illness, detect SIDS/apnoea/fever, or replace adult supervision or approved monitoring equipment. Keep any companion beside the cot, never in it, and keep hot compute in a vented base.
