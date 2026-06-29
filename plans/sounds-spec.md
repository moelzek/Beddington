# Beddington — add 8 soothe sounds (codex build spec)

You are an autonomous coding agent on **Beddington** (package `beddington` at
`src/beddington/`; tests in `tests/`). Implement **only the unit you are told**,
keep the WHOLE suite green, stdlib + numpy only (numpy is already used by the
generator — no NEW dependency). Never touch the stale gitignored `src/lullaby/`.

The soothe sounds are **synthesized procedurally** in
`scripts/generate_soothe_assets.py` and written to `assets/soothe/*.wav`
(16 kHz, mono, 16-bit). Existing helpers to reuse: `_white_noise`, `_low_pass`,
`_pulse`, `_attack_release`, `_fade`, `_normalise`, `_time`, `_sample_count`,
`_write_wav`, `SAMPLE_RATE`. Match the existing code style exactly.

**Interpreter:** regenerate the WAVs with the numpy-enabled interpreter (the same
one `pytest` uses):
`/opt/homebrew/opt/python@3.11/bin/python3.11 scripts/generate_soothe_assets.py`
(`python3` is 3.14 and has no numpy). The test gate is `pytest -q`.

Add these 8 new sounds (key -> display name; ~20-30 s each, gentle, normalised,
faded in/out so they loop cleanly, mono 16 kHz 16-bit):

1. `pink_noise` -> "pink noise" — softer 1/f-shaped noise (e.g. sum a few
   octave-band low-passed noises, or low-pass white noise more than `white_noise`).
2. `rain` -> "rain" — steady low-passed noise bed + sparse short high-frequency
   droplet transients sprinkled randomly.
3. `ocean_waves` -> "ocean waves" — low-passed noise with a slow (~0.07 Hz)
   amplitude swell repeated as waves (like `_uterine_whoosh` but slower, recurring).
4. `forest_breeze` -> "forest breeze" — low-passed noise with slow, gentle gusting
   amplitude modulation (wind only; no birdsong).
5. `night_sky` -> "night sky" — soft sustained ambient pad: a few quiet, low,
   consonant detuned sine partials with slow tremolo. Dreamy and gentle (no harsh
   crickets).
6. `music_box_lullaby` -> "music box lullaby" — a simple soft lullaby melody as
   bell/music-box plucks (decaying sine/triangle notes; reuse the `_soothing_music`
   / `_pulse` approach).
7. `shushing` -> "shushing" — rhythmic band/high-passed noise bursts ("shh… shh…")
   about once per second, mimicking a parent's shush.
8. `fan_hum` -> "fan hum" — steady low broadband hum (low-passed noise + a low
   ~120 Hz tone), constant, no modulation.

Keep peaks safe/consistent with the existing assets (`_normalise`). Do NOT change
the 4 existing sounds.

---

### S1 — synthesize the 8 sounds + regenerate assets
In `scripts/generate_soothe_assets.py`: add a `_<key>(seconds)` function for each
of the 8 sounds and a `_write_wav(ASSET_DIR / "<key>.wav", _<key>(seconds=...))`
line in `main()`. Then **run the generator** with the numpy interpreter above so all
12 `assets/soothe/*.wav` exist. Keep/extend `tests/test_assets.py` so it still
passes (all `assets/soothe/*.wav` are mono / 16 kHz / 16-bit / non-empty); you may
add an assertion that the 8 new keys are present. Acceptance: `pytest -q` green and
the 8 new WAV files exist on disk.

### S2 — register the 8 as config presets
Add a `[soothe.presets.<key>]` block for each of the 8 in **both**
`config/default.toml` and `config/pi-product.toml`, mirroring the existing blocks
exactly (`name` = display name, `sound_path = "../assets/soothe/<key>.wav"`,
`wait_seconds = 1800.0`, `play_seconds = 1800.0`). Update any test that enumerates
the preset set (e.g. `tests/test_config.py` asserts
`sorted(config.soothe.presets) == [...]`) to the full 12, and assert every preset's
`sound_path` exists. Do not change the default `soothe.preset` (`white_noise`).
Acceptance: `pytest -q` green; `load_config` exposes all 12 presets with existing
sound files.

## Per-unit checklist
1. Only this unit's scope. Stdlib + numpy only; no NEW dependency.
2. `pytest -q` passes for the whole suite.
3. 16 kHz / mono / 16-bit / faded / normalised; don't alter the 4 existing sounds.
4. Never edit the stale `src/lullaby/`.
5. Output one line of what changed.
