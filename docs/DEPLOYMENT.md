# Beddington Pi Deployment

This is the Raspberry Pi 5 setup for a local nursery monitor. It runs on your
LAN, keeps data on the Pi, and uses a tokened phone dashboard. There are three
main processes:

| Process | What it does | Notes |
|---|---|---|
| Live-view dashboard | Camera, sensor readings, alerts, and history on port 8088 | LAN only. Do not port-forward it. |
| Voice assistant | Answers local spoken questions from the latest readings | Owns the mic while running. |
| Cry monitor | Runs the cry detection pipeline and writes night outputs | Cannot share the mic with the assistant. |

The assistant and cry-detection `listen` path cannot use the same USB mic at the
same time. Stop one before starting the other.

## Hardware

| Hardware | Required? | Config section | Notes |
|---|---:|---|---|
| Raspberry Pi 5 | Yes | - | Use a stable power supply and a ventilated case. |
| USB mic | Yes | - | Needed for voice assistant and cry detection. |
| CSI cameras | Optional | live-view flags | Prod flags use 640x480, 12 fps, night camera 1, rotate 90. |
| BME688 air sensor | Optional | `[sensors.air]` | I2C address `0x76`. |
| HC-SR501 PIR | Optional | `[sensors.motion]` | GPIO 4. Context only. |
| Seeed MR60BHA2 radar | Optional | `[sensors.radar]` | ESPHome API host on port 6053. |
| Speaker | Optional | `[soothe]` and `[narrator]` | Used for Soothe and spoken replies. |

## Fresh Install

Start on the Pi as the normal user, expected here as `lab`.

```bash
cd ~
git clone <your-repo-url> Beddington
cd ~/Beddington

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install ".[dev]"

python -m beddington --config config/pi-product.toml download-model
```

The YAMNet TFLite cry model is cached under
`~/.cache/beddington/models/`. Fetch it while the Pi has internet.

If you want the local narrator, install Ollama and pull the small model:

```bash
bash scripts/setup_models.sh
```

That pulls `llama3.2:1b` through Ollama. The app still works with the narrator
disabled.

## Configuration

Start from `config/pi-product.toml`.

Touch only the sections that match your hardware and comfort thresholds:

| Section | Why you would edit it |
|---|---|
| `[detection]` | Cry score threshold and sustained/release timing. |
| `[sensors.air]` | Enable the BME688 and confirm I2C address `0x76`. |
| `[sensors.motion]` | Enable the PIR and confirm GPIO 4. |
| `[sensors.radar]` | Enable radar and set `host` plus port 6053. |
| `[soothe]` | Choose whether local sound playback is enabled. |
| `[liveview.state]` | Tune deterministic live-view state thresholds. |

Keep port 8088 on the LAN. Never port-forward it. The dashboard URL contains a
token, but the LAN is still the trust boundary.

## systemd User Services

The repo ships user services in `deploy/`. They assume:

- repo: `/home/lab/Beddington`
- venv: `/home/lab/Beddington/.venv`
- config: `/home/lab/Beddington/config/pi-product.toml`
- logs: `~/liveview.log` and `~/beddington-assistant.log`

Install:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/beddington-liveview.service ~/.config/systemd/user/beddington-liveview.service
cp deploy/beddington-assistant.service ~/.config/systemd/user/beddington-assistant.service

sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now beddington-liveview
systemctl --user enable --now beddington-assistant
```

The live-view unit has `ExecStartPre=/bin/sleep 25`. That delay gives the CSI
cameras, I2C bus, and Wi-Fi time to settle at cold boot. Without it, the camera
or air sensor can start half-ready and need a manual restart.

Manage them:

```bash
systemctl --user status beddington-liveview
systemctl --user restart beddington-liveview
systemctl --user stop beddington-liveview

systemctl --user status beddington-assistant
systemctl --user restart beddington-assistant
systemctl --user stop beddington-assistant
```

Stop `beddington-liveview` to free the camera. Stop `beddington-assistant` to
free the mic for cry detection.

## Phone URL and Token

The live-view token is generated once and stored at:

```text
~/.config/beddington/liveview.token
```

Find the phone URL in the first few lines of the live-view log:

```bash
head -3 ~/liveview.log
```

That log includes the tokened URL. Treat `~/liveview.log` as sensitive. Do not
paste it into chat or send it outside your home.

To rotate the token:

```bash
systemctl --user stop beddington-liveview
rm ~/.config/beddington/liveview.token
systemctl --user start beddington-liveview
head -3 ~/liveview.log
```

## Verify the Install

Run the read-only doctor first:

```bash
scripts/pi_doctor.sh --config config/pi-product.toml --port 8088
```

Then run the smoke test:

```bash
scripts/pi_smoke_test.sh --config config/pi-product.toml --port 8088
```

Results are one line each:

| Status | Meaning |
|---|---|
| `OK` | The check passed. |
| `SKIP` | The hardware, config section, or tool is not present. This can be normal. |
| `WARN` | Something is not ready, but the script did not prove a hard failure. |
| `FAIL` | A required contract failed, such as auth, JSON shape, or output files. |

The scripts exit 0 for all OK/SKIP, 1 if any WARN, and 2 if any FAIL.

## Upgrades and Rollback

Back up first:

```bash
tar czf ~/Beddington-backup-$(date +%Y%m%d).tgz -C ~ Beddington
```

Upgrade:

```bash
cd ~/Beddington
git pull
. .venv/bin/activate
python -m pip install ".[dev]"
systemctl --user restart beddington-liveview
systemctl --user restart beddington-assistant
scripts/pi_doctor.sh --config config/pi-product.toml --port 8088
```

If you deploy by `rsync` instead of `git pull`, copy the repo into
`~/Beddington`, reinstall the package in the venv, restart both services, and
run the doctor again.

For rollback, stop the services, move the broken directory aside, unpack the
backup, reinstall in the venv if needed, and restart.

## Troubleshooting

| Symptom | Likely cause | What to try |
|---|---|---|
| Camera busy | Live-view owns the camera | `systemctl --user stop beddington-liveview`, then retry the camera command. |
| Mic unavailable | Assistant and cry monitor are competing | Stop `beddington-assistant` before running cry detection. |
| Camera fails after cold boot | CSI/I2C was not settled | Keep the `ExecStartPre=/bin/sleep 25` delay, then restart live-view. |
| Phone gets 401 | Token mismatch or token rotated | Reopen the URL from `head -3 ~/liveview.log`. |
| Radar unreachable | Wrong host or ESPHome port blocked | Check `[sensors.radar].host` and port 6053. |
| Air sensor missing | BME688 not visible at `0x76` | Check wiring, I2C enablement, and `i2cdetect -y 1`. |
| Ollama narrator missing | Model/server not running | Run `bash scripts/setup_models.sh`, then check port 11434. |

## Privacy

Beddington is offline by design. The dashboard is LAN-only. It does not record
audio or stream audio. Do not expose port 8088 to the internet.

Local data on disk includes:

| Path | What it contains |
|---|---|
| `~/.local/share/beddington/sensors.db` | SQLite sensor history, derived events, and soothe outcomes. |
| `~/liveview.log` | Live-view logs and the tokened phone URL. Treat as sensitive. |
| `~/beddington-assistant.log` | Assistant service logs. |
| `output/.../events.json` | Offline analyze event output when you run `analyze`. |
| `output/.../night-log.txt` | Human-readable offline night log. |
| `output/.../morning-digest.txt` | Offline morning digest. |

It is an assistive notebook for tired parents, not a medical device.
