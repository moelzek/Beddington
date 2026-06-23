# Lullaby hardware guide

> Practical wiring notes for Mo's current inventory. Live project state and tier
> gates are still in [memory.md](memory.md).

Use this as a bench guide, not as cot-deployment approval. Keep the Pi, Hailo,
amplifiers, power boards, and any warm electronics in a vented base. Anything
that moves, heats, has cables, or has small parts stays away from the sleep
surface. The nursery camera physical gate lives in
[camera-mount-plan.md](camera-mount-plan.md).

## Bench-test order

- [x] Preview the generated soothe WAV files on the laptop at low volume.
- [x] Short looped white-noise playback on the laptop.
- [x] Test Pi audio with a Bluetooth speaker first.
- [ ] Bench-test one MAX98357 amplifier with one 3W 4Ω speaker. Deferred by Mo on 2026-06-23.
- [x] Test USB microphone capture through ALSA and Lullaby's microphone adapter.
- [x] Run a live cry-detection smoke test with the USB microphone.
- [x] Test attached Camera Module 3 detection and local no-preview still capture.
- [x] Document the cot-safe camera mount and cable-routing plan.
- [ ] Choose and mock up the actual nursery camera location before any nursery video use.
- [ ] Test one OLED display as a simple status screen.
- [ ] Test one VL53L0X distance sensor for mount/enclosure experiments.
- [ ] Test one SG90 or Miuzei 9g servo through the PCA9685 with separate 5V power.
- [ ] Use MG996R only if the joint genuinely needs the torque and the external supply is proven.
- [ ] Leave INMP441 I²S microphones until the simpler audio loop works.
- [ ] Use HC-SR04 only after adding a voltage divider on ECHO.

## Servos and PCA9685

Mo has three servo types:

| Part | Quantity | Best use |
|---|---:|---|
| MG996R metal-gear servo | 4 | Larger joints that genuinely need torque |
| Miuzei 9g micro servo | 10 | Fingers, sensors, light arms |
| SG90 9g micro servo | 10 | Fingers, sensors, light arms |
| PCA9685 16-channel servo driver | 3 | Drives servos from one Pi I²C connection |

Start with the SG90 or Miuzei 9g servos. They are lighter, draw less current,
and are the easiest first movement test. Reach for the MG996R only when the
mechanism really needs the torque. Treat the MG996R as high-current: the
reference notes say it can pull about 2.5A when stalled.

Drive servos through the PCA9685, not directly from Pi GPIO. The PCA9685 gives
clean PWM timing and lets the servo power stay separate from the Pi.

### Wiring

| PCA9685 / servo side | Connects to |
|---|---|
| PCA9685 VCC | Pi 3.3V |
| PCA9685 GND | Pi GND |
| PCA9685 SDA | Pi SDA, GPIO 2 |
| PCA9685 SCL | Pi SCL, GPIO 3 |
| PCA9685 screw terminal V+ | External 5-6V servo supply |
| PCA9685 screw terminal GND | External supply GND |
| Servo brown wire | PCA9685 GND |
| Servo red wire | PCA9685 V+ |
| Servo orange wire | PCA9685 signal |

Tie all grounds together: Pi GND, PCA9685 GND, and external supply GND.

Do not power more than one or two tiny servos from the Pi, and do not power the
MG996R from the Pi. Use the external 5-6V supply on the PCA9685 screw terminal.

### Install and smoke test

```bash
pip install adafruit-circuitpython-servokit
```

```python
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)
kit.servo[0].angle = 0
kit.servo[0].angle = 90
kit.servo[0].angle = 180
```

Move slowly, with one small servo first. If the servo jitters, browns out the
Pi, or the supply gets hot, stop and check power and common ground before
continuing.

