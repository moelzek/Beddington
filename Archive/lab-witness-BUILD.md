> Superseded by the Lullaby baby-monitor pivot on 2026-06-18; retained for history.

# BUILD.md — Lab Witness rig build runbook

**Purpose:** the reproducible, step-by-step way to assemble and boot the Lab Witness rig from scratch — so Mo (or the CV/embedded dev taking over from week two) can rebuild it without guesswork. This is the **"how"**. The **"what happened"** lives in [DEVLOG.md](DEVLOG.md); the design **"what & why"** lives in [lab-witness-v0-build-doc.md](lab-witness-v0-build-doc.md); canonical status/dates live in [memory.md](memory.md).

Each step is tagged **[DONE] / [NEXT] / [TODO]**. Keep it current as the build progresses.

---

## 1. Flash the microSD card  [DONE — 13 Jun 2026]

**You need:** a laptop, Raspberry Pi Imager (raspberrypi.com/software), the SanDisk microSD card, and a way to plug it into the laptop (SD-slot + adapter, or a USB card reader).

1. Open Raspberry Pi Imager.
2. **Choose Device** → Raspberry Pi 5.
3. **Choose OS** → Raspberry Pi OS (64-bit).
4. **Choose Storage** → the microSD card (tick "Exclude system drives" so you can't pick the laptop's own drive by mistake).
5. **Edit Settings (customisation):**
   - Hostname: `labwitness`
   - Username: `labwitness` + **a password you write down** ⚠️ (required — see note)
   - Wi-Fi: network name + password (the network the Pi will use)
   - Enable **SSH** (password authentication), under Services / Remote access
   - Raspberry Pi Connect: leave OFF (not needed; SSH covers remote access)
6. **Write** → wait ~10–15 min → Done.

⚠️ **A password is mandatory for headless use.** With no monitor, SSH is the only way in, and SSH needs a username **and** password. If the password wasn't set, either re-flash, or add it on the card's boot partition before first boot.

**Why headless:** the only HDMI cable on hand is full-size, but the Pi 5 uses **micro-HDMI** — so the Pi runs with no monitor and is controlled from the laptop over Wi-Fi via SSH.

## 2. Fit the Active Cooler  [DONE]

⚠️ First confirm the part is the **Active Cooler** (a flat metal heatsink with a small fan and a thin 4-pin lead), not a passive case — the box sticker was ambiguous (labelled "Case", CM5A221).

1. Take the Pi 5 out by its edges; avoid touching the gold pins/contacts.
2. Peel the protective film off the thermal pad(s) on the cooler's underside.
3. Line up the cooler's two **spring push-pins** with the two mounting **holes** on the Pi board.
4. Press each pin until it clicks through (firm but gentle; support the board from underneath).
5. Plug the **4-pin fan lead** into the Pi's **FAN** connector (the small white socket near the 40-pin GPIO header). It only fits one way.

## 2b. Fit the AI HAT+ (26 TOPS / Hailo-8)  [NEXT]

The AI HAT+ stacks on top of the Pi 5 (over the Active Cooler) and runs the v0 vision detector.

1. Power off / unplugged.
2. Fit the supplied **GPIO stacking header** and **spacers/standoffs** so the HAT clears the Active Cooler fan.
3. Seat the HAT on the 40-pin GPIO header; secure with the standoff screws.
4. Connect the supplied **PCIe ribbon (FFC)** between the Pi 5's PCIe port and the HAT — contacts the right way round, latch closed. (The Hailo-8 module is pre-fitted to the HAT.)
5. Drivers/firmware come later (section 6): on the booted Pi, `sudo apt install hailo-all`, reboot, then check with `hailortcli fw-control identify`.

## 3. Insert SD + first boot  [DONE — 13 Jun 2026]

1. Insert the flashed microSD into the Pi.
2. Connect the **27W USB-C PSU**; the Pi powers on (no power button needed).
3. Wait ~1–2 min for first boot.
4. From the laptop terminal: `ssh labwitness@labwitness.local` (or use the Pi's IP). Enter the password. You're in.

> ⚠️ **Reliable first boot = a monitor, not headless.** First-boot with a **monitor via micro-HDMI (the port nearest the USB-C) + a USB keyboard/mouse** — *not* headless. Headless SSH can fail silently (mDNS `.local` not resolving, Connect showing no device, SSH refused/timed out) and cost hours. A **micro-HDMI adapter/cable is required** for the Pi 5 — only full-size HDMI may be on hand. If the Pi doesn't auto-join wifi from the Imager config, connect it **manually via the desktop network icon** (top-right). Note: the **AI HAT+ boots fine and is not the problem** (it's the v0 vision compute — see [memory.md](memory.md)).

## 4. Connect Camera Module 3  [DONE — 13 Jun: camera connected + detected; first image pending lens-film peel]

> **13 Jun:** camera 0 (imx708) detected via `rpicam-hello --list-cameras`; capture with `rpicam-still -n -o test.jpg`. **If the image is BLACK, peel the clear protective film off the lens and ensure there's light** — that's the #1 cause.

⚠️ Needs a **Pi-5 camera adapter cable (22-pin → 15-pin)**. The Camera Module 3 ships only the wider 15-pin cable, which does **not** fit the Pi 5's narrower connector. Verify it's on hand / order if not.

1. Power off the Pi.
2. Seat the adapter cable: narrow (22-pin) end into the Pi's CAM/DISP port; wider (15-pin) end into the camera. Contacts the right way round, latch closed.
3. Power on; test: `rpicam-still -o test.jpg` (or `libcamera-still`). Check the image.

## 5. Mount + lighting  [TODO]

- Fix the camera **top-down**, ~40 cm above the bench, pointing straight down; never move it once set.
- Add controlled lighting (LED / ring light) for consistent detection.
- Mount option: 3D-print a bracket (3D printers on site at the workshop).

## 6. Software / perception  [TODO — CV dev]

- Vision runs on the **AI HAT+ 26 TOPS (Hailo-8)** — Hailo-accelerated object detection (e.g. YOLO via the `picamera2` Hailo examples / `hailo-rpi5-examples`). The state machine, timing check and Notion write stay plain Python on the CPU.
- Software setup on the booted Pi: `sudo apt update && sudo apt full-upgrade`, then `sudo apt install hailo-all`, reboot, verify with `hailortcli fw-control identify`.
- Detector (Hailo) → state machine → timing check → Notion write + on-screen deviation banner.
- See [lab-witness-v0-build-doc.md](lab-witness-v0-build-doc.md) for the design.
- Canonical AI reference: the hackathon's official "London Calling / Edge AI on a Raspberry Pi" quickstart — especially **Part 7** (camera + YOLO object detection on the Pi) and **Part 8** (AI HAT+ for real-time vision), both directly relevant to Lab Witness's perception stage.

---

*Living document — update each step's tag as the build moves. Canonical dates/status: [memory.md](memory.md).*
