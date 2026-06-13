# Hardware review checklist

Work through the dimensions relevant to the design under review. You don't have to touch every row — pick what applies and say which ones you checked (Rule #4). For each finding, decide PASS or FAIL and attach evidence (a calculation, a datasheet reference, a measured value, or a test you can describe). Never invent a part number, pin, or rating to fill a gap — unknowns become mentor questions (Rule #1). Physical-safety doubts default to Do-not-build (Rule #2).

## Table of contents
1. Electrical limits
2. Connector & pinout compatibility
3. Power budget
4. Mechanical fit & tolerances
5. Thermal
6. Structural / load
7. 3D-print feasibility
8. Reality check — does the claimed part behave as claimed?
9. Lab Witness kit-on-hand reality

---

## 1. Electrical limits
- Voltage: is every part fed within its rated range? (Pi 5 GPIO is 3.3 V logic — 5 V on a GPIO pin damages it.)
- Current: does any pin/rail exceed its source limit? Pi 5 GPIO sources only a few mA per pin; anything beyond a LED needs external power/driver.
- Resistor/level-shifting present where needed (LED current-limit, I2C pull-ups, 5 V↔3.3 V).
- Reverse polarity, shorts, floating inputs.

## 2. Connector & pinout compatibility
- Do the connectors physically mate, and is the pinout correct end to end? A swapped SDA/SCL or a mirrored ribbon is a silent failure.
- Voltage/logic level matches across the connector.
- **Pi 5 camera:** Camera Module 3 ships a 15-pin wide cable that does NOT fit the Pi 5's 22-pin narrow socket — needs a 22-to-15-pin Pi-5 adapter cable. Known gotcha; check it.

## 3. Power budget
- Sum the worst-case current draw (Pi 5 + cooler + 2 cameras + OLEDs + speaker + anything driven) against the 27 W USB-C PSU.
- Inrush/peaks, not just steady state. Brown-outs corrupt the microSD.
- If anything pulls power through the Pi rather than its own supply, check the rail can take it.

## 4. Mechanical fit & tolerances
- Do parts actually fit together and into the mount? Clearances for connectors, cables, airflow.
- Fastener sizes, hole alignment, cable strain relief.

## 5. Thermal
- Pi 5 throttles under sustained CPU load; the Active Cooler is on hand — is it fitted and is there airflow?
- Any part dissipating real power: heatsinking, spacing, enclosure venting.

## 6. Structural / load
- Top-down camera mount: stable, won't sag or vibrate, holds the camera square over the bench.
- Anything that bears weight or moves: will it hold for the demo run?

## 7. 3D-print feasibility
- Overhangs needing support, bridging, wall thickness, layer-adhesion under load, material choice (PLA vs PETG for heat).
- Print time vs the v0 freeze — a 14-hour print on 18 Jun is a schedule risk, flag it.

## 8. Reality check — does the claimed part behave as claimed?
- Is the named part real, and does it have the claimed pinout/rating/interface? If unsure, flag it; do not reconstruct a datasheet from memory (Rule #1).
- Performance/spec numbers that aren't measured or calculated are suspect — mark unverified.

## 9. Lab Witness kit-on-hand reality
On hand: Raspberry Pi 5 (4 GB), **AI HAT+ 26 TOPS (Hailo-8) — fitted, used for v0 vision**, official 27 W USB-C PSU, Active Cooler, 2× Camera Module 3, jumper wires, 2–3 breadboards, 3× 0.91" I2C OLED, mini speaker (BS-16), full solder/bench kit.
Known gaps / blockers (resolve first): **Pi-5 camera adapter cable** (Module 3 cable doesn't fit Pi 5), **micro-HDMI** adapter (Pi 5 has micro-HDMI; or go headless), **top-down mount + light** not yet sourced. microSD is sorted (SanDisk 32 GB); AI HAT+ 26 TOPS (Hailo-8) is on hand and fitted.
Parked (not v0): SG90 micro servo, PCA9685 driver, USB mic, 6-pin sensor breakout (model unconfirmed — mentor question).
- If a design assumes a part Mo doesn't have, say so and make it a blocker + mentor question, don't assume it'll appear.
- Any servo/actuator/PCA9685 use is a safety + scope flag for v0 (parked) — route to mentors.
