#!/usr/bin/env bash
# ethoscope-image.sh — manage an ethoscope SD card .img file
#
# Operations (combine freely):
#   --info      Read-only: print /etc/sdimagename and the /opt/ethoscope
#               git HEAD / branch / remote. Mounts the image read-only.
#   --fsck      Run e2fsck on the rootfs and fsck.fat on the boot partition
#               (auto-fixing any issues). Partitions must be unmounted.
#   --update    Pull latest from gilestrolab/ethoscope (dev branch)
#               into /opt/ethoscope, discarding local changes.
#   --shrink    Shrink the rootfs partition + image to fit a Samsung
#               32 GB card (target = 30000 MiB total, ~528 MiB margin).
#   --rename    Update /etc/sdimagename inside the image so its date
#               prefix matches today (YYYYMMDD).
#   --all       Equivalent to --update --shrink --rename (not --info / --fsck).
#
# Usage: sudo ./ethoscope-image.sh [flags] [path/to/image.img]
# If no path is given, the script picks the single .img in its dir.

set -euo pipefail

# --- config -----------------------------------------------------------------
REPO_URL="https://github.com/gilestrolab/ethoscope.git"
BRANCH="dev"

# Shrink target geometry:
#   image total       = 30000 MiB = 31457280000 bytes  (= 61440000 sectors)
#   partition 2 start = sector 1064960 (520 MiB) — unchanged
#   partition 2 size  = 61440000 - 1064960 = 60375040 sectors
#   filesystem target = 29400 MiB (fits inside partition with small tail)
SHRINK_IMG_BYTES=$((30000 * 1024 * 1024))
SHRINK_P2_SECTORS=60375040
SHRINK_FS_SIZE="29400M"

# --- arg parsing ------------------------------------------------------------
DO_INFO=0
DO_FSCK=0
DO_UPDATE=0
DO_SHRINK=0
DO_RENAME=0
IMG=""

usage() { sed -n '2,18p' "$0"; exit "${1:-0}"; }

for arg in "$@"; do
  case "$arg" in
    --info)   DO_INFO=1 ;;
    --fsck)   DO_FSCK=1 ;;
    --update) DO_UPDATE=1 ;;
    --shrink) DO_SHRINK=1 ;;
    --rename) DO_RENAME=1 ;;
    --all)    DO_UPDATE=1; DO_SHRINK=1; DO_RENAME=1 ;;
    -h|--help) usage 0 ;;
    -*) echo "Unknown flag: $arg" >&2; usage 1 ;;
    *)  IMG="$arg" ;;
  esac
done

(( DO_INFO || DO_FSCK || DO_UPDATE || DO_SHRINK || DO_RENAME )) || { echo "No operation requested." >&2; usage 1; }

# Write ops require rw mount; --info alone gets ro mount.
NEEDS_WRITE=$(( DO_UPDATE | DO_RENAME ))

