# ARCHIVED — Lab Witness Hardware Inventory

> Lab Witness is retired. This file is preserved for historical reference only and is not active Lullaby hardware guidance. Lullaby hardware must follow the cot-adjacent safety boundary in [memory.md](memory.md): hot compute in a vented base beside the cot, not in the cot.

# Lab Witness — Hardware Inventory (what Mo has)

Catalogued from photos taken 13 Jun 2026. **The photos were renamed 13 Jun 2026** from camera defaults (IMG_7802–7822) to descriptive snake_case names — see the old→new mapping at the foot of this file. Photo files live in `~/Code/Labie/hardware-photos/` — the `hardware-photos/` subfolder of the working folder. Beginner-friendly. Three buckets: **Use now**, **Check or buy**, **Park for later**. Plus a short "ask your mentors" list.

---

## ✅ USE NOW — core kit you already have (this is most of what you need)

| Item | Plain-English: what it is | Role in Lab Witness |
|---|---|---|
| **Raspberry Pi 5 (4GB)** (`raspberry_pi_5_4gb_box`) | The tiny computer — the "brain". 4GB of memory. | The brain. Runs everything. 4GB is enough for v0. |
| **AI HAT+ 26 TOPS (Hailo-8)** *(acquired after the 13 Jun photo catalogue)* | Add-on board with a Hailo-8 AI chip (26 TOPS) that runs the object-recognition maths fast. Stacks on top of the Pi 5. | **Runs v0 vision.** Hailo-accelerated object detection (e.g. YOLO via `picamera2`), freeing the CPU for the state machine + timing logic. |
| **27W USB-C Power Supply, UK plug** (`raspberry_pi_27w_power_supply_box`) | The official Pi 5 charger. | Powers the Pi. Correct one — don't substitute a phone charger. |
| **Active Cooler for Pi 5** (`raspberry_pi_active_cooler`) | A small heatsink + fan that clips on top of the Pi. | Stops the Pi overheating/slowing. Fit it before anything else. |
| **2× Camera Module 3** (`raspberry_pi_camera_module_3_boxes`) | Two official Pi cameras (autofocus). | The "eyes" over the bench. Two means a spare — huge for a sprint. |
| **Jumper wires, rainbow ribbon** (`jumper_wires_1`, `jumper_wires_2`) | Cables that push onto pins to connect things without soldering. | Wire up the screen / buzzer to the Pi. Essential. |
| **2–3 Breadboards** (`breadboard_1`, `breadboard_2`) | White plastic boards with holes — a solder-free "patch panel" to build small circuits. | Where the indicator (screen/LED/buzzer) gets wired up. |
| **3× 0.91" OLED displays** (`oled_display_1`, `oled_display_2`, `oled_display_3`) | Tiny black-and-white screens (~1cm tall). Labelled GND/VCC/SCL/SDA = a simple "I2C" screen (4 wires). | **This is your live deviation flag.** It can show "STEP 3 ✓" or "⚠ INCUBATION OVER TIME" right on the bench. |
| **Mini speaker, BS-16** (`speaker`) | A small loudspeaker with two wires. | *Optional* audio alert. See flag below — a speaker is fiddlier than a buzzer. |
| **Full electronics bench** (`workbench_parts_tray`, `workbench_tools_overview`) | Soldering iron, hot-air station, 2× multimeter, hook-up wire spools, crocodile clips, stripboard, components. | Your workshop. You're far better equipped than most teams. |

---

## ⚠️ CHECK OR BUY — likely blockers, sort these first

These are small/cheap but each can stop you dead. Resolve today.

1. ~~microSD card~~ ✅ **SORTED — SanDisk 32GB acquired (13 Jun).**
   - *What it is:* the Pi's hard drive — the operating system lives on it.
   - 32GB is plenty for v0. Next step is to "flash" it with Raspberry Pi OS (64-bit) using the Raspberry Pi Imager — that's part of the first setup prompt.

2. **Pi 5 camera cable — almost certainly needed.**
   - *The gotcha:* the Camera Module 3 comes with a *wide* ribbon cable. The **Pi 5's camera socket is a different, narrower type** — the included cable does **not** fit. You need a "Raspberry Pi 5 camera adapter cable" (22-pin to 15-pin).
   - *Action:* check the cable end against the Pi 5's camera socket. If it doesn't fit, buy 1–2 Pi-5 camera cables. **This trips up almost everyone — flag to mentors.**

3. **Screen connection (micro-HDMI).**
   - *The gotcha:* your white HDMI cable (`hdmi_cable`) is full-size both ends. The **Pi 5 has tiny "micro-HDMI" sockets**, so a normal HDMI plug won't fit.
   - *Action:* either get a **micro-HDMI-to-HDMI adapter/cable**, OR skip the monitor entirely and control the Pi from your laptop ("headless" setup). Either works — decide with Flomotion.

