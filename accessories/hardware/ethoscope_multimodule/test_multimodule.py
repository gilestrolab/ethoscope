#!/usr/bin/env python3
"""
Simple test routine for mAGO firmware.

Connects to the board, queries capabilities, and runs basic tests
on all available commands. Exits with 0 on success, 1 on failure.

Usage:
    python test_multimodule.py [port]                 # full self-test
    python test_multimodule.py [port] --identify      # spin motors one by one (interactive)
    python test_multimodule.py [port] --identify --auto            # timed sweep, no prompts
    python test_multimodule.py [port] --identify --duration 2000   # ms per motor

    port: Serial port (default: /dev/ttyACM0)
"""

import json
import sys
import time

import serial


def send_cmd(ser, cmd, wait=0.5):
    """Send a command and return all response lines."""
    ser.reset_input_buffer()
    ser.write(f"{cmd}\n".encode())
    time.sleep(wait)
    lines = []
    while ser.in_waiting:
        lines.append(ser.readline().decode("utf-8", errors="replace").strip())
    return lines


def motor_channels(info):
    """Return the physical channels carrying motors, per firmware mapping.

    Mirrors the channel assignment in ethoscope_multimodule.ino setup():
    on SD / AGOSD / mAGOLED modules (types 0, 1, 3) motors sit on the odd
    channels (1, 3, 5, ...). Other module types have no motors.

    Args:
        info (dict): Parsed JSON returned by the 'T' command.

    Returns:
        list[int]: Physical channel number for each motor, in motor order.
    """
    module_type = info["module"]["type"]
    motor_count = info["capabilities"]["motors"]
    if module_type in (0, 1, 3):
        return [2 * i + 1 for i in range(motor_count)]
    return []


def identify_motors(ser, info, duration_ms=1500, interactive=True):
    """Spin each motor one at a time so a faulty unit can be identified.

    Pulses each motor channel individually with a clear label. In
    interactive mode it pauses after every motor for the operator to
    confirm rotation, recording any motor that fails to spin.

    Args:
        ser (serial.Serial): Open serial connection to the board.
        info (dict): Parsed JSON returned by the 'T' command.
        duration_ms (int): How long to spin each motor, in milliseconds.
        interactive (bool): If True, prompt for confirmation after each
            motor; if False, run an automatic timed sweep with no prompts.

    Returns:
        list[int]: Motor numbers (1-indexed) flagged as faulty.
    """
    channels = motor_channels(info)
    if not channels:
        print("No motors on this module.")
        return []

    faulty = []
    print(f"\n=== Motor Identification ({len(channels)} motors) ===")
    if interactive:
        print("After each spin:  Enter = OK,  n = not spinning,  r = repeat,  q = quit\n")

    i = 0
    while i < len(channels):
        ch = channels[i]
        motor_no = i + 1
        print(f"--> Motor {motor_no:>2} (channel {ch:>2}) spinning {duration_ms} ms ...", flush=True)
        # Single-channel pulse is immediate (no stagger); wait out the pulse.
        send_cmd(ser, f"P {ch} {duration_ms}", wait=duration_ms / 1000 + 0.5)

        if not interactive:
            time.sleep(0.4)
            i += 1
            continue

        ans = input("    Spin OK? [Enter=yes / n=no / r=repeat / q=quit]: ").strip().lower()
        if ans == "r":
            continue  # repeat the same motor
        if ans == "q":
            print("Aborted by operator.")
            break
        if ans == "n":
            faulty.append(motor_no)
            print(f"    -> Motor {motor_no} (channel {ch}) flagged FAULTY")
        i += 1

    print("\n" + "=" * 30)
    if faulty:
        print(f"FAULTY motor(s): {', '.join(str(m) for m in faulty)}")
    elif interactive:
        print("All motors confirmed spinning.")
    else:
        print("Sweep complete.")
    return faulty


