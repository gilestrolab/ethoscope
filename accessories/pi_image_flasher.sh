#!/usr/bin/env bash
# pi_image_flasher.sh — flash Raspberry Pi OS to an SD card so it's SSH-able as ethoscope.
#
# Writes the minimum needed for a headless first boot:
#   - userconf.txt  → Bookworm's stock firstboot service creates the user from this
#   - ssh           → empty marker that enables sshd on first boot
# Everything else (hostname, services, MariaDB, ethoscope software, Wi-Fi, etc.)
# is handled by install_ethoscope_debian.sh, which is also copied onto the card.
#
# Workflow:
#   sudo ./pi_image_flasher.sh --device /dev/sdb
#   # pop the card into the Pi, wait for it to boot
#   ssh ethoscope@raspberrypi.local              # password: ethoscope
#   sudo bash /boot/firmware/install_ethoscope_debian.sh
#
# Options:
#   --device PATH        Target block device (REQUIRED, must be USB and ≤128 GiB)
#   --model pi3|pi4|pi5  Default: pi4 (only affects the default arch)
#   --arch 32|64         Default: 64 (forced to 64 for pi5)
#   --variant lite|desktop|full
#                        Default: lite
#   --user NAME          Default: ethoscope (install_ethoscope_debian.sh expects this)
#   --password PASS      Default: ethoscope (hashed with openssl passwd -6)
#   --no-installer       Don't bundle install_ethoscope_debian.sh
#                        (auto-bundled when the file sits next to this script)
#   --cache-dir PATH     Image cache directory (default: /tmp/pi-images)
#   --no-cache           Re-download the image even if a cached copy exists
#   --keep-image         Keep the downloaded image after flashing (default)
#   --no-keep-image      Delete the cached image after flashing
#   --dry-run            Print actions without writing
#   -h, --help           Show this help
#
# Examples:
#   sudo ./pi_image_flasher.sh --device /dev/sdb                    # pi4, 64-bit, Lite
#   sudo ./pi_image_flasher.sh --device /dev/sdb --model pi3 --arch 32
#   sudo ./pi_image_flasher.sh --device /dev/sdb --password 'changeme'

set -euo pipefail

# --- defaults ---------------------------------------------------------------
DEVICE=""
MODEL="pi4"
ARCH="64"
VARIANT="lite"
USER_VAL="ethoscope"
PASS_VAL="ethoscope"
PLACE_INSTALLER=1
CACHE_DIR="/tmp/pi-images"
NO_CACHE=0
KEEP_IMAGE=1
DRY_RUN=0
MAX_DEVICE_GIB=128

usage() { sed -n '2,36p' "$0"; exit "${1:-0}"; }

# --- arg parsing ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)        DEVICE="$2"; shift 2 ;;
    --model)         MODEL="$2"; shift 2 ;;
    --arch)          ARCH="$2"; shift 2 ;;
    --variant)       VARIANT="$2"; shift 2 ;;
    --user)          USER_VAL="$2"; shift 2 ;;
    --password)      PASS_VAL="$2"; shift 2 ;;
    --no-installer)  PLACE_INSTALLER=0; shift ;;
    --cache-dir)     CACHE_DIR="$2"; shift 2 ;;
    --no-cache)      NO_CACHE=1; shift ;;
    --keep-image)    KEEP_IMAGE=1; shift ;;
    --no-keep-image) KEEP_IMAGE=0; shift ;;
    --dry-run)       DRY_RUN=1; shift ;;
    -h|--help)       usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

# --- validation -------------------------------------------------------------
[[ -n "$DEVICE" ]] || { echo "ERROR: --device is required" >&2; usage 1; }
[[ "$MODEL" =~ ^pi[345]$ ]] || { echo "ERROR: --model must be pi3, pi4 or pi5" >&2; exit 1; }
[[ "$ARCH" =~ ^(32|64)$ ]] || { echo "ERROR: --arch must be 32 or 64" >&2; exit 1; }
[[ "$VARIANT" =~ ^(lite|desktop|full)$ ]] || { echo "ERROR: --variant must be lite, desktop or full" >&2; exit 1; }
[[ "$USER_VAL" =~ ^[a-z][a-z0-9_-]*$ ]] || { echo "ERROR: --user must match [a-z][a-z0-9_-]*" >&2; exit 1; }

