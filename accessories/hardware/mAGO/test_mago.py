#!/usr/bin/env python3
"""
Simple test routine for mAGO firmware.

Connects to the board, queries capabilities, and runs basic tests
on all available commands. Exits with 0 on success, 1 on failure.

Usage:
    python test_mago.py [port]

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


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
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
        lines = send_cmd(ser, "A 1", wait=2)
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
    demo_wait = total_ch * 0.5 + 2
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
