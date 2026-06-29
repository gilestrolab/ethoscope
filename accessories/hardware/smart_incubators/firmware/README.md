# Smart Incubator — WiFi Node Firmware (WeMos D1 R2 / ESP8266)

WiFi rewrite of the incubator (client) node, replacing the legacy nRF24L01 + Arduino UNO
design. Each incubator is now a self-contained WiFi device that:

- regulates **temperature** with a Peltier (TEC) element driven through a **Cytron
  SHIELD-MD10 R2** H-bridge,
- runs a **node-driven light/dark schedule** with configurable cycle length (24 h
  wall-clock or T-cycle anchored to a node-supplied ZT0 timestamp) and
  per-direction **fade in / fade out** PWM ramps on the panel LED,
- senses **temperature + humidity** (SHT31) and **light** (BH1750, calibrated lux),
- keeps time from **NTP** with a **DS3231** RTC as battery-backed backup,
- persists its configuration to flash (LittleFS) and survives reboots,
- exposes an **HTTP REST API** that the controller polls — no radio, no broker,
- **doubles as an ethoscope sensor** (same API as `etho_sensor`), so the node logs its
  temperature/humidity/light and runs temperature alerts on it with no node changes,
- supports **OTA** firmware updates and **mDNS** discovery (`incubator-<id>.local`,
  advertising both `_incubator._tcp` and `_sensor._tcp`).

It keeps regulating temperature and lights **even with no network**; NTP and remote
commands simply resume when WiFi returns.