# Pi 5 is 64-bit only.
if [[ "$MODEL" == "pi5" && "$ARCH" == "32" ]]; then
  echo "==> pi5 only supports 64-bit; forcing --arch 64"
  ARCH="64"
fi

# Where to find the bundled ethoscope installer (optional).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_SRC="${SCRIPT_DIR}/install_ethoscope_debian.sh"
if (( PLACE_INSTALLER )) && [[ ! -f "$INSTALLER_SRC" ]]; then
  echo "==> install_ethoscope_debian.sh not found next to this script — bundling disabled"
  PLACE_INSTALLER=0
fi

# --- self-elevate (skipped in --dry-run) ------------------------------------
if [[ $EUID -ne 0 && $DRY_RUN -eq 0 ]]; then
  echo "==> Re-executing under sudo..."
  exec sudo -E bash "$0" \
    --device "$DEVICE" --model "$MODEL" --arch "$ARCH" --variant "$VARIANT" \
    --user "$USER_VAL" --password "$PASS_VAL" \
    $([[ $PLACE_INSTALLER -eq 0 ]] && echo --no-installer) \
    --cache-dir "$CACHE_DIR" \
    $([[ $NO_CACHE -eq 1 ]] && echo --no-cache) \
    $([[ $KEEP_IMAGE -eq 0 ]] && echo --no-keep-image) \
    $([[ $DRY_RUN -eq 1 ]] && echo --dry-run)
fi

# --- safety checks on target ------------------------------------------------
[[ -b "$DEVICE" ]] || { echo "ERROR: $DEVICE is not a block device" >&2; exit 1; }

DEV_TRAN=$(lsblk -ndo TRAN "$DEVICE")
DEV_MODEL=$(lsblk -ndo MODEL "$DEVICE")
DEV_BYTES=$(blockdev --getsize64 "$DEVICE")
DEV_GIB=$((DEV_BYTES / 1024 / 1024 / 1024))

echo "==> Target: $DEVICE ($DEV_GIB GiB, $DEV_TRAN, $DEV_MODEL)"

if [[ "$DEV_TRAN" != "usb" ]]; then
  echo "ERROR: $DEVICE is not on a USB transport (got '$DEV_TRAN')." >&2
  echo "       Refusing to write — this avoids clobbering an internal disk." >&2
  exit 1
fi
if (( DEV_GIB > MAX_DEVICE_GIB )); then
  echo "ERROR: $DEVICE is $DEV_GIB GiB (> $MAX_DEVICE_GIB GiB safety guard)." >&2
  exit 1
fi
if (( DEV_GIB < 2 )); then
  echo "ERROR: $DEVICE is only $DEV_GIB GiB; Raspberry Pi OS needs ≥ 4 GiB." >&2
  exit 1
fi

# --- image URL resolution ---------------------------------------------------
case "$ARCH" in
  64) ARCH_SLUG="arm64" ;;
  32) ARCH_SLUG="armhf" ;;
esac
case "$VARIANT" in
  lite)    VARIANT_SLUG="raspios_lite_${ARCH_SLUG}" ;;
  desktop) VARIANT_SLUG="raspios_${ARCH_SLUG}" ;;
  full)    VARIANT_SLUG="raspios_full_${ARCH_SLUG}" ;;
esac
IMG_URL="https://downloads.raspberrypi.com/${VARIANT_SLUG}_latest"
IMG_XZ="${CACHE_DIR}/${VARIANT_SLUG}_latest.img.xz"

echo "==> Image: $VARIANT_SLUG ($MODEL, $ARCH-bit)"
echo "    URL:   $IMG_URL"
echo "    Cache: $IMG_XZ"

# --- download (as the invoking user, not root) ------------------------------
INVOKING_USER="${SUDO_USER:-$USER}"
mkdir -p "$CACHE_DIR"
chown "$INVOKING_USER:" "$CACHE_DIR" 2>/dev/null || true

if [[ $NO_CACHE -eq 1 ]] || [[ ! -s "$IMG_XZ" ]]; then
  echo "==> Downloading image (this can take a few minutes)"
  if (( DRY_RUN )); then
    echo "    [dry-run] curl -L --fail -o '$IMG_XZ' '$IMG_URL'"
  else
    sudo -u "$INVOKING_USER" curl -L --fail --progress-bar -o "$IMG_XZ" "$IMG_URL"
  fi