def main():
    # --- Argument parsing (positional port + optional flags) ---
    identify = auto = False
    duration_ms = 1500
    positional = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--identify", "--motors"):
            identify = True
        elif arg == "--auto":
            auto = True
        elif arg == "--duration":
            i += 1
            duration_ms = int(args[i])
        else:
            positional.append(arg)
        i += 1

    port = positional[0] if positional else "/dev/ttyACM0"
    errors = 0

    print(f"Connecting to {port}...")
    try:
        ser = serial.Serial(port, 115200, timeout=2)
    except serial.SerialException as e:
        print(f"FAIL: Cannot open {port}: {e}")
        sys.exit(1)

    time.sleep(2)  # Wait for Arduino reset after connection
    ser.reset_input_buffer()

    # --- Firmware info ---
    print("\n--- Firmware Info ---")
    lines = send_cmd(ser, "T")
    if not lines:
        print("FAIL: No response to T command")
        sys.exit(1)

    try:
        info = json.loads(lines[0])
        print(f"  Version:  {info['version']}")
        print(f"  Module:   {info['module']['name']} (type {info['module']['type']})")
        caps = info["capabilities"]
        print(f"  Motors:   {caps['motors']}")
        print(f"  Valves:   {caps['valves']}")
        print(f"  LEDs:     {caps['leds']}")
        print(f"  Channels: {caps['total_channels']}")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"FAIL: Bad JSON from T command: {e}")
        print(f"  Raw: {lines[0]}")
        sys.exit(1)

    total_ch = caps["total_channels"]

    # --- Motor identification mode (spin one by one), then exit ---
    if identify:
        faulty = identify_motors(ser, info, duration_ms=duration_ms, interactive=not auto)
        ser.close()
        sys.exit(1 if faulty else 0)

    # --- Help menu ---
    print("\n--- Help Menu ---")
    lines = send_cmd(ser, "H")
    for line in lines:
        print(f"  {line}")
    if not lines:
        print("FAIL: No response to H command")
        errors += 1

    # --- Single channel pulse ---
    print(f"\n--- Pulse Test (P) ---")
    for ch in [0, total_ch - 1]:
        lines = send_cmd(ser, f"P {ch} 200", wait=0.5)
        response = " ".join(lines)
        if f"Ch{ch} ON" in response:
            print(f"  P {ch} 200 -> OK")
        else:
            print(f"  P {ch} 200 -> FAIL: {response}")
            errors += 1
    time.sleep(0.3)

    # --- Error handling ---
    print("\n--- Error Handling ---")
    test_cases = [
        (f"P {total_ch} 100", "ERROR"),  # Channel out of range
        ("P 0", "ERROR"),  # Missing argument
    ]
    if caps["leds"] > 0:
        test_cases.append(("W 0 100 100", "ERROR"))  # Missing cycle count

    for cmd, expect in test_cases:
        lines = send_cmd(ser, cmd, wait=0.3)
        response = " ".join(lines)
        if expect in response:
            print(f"  {cmd} -> OK (caught)")
        else:
            print(f"  {cmd} -> FAIL: expected {expect}, got: {response}")
            errors += 1

    # --- Motor tests ---
    if caps["motors"] > 0:
        print("\n--- Motor All (A) ---")
        # The firmware staggers motor start AND stop by ACTIVATION_DELAY (250ms)
        # each, so "A 1" really takes motors*0.25 (on) + 1s (run) + motors*0.25
        # (off). Wait for the full sequence plus a safety buffer.
        a_wait = caps["motors"] * 0.5 + 1 + 1.5
        lines = send_cmd(ser, "A 1", wait=a_wait)
        response = " ".join(lines)
        if "motors ON" in response and "motors OFF" in response:
            print("  A 1 -> OK")
        else:
            print(f"  A 1 -> FAIL: {response}")
            errors += 1

    # --- LED tests ---
    if caps["leds"] > 0:
        print("\n--- LED All (B) ---")
        lines = send_cmd(ser, "B 1", wait=2)
        response = " ".join(lines)
        if "LEDs ON" in response and "LEDs OFF" in response:
            print("  B 1 -> OK")
        else:
            print(f"  B 1 -> FAIL: {response}")
            errors += 1

        print("\n--- Pulse Train (W) ---")
        lines = send_cmd(ser, "W 0 100 100 3", wait=1.5)
        response = " ".join(lines)
        if "Pulse ch0" in response and "done" in response:
            print("  W 0 100 100 3 -> OK")
        else:
            print(f"  W 0 100 100 3 -> FAIL: {response}")
            errors += 1

        print("\n--- Pulse All LEDs (X) ---")
        lines = send_cmd(ser, "X 100 100 2", wait=1.5)
        response = " ".join(lines)
        if "All LEDs pulse" in response and "done" in response:
            print("  X 100 100 2 -> OK")
        else:
            print(f"  X 100 100 2 -> FAIL: {response}")
            errors += 1

    # --- Demo ---
    print("\n--- Demo (D) ---")
    # Demo holds each of the total_ch channels ~600ms (500ms pulse + loop slack).
    demo_wait = total_ch * 0.6 + 2
    lines = send_cmd(ser, "D", wait=demo_wait)
    response = " ".join(lines)
    if "Running demo" in response and "Demo completed" in response:
        print(f"  D -> OK ({len(lines)} lines)")
    else:
        print(f"  D -> FAIL: {response}")
        errors += 1

    # --- Summary ---
    ser.close()
    print("\n" + "=" * 30)
    if errors == 0:
        print(f"ALL TESTS PASSED")
    else:
        print(f"FAILED: {errors} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
