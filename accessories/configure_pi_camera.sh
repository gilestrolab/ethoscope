#!/usr/bin/env bash
# configure_pi_camera.sh — write the camera section of config.txt for the
# Raspberry Pi model this is actually running on, idempotently.
#
# This is the SINGLE SOURCE OF TRUTH for the model→camera mapping, shared by:
#   * install_ethoscope_debian.sh step 12  (build time)
#   * ethoscope_camera_firstboot.service   (every boot)
#
# Why it exists: the camera stack differs fundamentally by Pi model —
#   Pi 2/3 → legacy firmware camera (start_x.elf + the bcm2835-v4l2 V4L2 shim)
#   Pi 4/5 → KMS / libcamera         (vc4-kms-v3d + imx219 overlay)
# so a card configured for one model has a DEAD camera on another. Because the
# first-boot service runs this on every boot, ONE image auto-corrects its camera
# the first time it is booted on a different model (rewriting the block and
# rebooting once), and is a no-op forever after. That lets a single ethoscope
# image serve Pi 2/3/4/5 instead of shipping one image per model.
#
# We own exactly one delimited block in config.txt and rewrite it only when the
# model changes; everything outside the block is left untouched.
#
# Usage:
#   sudo configure_pi_camera.sh              # apply for this model; exit 10 if changed
#   sudo configure_pi_camera.sh --boot       # apply; reboot if changed (first-boot svc)
#   sudo configure_pi_camera.sh --model pi4  # force a model (testing / cross-config)
#   configure_pi_camera.sh --config FILE     # target a specific config.txt (testing)
set -uo pipefail

BEGIN_MARK="# >>> ethoscope camera (managed by configure_pi_camera.sh) >>>"
END_MARK="# <<< ethoscope camera <<<"
# Overridable so the block can be exercised without touching the real system.
MODULES_FILE="${ETHOSCOPE_CAMERA_MODULES_FILE:-/etc/modules-load.d/picamera.conf}"

DO_BOOT=0
MODEL=""
CONFIG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --boot)    DO_BOOT=1; shift ;;
    --model)   MODEL="${2:-}"; shift 2 ;;
    --config)  CONFIG="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { echo "[camera-config] $*"; }

detect_model() {
  local rev
  rev=$(grep -m1 'Revision' /proc/cpuinfo 2>/dev/null | awk '{print $3}')
  case "$rev" in
    a01041|a21041|a22042)        echo pi2 ;;
    a02082|a22082|a32082|a020d3) echo pi3 ;;
    *)
      if   [[ "$rev" =~ ^[bc][0-9a-f]{5}$ ]]; then echo pi4
      elif [[ "$rev" =~ ^d[0-9a-f]{5}$ ]];    then echo pi5
      else echo pi; fi ;;
  esac
}

find_config() {
  local c
  for c in /boot/firmware/config.txt /boot/config.txt; do
    [[ -f "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

# The camera lines for a model — WITHOUT the markers. Legacy models also need
# the bcm2835-v4l2 module loaded (WANT_MODULE), which the caller handles.
desired_block() {
  case "$1" in
    pi2|pi3)
      cat <<'BLK'
# Legacy firmware camera (Pi 2/3)
start_file=start_x.elf
fixup_file=fixup_x.dat
gpu_mem=256
cma_lwm=
cma_hwm=
cma_offline_start=
awb_auto_is_greyworld=1
camera_auto_detect=1
dtparam=camera=on
BLK
      ;;
    pi4|pi5)
      cat <<'BLK'
# KMS / libcamera camera (Pi 4/5)
dtoverlay=vc4-kms-v3d
gpu_mem=256
dtoverlay=imx219
camera_auto_detect=1
dtparam=camera=on
BLK
      ;;
    *)
      cat <<'BLK'
# Generic camera fallback (unknown model)
gpu_mem=128
dtoverlay=imx219
camera_auto_detect=1
dtparam=camera=on
BLK
      ;;
  esac
}

# --- resolve inputs ---------------------------------------------------------
[[ -n "$MODEL"  ]] || MODEL=$(detect_model)
[[ -n "$CONFIG" ]] || CONFIG=$(find_config) || { log "no config.txt found — nothing to do"; exit 0; }
[[ -f "$CONFIG" ]] || { log "config.txt not found at $CONFIG"; exit 2; }

case "$MODEL" in pi2|pi3) WANT_MODULE=1 ;; *) WANT_MODULE=0 ;; esac

# Desired managed block (markers included). $(...) trims trailing newlines so
# this matches what awk extracts from the file byte-for-byte.
want_body=$(printf '%s\n%s\n%s' "$BEGIN_MARK" "$(desired_block "$MODEL")" "$END_MARK")

# Camera keys this script owns. They must live ONLY inside the managed block;
# any copy elsewhere (e.g. the direct lines older installers appended) is a
# stray that would fight the block on another model, so we strip them. Precise
# on dtoverlay so the non-camera overlays (disable-bt, ...) are never touched.
STRAY_RE='^[[:space:]]*(start_file|fixup_file|gpu_mem|cma_lwm|cma_hwm|cma_offline_start|awb_auto_is_greyworld|camera_auto_detect)=|^[[:space:]]*dtparam=camera=|^[[:space:]]*dtoverlay=(vc4-kms-v3d|imx219)'

extract_block() {  # print just the managed block (markers included)
  awk -v b="$BEGIN_MARK" -v e="$END_MARK" \
    'index($0,b){f=1} f{print} index($0,e){f=0}' "$1"
}
strip_block() {    # print the file with the managed block removed
  awk -v b="$BEGIN_MARK" -v e="$END_MARK" \
    'index($0,b){skip=1} !skip{print} index($0,e){skip=0}' "$1"
}
has_strays() {     # any owned camera key sitting outside the managed block?
  strip_block "$1" | grep -Eq "$STRAY_RE"
}

module_ok() {
  if [[ "$WANT_MODULE" == 1 ]]; then
    [[ -f "$MODULES_FILE" ]] && grep -qx 'bcm2835-v4l2' "$MODULES_FILE"
  else
    [[ ! -f "$MODULES_FILE" ]]
  fi
}

if [[ "$(extract_block "$CONFIG")" == "$want_body" ]] && ! has_strays "$CONFIG" && module_ok; then
  log "config.txt already correct for $MODEL — no change"
  exit 0
fi

log "applying camera config for $MODEL -> $CONFIG"

# Rebuild: keep everything except the managed block and any stray camera keys,
# then append a fresh block. This migrates config.txt written by older installers
# (direct start_x.elf/imx219 lines) into the managed, model-swappable form.
tmp="${CONFIG}.ethoscope.tmp"
{ strip_block "$CONFIG" | grep -Ev "$STRAY_RE"; printf '%s\n' "$want_body"; } > "$tmp"
mv "$tmp" "$CONFIG"

# Legacy-camera V4L2 module: present for Pi 2/3, absent otherwise.
if [[ "$WANT_MODULE" == 1 ]]; then
  mkdir -p "$(dirname "$MODULES_FILE")"
  echo 'bcm2835-v4l2' > "$MODULES_FILE"
else
  rm -f "$MODULES_FILE"
fi

# Verify the write landed — guards against a reboot loop on a read-only rootfs.
if [[ "$(extract_block "$CONFIG")" != "$want_body" ]] || has_strays "$CONFIG"; then
  log "ERROR: $CONFIG did not update as expected — not rebooting"
  exit 1
fi

log "camera config updated for $MODEL"
if [[ "$DO_BOOT" == 1 ]]; then
  log "rebooting once so the firmware picks up the new camera settings..."
  systemctl reboot
fi
exit 10