> Status: **compiles clean** for `esp8266:esp8266:d1_mini` with ESP8266 core 3.1.2
> (RAM 42 %, flash 39 %). Not yet bench-tested on hardware — verify the Peltier direction
> polarity and I²C addresses on first bring-up (see [Bring-up](#bring-up--verification)).

---

## Hardware

### Board: WeMos / LOLIN D1 R2 (ESP8266)

| Spec | Value |
|------|-------|
| MCU | ESP8266 (80/160 MHz) |
| Logic level | **3.3 V** (GPIOs are *not* reliably 5 V-tolerant) |
| Digital I/O | D0–D8 (all support PWM/interrupt/I²C **except D0**) |
| Analog in | A0 only, **3.2 V max** (on-board 220 kΩ/100 kΩ divider) — unused here |
| Power in | Micro-USB (5 V) **or** the barrel jack (9–24 V) |
| WiFi | 2.4 GHz b/g/n, on-board |

GPIO mapping was verified against the official **WeMos D1 R2 V2.0.0 schematic**:
`D0=GPIO16, D1=GPIO5(SCL), D2=GPIO4(SDA), D3=GPIO0, D4=GPIO2, D5=GPIO14(SCK),
D6=GPIO12(MISO), D7=GPIO13(MOSI), D8=GPIO15(SS)`. D3/D4/D8 are boot-strapping pins (kept
off the actuator paths); D5/D6/D7/D8 are the hardware-SPI pins — free here since the radio
is gone and all sensors are I²C.

### Pin assignment

| WeMos | GPIO | Connected to | Notes |
|------|------|--------------|-------|
| **D1** | GPIO5 | I²C **SCL** | shared bus: SHT31 + BH1750 + DS3231 |
| **D2** | GPIO4 | I²C **SDA** | shared bus |
| **D6** | GPIO12 | MD10 **PWM** | Peltier power; shield jumper **JP5 = D6** |
| **D7** | GPIO13 | MD10 **DIR** | Peltier direction; shield jumper **JP8 = D7** |
| **D5** | GPIO14 | LED MOSFET gate | grow-light PWM (on-board LED mirrors it — cosmetic) |
| **D0** | GPIO16 | hot-side fan MOSFET | digital on/off; optional; *not* via the MD10 |
| A0 | ADC | — | unused (light is on I²C) |
| D3/D4/D8 | GPIO0/2/15 | — | **avoid** (boot-mode strapping pins) |

> **Why these pins?** The Peltier PWM/DIR lines are constrained by the MD10's jumper
> selectors — **PWM (JP5)** ∈ {D3,D5,D6,D9,D10,D11}, **DIR (JP8)** ∈ {D2,D4,D7,D8,D12,D13}.
> The D1 R2 only exposes D0–D8, so the only safe, free intersection is **PWM=D6, DIR=D7**.
> The grow light then takes the remaining clean PWM pin **D5**, and the fan (driven by its
> own MOSFET, not the H-bridge, so it isn't jumper-bound) takes the digital-only **D0**.

### Peltier driver — Cytron SHIELD-MD10 R2

Single-channel 10 A bi-directional H-bridge (confirmed from the *SHIELD-MD10 User's Manual
REV 2.0*):

- **Accepts 3.3 V logic** ("3.3 V and 5 V logic level input"; V_IOH min = 3 V) — the ESP8266
  drives PWM/DIR **directly, no level shifter**.
- **PWM ≤ 10 kHz** (firmware uses 5 kHz).
- **Motor supply 7–25 V** — a 12 V Peltier rail is ideal; **< 7 V will not work**.
- Logic: `PWM=0` → both outputs LOW (motor off); `PWM=1` + `DIR` LOW/HIGH selects direction.
- Fully-NMOS bridge, needs **no heatsink itself** (the Peltier still does — see below).

**Mounting:** the shield is **stacked** on the D1 R2 (UNO form factor; pass-through headers
keep D1/D2/D5/D0/A0 reachable on top). Set the two mini-jumpers to **JP5 = D6 (PWM)** and
**JP8 = D7 (DIR)**. Power the Peltier from its **own 7–25 V supply** into the MD10 MOTOR
terminals — never through the WeMos. **Common ground** between the WeMos, the MD10 supply
and the LED supply is mandatory.

> ⚠️ **Direction polarity is wiring-dependent.** Which `DIR` level heats vs. cools depends
> on how your TEC faces and how it connects to MD10 OUT A/B. The firmware default is
> `DIR_HEAT = HIGH` (`pins.h`) — **verify on the bench and swap if reversed.**

### Sensors (all I²C, 3.3 V, on the D1/D2 bus)

| Sensor | Measures | I²C addr | Library |
|--------|----------|----------|---------|
| **SHT31** | temperature + humidity | `0x44` (or `0x45`) | Adafruit SHT31 |
| **BH1750** | ambient light (lux) | `0x23` (or `0x5C`) | BH1750 (Christopher Laws) |
| **DS3231** *or* **DS1307** | real-time clock (backup) | `0x68` | RTClib (`RTC_DS1307` class — works with either; DS3231 is more accurate) |

Add **4.7 kΩ pull-ups to 3.3 V** on SDA/SCL if the modules don't already carry them, and
confirm none pulls the bus to 5 V. **DS3231 is recommended** (3.3 V-native, TCXO-accurate),
but the legacy **DS1307/TinyRTC also works** — the firmware uses RTClib's `RTC_DS1307`
class, which drives either chip (same I²C address and time registers). Note the DS1307 is a
5 V part: power its module from 5 V and keep its I²C lines at 3.3 V (level-shift, or use a
module whose pull-ups go to 3.3 V) to stay safe on the ESP8266 bus.

> **Where to wire I²C — D1/D2 or A4/A5?** Same two pins. On the D1 R2 the I²C bus appears
> at several header positions all tied to the same GPIOs (confirmed from the V2.0.0
> schematic): **D2 = A4 = the SDA pin = GPIO4**, and **D1 = A5 = the SCL pin = GPIO5**. So
> you may connect the sensors to **A4/A5** (or the dedicated SDA/SCL pins by AREF) instead
> of D1/D2 — it is electrically identical and **needs no firmware change** (`Wire` runs on
> GPIO4/GPIO5 whichever header you use). With the MD10 stacked, **A4/A5 is the cleaner
> choice**: the shield's analog header is unused pass-through, so those pins come straight
> up to the top of the stack. (A1/A2/A3 are *not* analog inputs — the ESP8266 has only the
> single A0 ADC, which we leave free regardless.)

### Light panel

PWM on **D5** through a **logic-level N-MOSFET** (e.g. IRLZ44N). The gate is driven at
3.3 V, so a classic 5 V-gate FET will **not** switch fully — use a logic-level part or a
gate driver. The LED panel is powered from its own rail (commonly 12 V), switched
low-side by the MOSFET.

### Power & thermal

- Power the WeMos from a solid **5 V** source (USB or a 5 V buck) — WiFi TX spikes ~300 mA;
  don't share a marginal rail with the sensors.
- The Peltier's **hot side needs a heatsink + fan** (fan on D0). Keep TEC current within
  the MD10's **10 A continuous** (15 A peak, ≤10 s).
- **Power sequencing (per the MD10 manual):** power/boot the WeMos first, *then* energise
  the MD10 motor supply. The firmware holds the H-bridge OFF at boot (PWM=0); a pull-down
  on D6 is recommended as belt-and-braces.

### Wiring overview

```
                 WeMos D1 R2 (ESP8266, 3.3V)         MD10 R2 (stacked)
   I2C  D1(SCL)/D2(SDA) ──┬─ SHT31 (0x44)           JP5 = D6  ── PWM
                          ├─ BH1750 (0x23)          JP8 = D7  ── DIR
                          └─ DS3231 (0x68)          MOTOR ─── Peltier (own 7–25 V)
   D6 ── PWM ─────────────────────────────────────► (via stack)
   D7 ── DIR ─────────────────────────────────────► (via stack)
   D5 ── PWM ──► logic-level MOSFET ──► LED panel (+rail)
   D0 ── on/off ► MOSFET ──► hot-side fan (+rail)
   5V/USB ── WeMos power          GND ── COMMON ground (WeMos + MD10 + LED + fan)
```

### Bill of materials (per incubator)

| Item | Part | Notes |
|------|------|-------|
| MCU | WeMos/LOLIN D1 R2 (ESP8266) | reused stock |
| Peltier driver | Cytron SHIELD-MD10 R2 | stacked; JP5=D6, JP8=D7 |
| Temp/humidity | SHT31 module | I²C 0x44 |
| Light | BH1750 module | I²C 0x23 |
| RTC | DS3231 (ZS-042) + CR2032 — or legacy DS1307/TinyRTC | I²C 0x68; backup time. DS1307 module: power at 3.3 V so its I²C pull-ups don't push 5 V onto the bus |
| LED switch | logic-level N-MOSFET (IRLZ44N) + gate resistor | 3.3 V gate |
| Peltier | TEC module + heatsink + fan | thermal mgmt required |
| Supplies | 5 V (WeMos), 7–25 V (Peltier/LED) | common ground |
| Misc | 2× 4.7 kΩ I²C pull-ups, D6 pull-down, wiring | — |

---

## Firmware architecture

Cooperative **non-blocking** super-loop — the ESP8266 WiFi stack must be serviced
frequently, so nothing blocks. `loop()` services the network/HTTP/OTA stacks every pass and
runs each task on its own `millis()` timer.

| File | Responsibility |
|------|----------------|
| `client_firmware_esp8266.ino` | `setup()`/`loop()`, the task scheduler |
| `incubator.h` | shared `Config` + `State` structs, `LightMode` enum, FW version |
| `pins.h` | pin map + PWM/direction constants |
| `Config.{h,cpp}` | load/save `/config.json` (LittleFS); JSON ↔ `cfg`; defines the globals |
| `Sensors.{h,cpp}` | SHT31 + BH1750 read, 5 s self-heating guard, fault flag |
| `TimeKeeper.{h,cpp}` | NTP (SNTP) + DS3231 backup; local minute-of-day for the schedule |
| `Peltier.{h,cpp}` | PID + DIR/PWM, deadband, direction-dwell, slew, failsafes |
| `LightControl.{h,cpp}` | non-blocking fader + DD/LD/LL/DL/MM scheduler |
| `Network.{h,cpp}` | WiFiManager provisioning, mDNS, OTA, reconnect |
| `Api.{h,cpp}` | `ESP8266WebServer` REST routes |

### Control & behaviour

- **Temperature:** a PID on `set_temp − measured`; sign → DIR (heat/cool), magnitude →
  PWM duty. A **deadband** (`±0.3 °C`) stops hunting, a **direction-dwell** prevents rapid
  current reversal, a **slew limit** caps duty change per cycle, and a **failsafe** forces
  the Peltier OFF on sensor fault or out-of-range temperature.
- **Light schedule:** always light-during-window. With `light_period_minutes==1440` and
  `light_cycle_anchor==0` the window is wall-clock `[lights_on, lights_off)`; otherwise
  it's `[lights_on, lights_off)` *within* a cycle of `light_period_minutes` whose phase is
  `(now − light_cycle_anchor) mod period`. Per-direction fade (`fade_in_ms` / `fade_out_ms`)
  ramps the panel PWM between `0%` and `max_light` non-blockingly; a bench override is
  available via `POST /command {"set_light":<pct>}` (transient — the next schedule tick
  resumes control). The four legacy mode shortcuts (`DD/LL/DL/MM`) were removed in 3.2 —
  the node is the single source of truth.
- **Humidity** is **sensed only** — the current hardware has no humidity actuator
  (`set_hum` is kept for logging/future use).
- **Time:** NTP is primary; the server is the `ntp` config field (default `pool.ntp.org`).
  **On an offline lab network, set `ntp` to a local NTP source** — e.g. the controller's IP
  (it already runs `ntpd`) or the router. The DS3231 preserves time across reboots, and if
  there is no NTP at all the controller can push the clock with
  `POST /command {"set_time": <unix_epoch>}`. With no valid time, LD/DL light modes simply
  hold (temperature control is unaffected).

---

## Build & flash

Requires the ESP8266 Arduino core and four libraries (versions known-good in parentheses):

```bash
# core
arduino-cli core install esp8266:esp8266        # tested with 3.1.2

# libraries
arduino-cli lib install "Adafruit SHT31 Library" \
                        "BH1750" \
                        "RTClib" \
                        "WiFiManager" \
                        "ArduinoJson"            # v7.x
```

Board = *LOLIN(WEMOS) D1 R2 & mini* (`esp8266:esp8266:d1_mini`).

**Use `build.sh`** — it bumps the build number, compiles, and (optionally) OTA-flashes:

```bash
./build.sh                    # bump FW_BUILD + compile only
./build.sh 192.168.4.224      # bump + compile + OTA flash (IP or incubator-<id>.local)
```

First-ever flash must be over USB:

```bash
arduino-cli upload --fqbn esp8266:esp8266:d1_mini -p /dev/ttyUSB0 client_firmware_esp8266
```

After that, updates go **over the air** (ArduinoOTA). Note: `arduino-cli upload -p <ip>`
fails non-interactively (it prompts for an OTA password), so `build.sh` calls the ESP8266
`espota.py` tool directly:

```bash
python3 ~/.arduino15/packages/esp8266/hardware/esp8266/<ver>/tools/espota.py \
        -i <ip> -p 8266 -f /tmp/inc_build/client_firmware_esp8266.ino.bin -r
```

### Versioning

`version.h` carries three fields, all reported in `/telemetry`:

| Field | Meaning |
|-------|---------|
| `FW_VERSION` | semantic version, set by hand (`"3.0.0-wifi"`) |
| `FW_BUILD` | integer, **auto-incremented by `build.sh`** each build — do not edit by hand |
| `FW_BUILD_DATE` | compile timestamp (`__DATE__ __TIME__`), changes on every rebuild |

After an OTA, confirm the new image is live by checking the build number rose:

```bash
curl -s http://incubator-1.local/telemetry | grep -o '"build":[0-9]*'
```

---

## First-boot provisioning

On first boot (no WiFi credentials), the node starts a captive-portal AP named
**`incubator-setup-<id>`**. Connect to it, enter your WiFi credentials and the **Incubator
ID**, and save. Credentials are stored by WiFiManager; the ID is written to `/config.json`.
The node then joins your network and is reachable at **`incubator-<id>.local`**.

All other settings live in `/config.json` and are editable at runtime over REST.

---

## REST API

Served on port 80. JSON bodies. The controller polls `/telemetry`; liveness is inferred
from poll success/timeout.

**Incubator API** (polled by the node `IncubatorScanner`, mDNS service `_incubator._tcp`):

| Method & path | Purpose |
|---|---|
| `GET /telemetry` | live readings + state |
| `GET /config` | current persisted configuration |
| `POST /config` | update a subset of config fields (JSON), then persist |
| `POST /command` | transient actions: `sync_time`, `set_time` (epoch), `set_light`, `identify`, `reboot` |
| `GET /health` | wifi / heap / time-valid / sensor-fault / uptime |
| `GET /status` | human-readable status page (auto-refresh) |

**Sensor API** — the incubator *also* presents itself as an ethoscope **sensor** (identical
API to `accessories/hardware/etho_sensor`, mDNS service `_sensor._tcp`), so the node's
`SensorScanner` logs its readings to CSV and runs temperature alerts with no node changes:

| Method & path | Purpose |
|---|---|
| `GET /` | sensor JSON: `{id (MAC), ip, name, location, temperature, humidity, light (lux), alerts}` (values as strings) |
| `GET /id` | `{"id":"<MAC>"}` |
| `POST /set` | update sensor `name`/`location` (the node pushes the bound incubator's name into `location`) |

> The sensor `location` defaults to `incubator-<id>` and is overwritten by the node with the
> bound incubator's name, so readings always group under their incubator. From firmware 3.2.0
> the node also pushes the **light schedule** (lights_on/off + period + anchor + fade) to
> `/config` on every relevant edit, with a 60 s reconciler re-pushing on drift (e.g. after a
> firmware reboot). Note `GET /` is the sensor data endpoint — the status page is at `/status`.

Examples:

```bash
# Read live state
curl http://incubator-1.local/telemetry

# Push a 9-21h wall-clock photoperiod with a 30s fade in/out and 80% peak brightness
curl -X POST http://incubator-1.local/config \
     -H 'Content-Type: application/json' \
     -d '{"set_temp":24.0,"lights_on":"09:00","lights_off":"21:00",
          "light_period_minutes":1440,"light_cycle_anchor":0,
          "fade_in_ms":30000,"fade_out_ms":30000,"max_light":80}'

# Push a T=21h cycle: light during the first 9h after ZT0 (anchor = now)
curl -X POST http://incubator-1.local/config \
     -d "{\"lights_on\":\"00:00\",\"lights_off\":\"09:00\",
          \"light_period_minutes\":1260,\"light_cycle_anchor\":$(date -u +%s)}"

# Transient bench override (next schedule tick takes back control)
curl -X POST http://incubator-1.local/command -d '{"set_light":50,"sync_time":true}'

# Offline lab: point the node at a local NTP server (e.g. the controller running ntpd)
curl -X POST http://incubator-1.local/config -d '{"ntp":"192.168.1.10"}'

# No NTP at all: push the current UTC epoch directly (controller does `date +%s`)
curl -X POST http://incubator-1.local/command -d "{\"set_time\":$(date -u +%s)}"
```

`POST /config` accepts any subset of: `node_id, tz, ntp, set_temp, set_hum, max_light,
lights_on ("HH:MM" or minutes), lights_off, light_period_minutes, light_cycle_anchor
(unix ts; 0 = wall-clock mode), fade_in_ms, fade_out_ms, report_interval, kp, ki, kd,
deadband, max_duty, dir_dwell_ms, slew_per_cycle, temp_min, temp_max, peltier_enabled`.

`/telemetry` fields include: `node_id, fw, build, built, time, time_valid, uptime_s,
temperature, humidity, lux, sensor_fault, set_temp, set_hum, light_level, max_light,
lights_on, lights_off, light_period_minutes, light_cycle_anchor, fade_in_ms, fade_out_ms,
peltier_duty (signed: + heat / − cool), peltier_dir, fan_on, rssi, wifi`.

---

## Bring-up & verification

Compilation is confirmed (`arduino-cli compile`). On hardware, verify in this order
(each step gates the next):

1. **Flash + serial @115200** → version banner prints.
2. **Provision WiFi** via the captive portal → node reachable at `incubator-<id>.local`.
3. **I²C scan / sensors** → `GET /telemetry` shows plausible `temperature`, `humidity`,
   `lux`; `sensor_fault=false`. (If SHT31 is at `0x45`, change the address in `Sensors.cpp`.)
4. **Light** → `POST /command {"set_light":100}` in mode `MM` fades the panel; WiFi stays up
   during the fade (proves the non-blocking design).
5. **Peltier (low duty, bench)** → raise/lower `set_temp` and watch `peltier_dir`/`duty`.
   **Confirm `heat` actually heats** — if reversed, swap `DIR_HEAT`/`DIR_COOL` in `pins.h`.
6. **Offline test** → drop WiFi; the node keeps regulating temperature and the light
   schedule; reconnect resumes telemetry and NTP.
7. **OTA** → push an update to `incubator-<id>.local`; the new `fw` shows in `/telemetry`.

---

## License

GNU General Public License v2 (or later) — © Giorgio Gilestro <giorgio@gilest.ro>.