References: [MG996R datasheet](https://components101.com/motors/mg996r-servo-motor-datasheet),
[SG90 datasheet](https://components101.com/motors/servo-motor-basics-pinout-datasheet),
[Adafruit PCA9685 guide](https://learn.adafruit.com/16-channel-pwm-servo-driver).

## Servo power with USB-C PD trigger boards

Servos need their own 5-6V supply. Do not take servo power from the Pi.

Mo's USB-C PD trigger boards can ask a USB-C PD charger or power bank for a
chosen output voltage. For the first servo bench tests, set the board to 5V and
wire its output to the PCA9685 V+ and GND screw terminals.

Before connecting servos:

- [ ] Set the trigger board output voltage with its solder pad or jumper.
- [ ] Confirm the output is about 5V with a multimeter.
- [ ] Connect trigger-board GND to PCA9685 GND and Pi GND.
- [ ] Start with one SG90 or Miuzei 9g servo.

Reference: [USB-C PD trigger board explanation](https://www.tindie.com/products/lcsc/usb-c-pd-trigger-board/).

## Audio out

The Pi 5 has no headphone jack. Start with the easiest path, then move to wired
audio once the loop works.

### Option A: Bluetooth speaker first

Pair a Bluetooth speaker from Raspberry Pi OS, select it as the output device,
then run Lullaby's own short preview command:

```bash
lullaby --config config/default.toml preview-soothe --seconds 5
```

Expected: the selected `white_noise` preset plays through the Bluetooth speaker
at low volume, then stops.

If Lullaby reports `no_supported_player`, install FFmpeg or play a local file
directly with a PipeWire-aware player:

```bash
ffplay -nodisp -autoexit assets/soothe/white_noise.wav
```

or:

```bash
mpv assets/soothe/white_noise.wav
```

Plain `aplay` usually reaches HDMI or wired ALSA devices, not Bluetooth.

### Option B: MAX98357 plus 3W 4Ω speaker

Mo has two MAX98357 I²S amplifiers and four 3W 4Ω speakers. This is the wired
step-up after Bluetooth: the Pi sends digital I²S audio to the amplifier, and
the amplifier drives the speaker.

| MAX98357 pin | Connects to |
|---|---|
| LRC | GPIO 19 |
| BCLK | GPIO 18 |
| DIN | GPIO 21 |
| VIN | 5V |
| GND | GND |
| Speaker + / - | Speaker screw terminals |

Enable the overlay by adding this to `/boot/firmware/config.txt`:

```text
dtparam=i2s=on
dtoverlay=max98357a
```

Reboot. The MAX98357 should appear as an audio output device, then a wired
playback smoke test can use:

```bash
aplay assets/soothe/white_noise.wav
```

Keep the first run short and low volume.

Reference: [Adafruit MAX98357 guide](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp).

## Microphone input

Use the simplest microphone path first:

- USB microphone or USB sound card: plug-and-play path for the current Lullaby code.
- Bluetooth headset: useful for quick experiments if pairing is reliable.
- INMP441 I²S MEMS microphone: advanced path for later.

Mo has four INMP441 microphones. They are a good future part, but I²S audio
input on Pi 5 needs extra device-tree setup and is fiddlier than USB audio.
Leave them until the core cry-detection and speaker-output loop works. They
may also be a natural fit for an ESP32 / Seeed XIAO Sense style satellite later.

Reference: [INMP441 datasheet](https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf).

## Camera

One Camera Module 3 is attached to the Pi and was detected by `rpicam-hello` as
`imx708`, with modes up to 4608×2592. A no-preview still-capture smoke test
also passed locally on the Pi. Use Lullaby's smoke command for repeat checks so
the raw test frame is deleted by default:

```bash
lullaby camera-smoke --output output/pi-camera-smoke
```

Expected: `output/pi-camera-smoke/camera-smoke.json` contains derived metadata
such as dimensions, byte count, camera summary, and capture metadata keys. The
raw test frame is deleted unless `--keep-frame` is passed deliberately.

For the bench-only two-frame change check:

```bash
lullaby camera-change --output output/pi-camera-change
```

Expected: Lullaby captures two short local BMP frames, writes
`output/pi-camera-change/visual-change.json`, and deletes the raw BMP frames by
default. The result is only a visual-change metric; it is not a safety, sleep,
breathing, or face-covering assessment.

The underlying Raspberry Pi commands are:

```bash
rpicam-hello --list-cameras
rpicam-still -n --immediate --timeout 1s --width 640 --height 480 \
  --output /tmp/lullaby-camera-smoke.jpg \
  --metadata /tmp/lullaby-camera-smoke.json \
  --metadata-format json
```

Expected: the list command shows an `imx708` camera, and the still command
writes a local JPEG. Delete test images after checking them. Do not copy raw
frames off-device or commit them.

Camera Module 3 is useful for daylight bench tests. Dark-room video would need
a separate Tier 2 hardware decision, likely NoIR plus safe IR illumination and
a physical mock-up that satisfies [camera-mount-plan.md](camera-mount-plan.md).

## Distance sensors

Mo has two distance-sensor families. Prefer VL53L0X on the Pi because it is
I²C, works at 3.3V, and needs no extra voltage-divider parts.

### VL53L0X time-of-flight sensor

Mo has five VL53L0X sensors. Use them for bench proximity, mount checks, and
enclosure experiments. Do not treat distance readings as baby-state inference.

| VL53L0X pin | Connects to |
|---|---|
| VIN | Pi 3.3V |
| GND | Pi GND |
| SDA | Pi SDA, GPIO 2 |
| SCL | Pi SCL, GPIO 3 |

```bash
pip install adafruit-circuitpython-vl53l0x
```

```python
import board
import adafruit_vl53l0x

i2c = board.I2C()
sensor = adafruit_vl53l0x.VL53L0X(i2c)
print(sensor.range, "mm")
```

Reference: [Adafruit VL53L0X guide](https://learn.adafruit.com/adafruit-vl53l0x-micro-lidar-distance-sensor-breakout).

### HC-SR04 ultrasonic sensor

Mo has five HC-SR04 sensors. They can be useful for rough bench distance
checks, but the ECHO pin outputs 5V, which can damage a Pi GPIO pin. Use a
voltage divider on ECHO, for example 1kΩ and 2kΩ resistors. Those resistors are
not listed in the kit, so the VL53L0X is lower-friction.

With a divider in place:

```python
from gpiozero import DistanceSensor

sensor = DistanceSensor(echo=24, trigger=23)
print(sensor.distance * 100, "cm")
```

Reference: [HC-SR04 datasheet](https://cdn.sparkfun.com/datasheets/Sensors/Proximity/HCSR04.pdf).

## OLED displays

Mo has four 0.96-inch OLED displays and two 0.91-inch OLED displays. They are
tiny I²C screens, useful later for status, sensor values, or short transcribed
text. The common modules are SSD1306/SSD1315-compatible.

| OLED pin | Connects to |
|---|---|
| VCC | Pi 3.3V |
| GND | Pi GND |
| SDA | Pi SDA, GPIO 2 |
| SCL | Pi SCL, GPIO 3 |

Common I²C address: `0x3C`.

```bash
pip install luma.oled
```

```python
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas

device = ssd1306(i2c(port=1, address=0x3C))
with canvas(device) as draw:
    draw.text((0, 0), "Hello hackathon", fill="white")
```

Reference: [Adafruit monochrome OLED guide](https://learn.adafruit.com/monochrome-oled-breakouts).