# Locate image if not given
if [[ -z "$IMG" ]]; then
  SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  shopt -s nullglob
  cands=( "$SCRIPT_DIR"/*.img )
  shopt -u nullglob
  if (( ${#cands[@]} == 1 )); then
    IMG="${cands[0]}"
  else
    echo "Specify the .img file path (found ${#cands[@]} candidates in $SCRIPT_DIR)" >&2
    exit 1
  fi
fi
[[ -f "$IMG" ]] || { echo "Image not found: $IMG" >&2; exit 1; }
IMG=$(realpath "$IMG")
echo "==> Image: $IMG"

# Self-elevate
if [[ $EUID -ne 0 ]]; then
  echo "==> Re-executing under sudo..."
  exec sudo -E bash "$0" "$@"
fi

# --- state + cleanup --------------------------------------------------------
LOOP=""
MNT_ROOT=""

cleanup() {
  set +e
  [[ -n "$MNT_ROOT" && -d "$MNT_ROOT" ]] && {
    mountpoint -q "$MNT_ROOT" && umount "$MNT_ROOT"
    rmdir "$MNT_ROOT" 2>/dev/null
  }
  [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null
}
trap cleanup EXIT

attach_loop() {
  # Release any pre-existing loop on this file
  for L in $(losetup -j "$IMG" | cut -d: -f1); do
    losetup -d "$L" 2>/dev/null || true
  done
  LOOP=$(losetup -fP --show "$IMG")
  echo "==> Loop attached: $LOOP"
}

mount_root() {
  MNT_ROOT=$(mktemp -d /tmp/ethoscope-root.XXXXXX)
  if (( NEEDS_WRITE )); then
    mount "${LOOP}p2" "$MNT_ROOT"
  else
    mount -o ro "${LOOP}p2" "$MNT_ROOT"
  fi
}

unmount_root() {
  sync
  umount "$MNT_ROOT"
  rmdir "$MNT_ROOT"
  MNT_ROOT=""
}

detach_loop() {
  losetup -d "$LOOP"
  LOOP=""
}

# --- operations -------------------------------------------------------------
op_info() {
  echo "==> Image info"
  printf '    File:             %s\n' "$IMG"
  printf '    Size on disk:     %s\n' "$(stat -c%s "$IMG") bytes ($(numfmt --to=iec --format='%.2f' "$(stat -c%s "$IMG")"))"
  if [[ -f "$MNT_ROOT/etc/sdimagename" ]]; then
    printf '    /etc/sdimagename: %s\n' "$(<"$MNT_ROOT/etc/sdimagename")"
  else
    printf '    /etc/sdimagename: <missing>\n'
  fi
  local repo="$MNT_ROOT/opt/ethoscope"
  if [[ -d "$repo/.git" ]]; then
    local g=(git -c safe.directory="$repo" -C "$repo")
    printf '    /opt/ethoscope:\n'
    printf '      branch:         %s\n' "$("${g[@]}" rev-parse --abbrev-ref HEAD)"
    printf '      HEAD:           %s\n' "$("${g[@]}" log --oneline -1)"
    printf '      committed:      %s\n' "$("${g[@]}" log -1 --format=%cI)"
    printf '      remote.origin:  %s\n' "$("${g[@]}" config --get remote.origin.url || echo '<unset>')"
  else
    printf '    /opt/ethoscope:   <not a git repo>\n'
  fi
}

op_update() {
  local repo="$MNT_ROOT/opt/ethoscope"
  [[ -d "$repo/.git" ]] || { echo "ERROR: $repo is not a git repo" >&2; exit 2; }
  echo "==> Updating $repo from $REPO_URL ($BRANCH)"
  echo "    Before: $(git -c safe.directory="$repo" -C "$repo" log --oneline -1)"
  git -c safe.directory="$repo" -C "$repo" fetch "$REPO_URL" "$BRANCH"
  git -c safe.directory="$repo" -C "$repo" reset --hard FETCH_HEAD
  git -c safe.directory="$repo" -C "$repo" clean -fd
  echo "    After:  $(git -c safe.directory="$repo" -C "$repo" log --oneline -1)"
}

op_rename() {
  local f="$MNT_ROOT/etc/sdimagename"
  [[ -f "$f" ]] || { echo "ERROR: $f not found" >&2; exit 2; }
  local cur new today
  cur=$(<"$f")
  cur=${cur//$'\n'/}
  today=$(date +%Y%m%d)
  if [[ "$cur" =~ ^[0-9]{8} ]]; then
    new="${today}${cur:8}"
  else
    new="${today}_${cur}"
  fi
  echo "==> /etc/sdimagename: '$cur' -> '$new'"
  printf '%s\n' "$new" > "$f"
}

op_fsck() {
  echo "==> fsck.fat on boot partition (${LOOP}p1)"
  # -a auto-fixes; exits 0 on clean, 1 on fixed, ≥2 on serious errors.
  fsck.fat -a -w "${LOOP}p1" || [[ $? -le 1 ]]
  echo "==> e2fsck on rootfs (${LOOP}p2)"
  e2fsck -f -y "${LOOP}p2"
}

op_shrink() {
  local part="${LOOP}p2"
  echo "==> fsck (pre-resize)"
  e2fsck -f -y "$part"
  echo "==> resize2fs to $SHRINK_FS_SIZE (no-op if already smaller)"
  resize2fs "$part" "$SHRINK_FS_SIZE" || true
  echo "==> fsck (post-resize)"
  e2fsck -f -y "$part"
  echo "==> sfdisk: shrink partition 2 to $SHRINK_P2_SECTORS sectors"
  echo ", $SHRINK_P2_SECTORS" | sfdisk --no-reread -N 2 "$LOOP"
  sfdisk -l "$LOOP"
}

# --- orchestration ----------------------------------------------------------
# 1. Mount-required ops first (info, update, rename).
if (( DO_INFO || DO_UPDATE || DO_RENAME )); then
  attach_loop
  mount_root
  (( DO_INFO ))   && op_info
  (( DO_UPDATE )) && op_update
  (( DO_RENAME )) && op_rename
  unmount_root
  # Keep loop for fsck/shrink, otherwise drop it.
  (( DO_FSCK || DO_SHRINK )) || detach_loop
fi

# 2. fsck (partitions must be unmounted).
if (( DO_FSCK )); then
  [[ -n "$LOOP" ]] || attach_loop
  op_fsck
  (( DO_SHRINK )) || detach_loop
fi

# 3. Shrink (needs unmounted partition and an attached loop).
if (( DO_SHRINK )); then
  [[ -n "$LOOP" ]] || attach_loop
  op_shrink
  detach_loop
  echo "==> Truncating image to $SHRINK_IMG_BYTES bytes (30000 MiB)"
  truncate -s "$SHRINK_IMG_BYTES" "$IMG"
fi

# 4. Final summary
echo "==> Done."
if (( DO_UPDATE || DO_SHRINK || DO_RENAME )); then
  ls -lah "$IMG"
  fdisk -l "$IMG" | head -10
fi
