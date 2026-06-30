# Real product test on the Raspberry Pi (mic + speaker)

Mimic the finished Beddington: the **mic** hears a cry → the **speaker** plays a
soothe sound → Beddington listens back to confirm it settled → it **remembers**
which sound worked → the morning recap is **narrated by the local llama**.

Everything runs on-device. Nothing leaves the Pi.

---

## 0. One-time setup (on the Pi)

```bash
cd ~/Beddington                 # your repo checkout
git pull                        # get the on-by-default llama config + this profile

# Python package + mic/voice extras
python3 -m pip install -e ".[mic,ears]"

# Local AI model — pulls llama3.2:1b (~1.3 GB) once. The model is NOT in git.
bash scripts/setup_models.sh

# Check audio works (speaker + mic)
aplay  sample_data/crying_baby_cc0.wav   # you should HEAR the sample cry
arecord -d 3 /tmp/mic_test.wav && aplay /tmp/mic_test.wav   # record 3s, play back
```

If `aplay`/`arecord` aren't found: `sudo apt install alsa-utils`.

---

## 1. Start the monitor (Terminal A)

```bash
beddington --config config/pi-product.toml listen --seconds 180
```

This is the real product loop: mic → cry detection (YAMNet) → soothe playback →
quiet-check → outcome saved to `~/.local/share/beddington/sensors.db`.

## 2. Trigger a "crying baby" (Terminal B)

Play the sample cry out loud near the mic so Beddington hears it for real:

```bash
aplay sample_data/crying_baby_cc0.wav
```

(Or play it from your phone next to the cot mic — that's the most realistic.)

**What you should see/hear in Terminal A:**
1. cry detected (sustained)
2. the speaker plays the soothe preset (white noise by default)
3. a quiet-check listens back; when the room is quiet it logs **settled**
4. one outcome row is written to memory

## 3. Let it learn (repeat ≥ 3 times)

`min_samples = 3` in this profile, so after ~3 soothe episodes Beddington has
enough data to **prefer the sound that actually worked**. Re-run step 2 a few
times (you can play different cries / let different presets win).

Peek at what it remembered (read-only):

```bash
sqlite3 ~/.local/share/beddington/sensors.db \
  "select datetime(ts,'unixepoch','localtime') t, sound_name, success from soothe_outcomes order by ts desc limit 10;"
```

## 4. Morning recap — narrated by the local llama

```bash
beddington --config config/pi-product.toml digest
```

You should get a plain-English recap **re-voiced by llama3.2:1b**, including the
new trend lines, e.g. *"When white noise played, Rayan quieted 4/5 times (best
guess)."* Confirm the model actually ran:

```bash
ollama ps        # shows llama3.2:1b loaded while the recap is generated
```

If Ollama or the model is missing, the recap silently falls back to the plain
deterministic digest — nothing breaks.

## 5. (Optional) Talk to it — the fuzzy-question translator

```bash
beddington --config config/pi-product.toml listen-assistant
```

Say: **"Hi Beddington, should I crack a window?"** — the keyword brain misses it,
the llama maps it to the *air-quality* intent, and you get a real sensor answer
(the number always comes from the deterministic brain, never the LLM).

To hear answers spoken aloud, set up Piper and flip `voice_enabled = true` in
`config/pi-product.toml` (`piper_binary` / `piper_model` paths must exist).

---

## What "smart" is doing here

| Feature | What you'll observe | Uses AI? |
|---|---|---|
| Soothe memory | after step 3, it auto-picks the sound that helped Rayan quiet | no — just counts |
| Night trends | step 4 recap shows "Rayan usually stirs ~Xam" / "what helped Rayan quiet" (best guess) | no |
| Llama translator | step 5 understands "crack a window?" | yes — llama3.2:1b |
| Narrated recap | step 4 reads like sentences, not stats | yes — llama3.2:1b |

Safety unchanged: deterministic cry detection, no medical claims, every
inference tagged "(best guess)", raw audio/video never leave the Pi.