4. ~~**AI HAT+ (the Hailo AI accelerator) — you don't appear to have one.**~~ ✅ **SORTED — AI HAT+ 26 TOPS (Hailo-8) acquired and now used for v0 (13 Jun).**
   - *What it is:* an add-on board that speeds up the "recognise objects in the camera" maths.
   - *Decision (13 Jun, Mo's call):* the HAT is in hand and fitted to the Pi 5, so **v0 vision runs on it** (Hailo-accelerated detection) rather than CPU-only. This reverses the earlier "try CPU-first, defer the HAT" plan. Now listed under **Use now** above.

5. **Top-down camera mount + a light.**
   - *Why:* fixing the camera directly overhead at a steady height, with steady lighting, is the single biggest thing that makes the vision reliable.
   - *Action:* any cheap overhead arm/clamp/copy-stand + a small LED light. Improvise from the workshop if needed.

---

## 🅿️ PARK FOR LATER — real kit, but NOT for v0 (don't get distracted)

ADHD guardrail: these are tempting rabbit holes. They belong to v2 or never. Leave them bagged.

| Item | What it is | Why not now |
|---|---|---|
| **Micro servo motor (SG90-type)** (`servo_motor`) | A tiny motor that rotates to a set angle. | v0 doesn't physically move anything. Pure distraction. |
| **PCA9685 16-channel PWM/servo driver** (`pwm_servo_driver_front`, `pwm_servo_driver_back`) | A board for controlling lots of servos at once. | Only useful if you're driving motors — you're not, for v0. |
| **USB mini microphone** (`usb_microphone`) | A small plug-in microphone. | v0 watches; it doesn't listen. Not needed. |
| **Small 6-pin sensor breakout** (`distance_sensor`) | Confirmed a sensor board (Mo). 6 pins + 2 mounting holes — looks like an I2C sensor breakout, plausibly a time-of-flight (ToF) distance sensor (e.g. VL53L0X-type), but exact model unconfirmed. | v0 is camera-only. *Possible v2 use:* a ToF sensor could detect "a hand is over the bench" cheaply — park the idea, don't build it now. Confirm exact model from any text on the board. |

---

## 🙋 ASK YOUR MENTORS (or retake a clearer photo)

Genuine uncertainties where a wrong move wastes time or risks a part:

1. **The 6-pin black sensor breakout (`distance_sensor`)** — confirmed a sensor (Mo). Likely an I2C sensor breakout, possibly a time-of-flight distance sensor. Worth confirming the exact model (any text on the board, or ask a mentor) so we know what it could do — but it's parked for v0 either way.
2. **The blue box tool (`solder_fume_extractor`)** — possibly a UV-cure box or a fume extractor; unclear. The black unit next to it is a solder-fume extractor fan (use it when soldering — those fumes aren't great to breathe).
3. **Does the Camera Module 3 cable physically fit the Pi 5 camera socket?** (See blocker #2.) A 10-second check with a mentor saves a day.
4. **Speaker vs buzzer for the alert (`speaker`):** driving a bare speaker from the Pi usually needs a small amplifier; a simple "active buzzer" is far easier. Ask which is least hassle — or just use the OLED screen as the flag for v0 and skip audio.

---

## Bottom line

You already own the expensive, hard-to-source parts: **Pi 5, two cameras, power, cooling, screens, wiring, and a full bench.** What stands between you and "the camera sees the bench" is small and cheap: **a microSD card, the right Pi-5 camera cable, and a way to view the screen.** Sort those three and you can start building.

---

## Photo filename mapping (renamed 13 Jun 2026)

All 21 photos live in `~/Code/Labie/hardware-photos/` and were renamed from camera defaults to descriptive snake_case names (extension kept `.JPG`).

| Original | New name | What it shows |
|---|---|---|
| IMG_7802 | `raspberry_pi_27w_power_supply_box` | Pi 27W USB-C PSU box (UK plug) |
| IMG_7803 | `raspberry_pi_active_cooler` | Active Cooler for Pi 5 (boxed) |
| IMG_7804 | `raspberry_pi_5_4gb_box` | Raspberry Pi 5 4GB box |
| IMG_7805 | `raspberry_pi_camera_module_3_boxes` | 2× Camera Module 3 boxes |
| IMG_7806 | `breadboard_1` | Solderless breadboard |
| IMG_7807 | `hdmi_cable` | Full-size HDMI cable |
| IMG_7808 | `oled_display_1` | 0.91" OLED (back of board) |
| IMG_7809 | `oled_display_2` | OLED (screen face) |
| IMG_7810 | `usb_microphone` | USB mini microphone |
| IMG_7811 | `breadboard_2` | Solderless breadboard |
| IMG_7812 | `speaker` | Mini speaker (BS-16) |
| IMG_7813 | `servo_motor` | SG90-type micro servo |
| IMG_7814 | `distance_sensor` | 6-pin sensor breakout (likely ToF) |
| IMG_7815 | `oled_display_3` | 0.91" OLED (back of board) |
| IMG_7816 | `jumper_wires_1` | Rainbow ribbon jumper wires |
| IMG_7817 | `pwm_servo_driver_front` | PCA9685 PWM/servo driver (front) |
| IMG_7818 | `pwm_servo_driver_back` | PCA9685 PWM/servo driver (back) |
| IMG_7819 | `jumper_wires_2` | Rainbow ribbon jumper wires |
| IMG_7820 | `workbench_parts_tray` | Bench: wire spools / parts tray |
| IMG_7821 | `workbench_tools_overview` | Bench: multimeters, soldering station |
| IMG_7822 | `solder_fume_extractor` | Fume extractor fan (+ unidentified blue box) |
