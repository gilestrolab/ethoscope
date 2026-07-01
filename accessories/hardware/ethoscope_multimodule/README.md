# Ethoscope Multi-Module Actuator Controller

## Overview

This is the Arduino firmware for the Ethoscope multi-module actuator board. A single
sketch (`ethoscope_multimodule.ino`) drives motors, solenoid valves, and LEDs through
Darlington arrays over a serial connection. The same code compiles into five distinct
module personalities selected at build time, covering sleep-deprivation, odour-arousal,
and optogenetic stimulation use cases.

The firmware is non-blocking (all timing uses `millis()`), self-describing (it can emit
its own capabilities as JSON), and requires no external Arduino libraries.

## Module Types

The active personality is chosen by the `MODULE` define. Each module exposes only the
channels and commands relevant to its hardware:

| MODULE | Name   | Motors | Valves | LEDs | Description                                        |
|:------:|--------|:------:|:------:|:----:|----------------------------------------------------|
| 0      | SD     | 10     | 0      | 0    | N20 Sleep Deprivation — up to twenty N20 geared motors |
| 1      | AGOSD  | 10     | 10     | 0    | Sleep Deprivation + Odour Arousal — motors and valves |
| 2      | AGO    | 0      | 10     | 0    | Odour Arousal — ten solenoid valves                |
| 3      | mAGOLED| 10     | 0      | 10   | Motor + Optogenetic LED — motors on odd, LEDs on even channels |
| 4      | LED    | 0      | 0      | 20   | Optogenetic LEDs — twenty LEDs (CsChrimson, 620–630 nm) |

There are always 20 physical channels (pins 0–19). Motors sit on odd channels, valves
and LEDs on even channels, depending on the module.

## Hardware Requirements

- Arduino Micro (ATmega32U4).
- Ethoscope multi-module PCB (v1.0, v1.1, or v1.2/1.3).
- Darlington arrays (e.g. ULN2803) for the output channels.
- Power supply sized for the actuators in use:
  - Motors: 6–12 V DC, up to 10 × 500 mA = 5 A.
  - Solenoid valves: as per valve specification.
  - LEDs: driven through current-limiting resistors, up to 20 × 20 mA = 400 mA.
- Common ground between the Arduino and the actuator power rail.

## Software Requirements

- Arduino IDE (or `arduino-cli`) with the Arduino Micro board support installed.
- No external libraries — the serial command parser is built in.

## Configuration

Hardware selection is kept in a local, gitignored header so your board setup is not
tracked. Copy the example and edit it before compiling:

```sh
cp versions.h.example versions.h
```

Then set the two values in `versions.h` to match your board:

```cpp
#define PCBVERSION 10    // 10 = v1.0, 11 = v1.1, 12/13 = v1.2/1.3
#define MODULE 0         // 0=SD, 1=AGOSD, 2=AGO, 3=mAGOLED, 4=LED
```

Flash the sketch:

- Connect the Arduino Micro.
- Select the correct board and port in the Arduino IDE.
- Compile and upload `ethoscope_multimodule.ino`.

## Serial Interface

- **Baud rate**: 115200 (fixed).
- **Format**: ASCII commands terminated by newline or carriage return.

Only the commands relevant to the compiled module are active.

| Command | Format                       | Description                              | Modules |
|:-------:|------------------------------|------------------------------------------|---------|
| `P`     | `P [0-19] [ms]`              | Pulse a single channel for N ms          | all     |
| `A`     | `A [s]`                      | Activate all motors for N seconds        | motors  |
| `W`     | `W [ch] [on_ms] [off_ms] [n]`| Pulse train on one channel (n cycles)    | LEDs    |
| `B`     | `B [s]`                      | Activate all LEDs for N seconds          | LEDs    |
| `X`     | `X [on_ms] [off_ms] [n]`     | Pulse train on all LEDs (n cycles)       | LEDs    |
| `D`     | `D`                          | Run a demo sequence over all channels    | all     |
| `T`     | `T`                          | Emit module capabilities as JSON         | all     |
| `H`     | `H`                          | Show the help/command menu               | all     |

### Examples

```text
P 5 1000        # Channel 5 on for 1000 ms
A 5             # All motors on for 5 s
W 4 100 900 30  # Channel 4: 30 pulses of 100 ms on / 900 ms off
B 3             # All LEDs on for 3 s
X 100 900 10    # All LEDs: 10 pulses of 100 ms on / 900 ms off
```

Pulse trains (`W`/`X`) are useful for optogenetic protocols where continuous
illumination would cause depolarization block.

### Capability discovery (`T`)

The `T` command returns a JSON description of the firmware version, module type,
channel counts, and available commands. This lets a host (e.g. the node) learn a
module's abilities dynamically rather than hard-coding them. Example:

```json
{"version":"FW-1.50;HW-10","module":{"name":"N20 Sleep Deprivation Module","type":0},
 "capabilities":{"motors":10,"valves":0,"leds":0,"total_channels":20,"num_actuators":10}}
```

## Testing

`test_multimodule.py` is a standalone smoke test. It connects to the board, queries
capabilities with `T`, and exercises every command supported by the reported module,
returning exit code 0 on success and 1 on failure.

```sh
pip install pyserial
python test_multimodule.py [port]     # default port: /dev/ttyACM0
```

## Safety

- All activations are non-blocking and time-limited.
- Channel numbers and durations are validated; invalid input returns an `ERROR` line.
- `A` / `A`-off staggers motor switching (`ACTIVATION_DELAY`) to avoid current inrush.
- An `emergencyShutdown()` routine disables every output at once. A commented current-
  monitoring block (e.g. ACS712) is included as a starting point for overload protection.

## Troubleshooting

**Channels not activating**
1. Verify power supply connections and ratings.
2. Confirm `PCBVERSION` and `MODULE` are set correctly in `versions.h`.
3. Check Darlington array orientation and wiring.
4. Confirm the serial port is at 115200 baud.

**Random or unintended activations**
1. Inspect for ground loops or electrical noise.
2. Check serial cable integrity and shielding.
3. Ensure adequate current limiting and protection.

## License

MIT License. Author: Giorgio Gilestro &lt;giorgio@gilest.ro&gt;