else
  echo "==> Using cached image ($(numfmt --to=iec --format='%.0f' "$(stat -c%s "$IMG_XZ")"))"
fi

if [[ $DRY_RUN -eq 0 ]]; then
  file_type=$(file -b "$IMG_XZ")
  [[ "$file_type" == *"XZ compressed"* ]] || {
    echo "ERROR: cached file is not XZ-compressed (got: $file_type)" >&2
    echo "       Delete it and retry: rm '$IMG_XZ'" >&2
    exit 1
  }
fi

PWHASH=$(openssl passwd -6 "$PASS_VAL")

echo "==> Plan:"
echo "    user:     ${USER_VAL}  (password hash will be written to userconf.txt)"
echo "    ssh:      enabled"
echo "    installer:$( (( PLACE_INSTALLER )) && echo " bundled (run sudo bash /boot/firmware/install_ethoscope_debian.sh)" || echo " (not bundled)")"

if (( DRY_RUN )); then
  echo "==> [dry-run] would now stop udisks2, write image, mount bootfs, drop userconf.txt + ssh + installer, eject"
  exit 0
fi

# --- udisks2 quiet, partitions unmounted ------------------------------------
UDISKS_WAS_ACTIVE=0
if systemctl is-active --quiet udisks2; then
  UDISKS_WAS_ACTIVE=1
  echo "==> Stopping udisks2 (prevents auto-remount races during write)"
  systemctl stop udisks2 || true
fi

restart_udisks() {
  if (( UDISKS_WAS_ACTIVE )); then
    systemctl start udisks2 || true
  fi
}

echo "==> Unmounting any partitions on $DEVICE"
for p in $(lsblk -lno NAME "$DEVICE" | tail -n +2); do
  umount "/dev/$p" 2>/dev/null || true
done

# --- write the image --------------------------------------------------------
echo "==> Writing image (xzcat | dd bs=4M conv=fsync)"
xzcat "$IMG_XZ" | dd of="$DEVICE" bs=4M conv=fsync status=progress
sync

echo "==> Re-reading partition table"
partprobe "$DEVICE"
sleep 2

# --- patch bootfs -----------------------------------------------------------
BOOT_PART="${DEVICE}1"
[[ -b "$BOOT_PART" ]] || BOOT_PART="${DEVICE}p1"
[[ -b "$BOOT_PART" ]] || { echo "ERROR: cannot find boot partition for $DEVICE" >&2; restart_udisks; exit 1; }

MNT=$(mktemp -d /tmp/pi-bootfs.XXXXXX)
cleanup_mount() {
  if mountpoint -q "$MNT"; then umount "$MNT" || true; fi
  rmdir "$MNT" 2>/dev/null || true
}
trap cleanup_mount EXIT

echo "==> Mounting $BOOT_PART at $MNT"
mount "$BOOT_PART" "$MNT"

echo "==> Writing first-boot files"
# userconf.txt — Bookworm's stock firstboot service reads this and creates the user.
echo "${USER_VAL}:${PWHASH}" > "$MNT/userconf.txt"
echo "    + userconf.txt   (user '${USER_VAL}')"
# ssh marker — enables sshd on first boot.
touch "$MNT/ssh"
echo "    + ssh            (sshd enabled)"
# Bundled installer — left on the bootfs partition; SSH in and run it.
if (( PLACE_INSTALLER )); then
  cp "$INSTALLER_SRC" "$MNT/install_ethoscope_debian.sh"
  echo "    + install_ethoscope_debian.sh  (run after ssh-in)"
fi

sync
echo "==> Unmounting and powering off $DEVICE"
umount "$MNT"
rmdir "$MNT" 2>/dev/null || true
trap - EXIT
udisksctl power-off -b "$DEVICE" 2>/dev/null || eject "$DEVICE" 2>/dev/null || true

restart_udisks

if (( KEEP_IMAGE == 0 )); then
  echo "==> Removing cached image $IMG_XZ"
  rm -f "$IMG_XZ"
fi

cat <<EOF
==> Done. Next steps:
    1. Pop the card into the Pi and power it on (wait ~30-60 s for first boot).
    2. ssh ${USER_VAL}@raspberrypi.local        # password: ${PASS_VAL}
$( (( PLACE_INSTALLER )) && echo "    3. sudo bash /boot/firmware/install_ethoscope_debian.sh")
EOF
