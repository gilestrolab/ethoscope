#!/usr/bin/env bash
# build.sh — bump the firmware build number, compile, and (optionally) OTA-flash.
#
#   ./build.sh                 bump FW_BUILD + compile
#   ./build.sh 192.168.4.224   bump + compile + OTA upload to that IP
#   ./build.sh incubator-51.local   (mDNS name works too)
#
# The build number lives in version.h and is reported by /telemetry as "build", so after a
# flash you can confirm the new image is running by checking that the number went up.
set -euo pipefail
cd "$(dirname "$0")"

FQBN="esp8266:esp8266:d1_mini"
OUT="/tmp/inc_build"
VFILE="version.h"
# arduino-cli requires the sketch directory's name to match its main .ino. This repo folder
# is "firmware" but the sketch is client_firmware_esp8266.ino, so compiling "." in place
# fails ("main file missing: firmware.ino"). Stage the sources into a correctly-named temp
# sketch dir and compile that instead.
SKETCH="client_firmware_esp8266"
STAGE="/tmp/${SKETCH}_src"

# --- bump FW_BUILD (matches the integer line only, never FW_BUILD_DATE) ---
cur=$(awk '/^#define FW_BUILD[ \t]/{print $3}' "$VFILE")
next=$((cur + 1))
sed -i -E "s/^#define FW_BUILD[[:space:]]+[0-9]+/#define FW_BUILD       ${next}/" "$VFILE"
echo ">> Building firmware build #${next}"

# --- stage sources into a sketch dir named after the .ino, then compile ---
STAGE_SKETCH="${STAGE}/${SKETCH}"
rm -rf "$STAGE"
mkdir -p "$STAGE_SKETCH"
cp ./*.ino ./*.h ./*.cpp "$STAGE_SKETCH"/
arduino-cli compile --fqbn "$FQBN" --output-dir "$OUT" "$STAGE_SKETCH"
BIN="$OUT/${SKETCH}.ino.bin"

# --- optional OTA upload ---
target="${1:-}"
if [ -n "$target" ]; then
  ESPOTA="$HOME/.arduino15/packages/esp8266/hardware/esp8266/3.1.2/tools/espota.py"
  echo ">> OTA uploading build #${next} to ${target}"
  python3 "$ESPOTA" -i "$target" -p 8266 -f "$BIN" -r
  echo ">> Done. Verify with:  curl -s http://${target}/telemetry | grep -o '\"build\":[0-9]*'"
else
  echo ">> Compiled only (build #${next}). Pass an IP/host to OTA-flash."
fi
